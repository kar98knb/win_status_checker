"""
ETW Real-Time Consumer

用 OpenTraceW + ProcessTraceW 消费一个 real-time session 的事件。
事件立即打包成紧凑二进制塞到 deque 环形（避免 Python dict 开销），
Ctrl+C 或告警时 dump 到 gzip 压缩的二进制文件。

架构:
    kernel buffer
        ↓ 内核推送
    ProcessTraceW 回调（在独立线程里跑）
        ↓ struct.pack
    deque[bytes]  ← 环形，maxlen 控制内存
        ↓ dump()
    events.bin.gz  ← Ctrl+C 时序列化
"""

import ctypes
import ctypes.wintypes as wt
import gzip
import io
import logging
import struct
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger("etw.consumer")


# ============ 结构体定义 ============
# 从 evntcons.h / evntrace.h 抄的
# https://learn.microsoft.com/en-us/windows/win32/api/evntrace/ns-evntrace-event_trace_logfilew
# https://learn.microsoft.com/en-us/windows/win32/api/evntcons/ns-evntcons-event_header
# https://learn.microsoft.com/en-us/windows/win32/api/evntcons/ns-evntcons-event_record


# EVENT_HEADER — 每个 ETW 事件的固定 header（evntcons.h）
# 原型（简化）:
#   typedef struct _EVENT_HEADER {
#       USHORT Size;                     // 整个 event record 的大小
#       USHORT HeaderType;
#       USHORT Flags;
#       USHORT EventProperty;
#       ULONG  ThreadId;
#       ULONG  ProcessId;
#       LARGE_INTEGER TimeStamp;         // 100ns 单位
#       GUID   ProviderId;               // 事件的 provider
#       EVENT_DESCRIPTOR EventDescriptor;// 详见下面
#       union {
#         struct { ULONG KernelTime; ULONG UserTime; } DUMMYSTRUCTNAME;
#         ULONG64 ProcessorTime;
#       } DUMMYUNIONNAME;
#       GUID   ActivityId;
#   } EVENT_HEADER;
class EVENT_DESCRIPTOR(ctypes.Structure):
    """EVENT_DESCRIPTOR (evntprov.h) — 事件元数据"""
    _fields_ = [
        ("Id",       wt.USHORT),      # event ID
        ("Version",  ctypes.c_ubyte),
        ("Channel",  ctypes.c_ubyte),
        ("Level",    ctypes.c_ubyte), # 严重级别
        ("Opcode",   ctypes.c_ubyte),
        ("Task",     wt.USHORT),
        ("Keyword",  ctypes.c_uint64),
    ]


class _GUID(ctypes.Structure):
    """本地版 GUID（不引入循环 import）"""
    _fields_ = [
        ("Data1", wt.DWORD),
        ("Data2", wt.WORD),
        ("Data3", wt.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class EVENT_HEADER(ctypes.Structure):
    _fields_ = [
        ("Size",             wt.USHORT),
        ("HeaderType",       wt.USHORT),
        ("Flags",            wt.USHORT),
        ("EventProperty",    wt.USHORT),
        ("ThreadId",         wt.ULONG),
        ("ProcessId",        wt.ULONG),
        ("TimeStamp",        ctypes.c_int64),
        ("ProviderId",       _GUID),
        ("EventDescriptor",  EVENT_DESCRIPTOR),
        # union 里两种视角，我们只用 KernelTime/UserTime
        ("KernelTime",       wt.ULONG),
        ("UserTime",         wt.ULONG),
        ("ActivityId",       _GUID),
    ]


# ETW_BUFFER_CONTEXT — 事件来自哪个 CPU/logger
class ETW_BUFFER_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("ProcessorNumber", ctypes.c_ubyte),
        ("Alignment",       ctypes.c_ubyte),
        ("LoggerId",        wt.USHORT),
    ]


# EVENT_HEADER_EXTENDED_DATA_ITEM — 扩展数据（stack、TS ID 等）
# 我们不用，只做占位
class EVENT_HEADER_EXTENDED_DATA_ITEM(ctypes.Structure):
    _fields_ = [
        ("Reserved1",   wt.USHORT),
        ("ExtType",     wt.USHORT),
        ("Reserved2",   wt.USHORT),
        ("DataSize",    wt.USHORT),
        ("DataPtr",     ctypes.c_uint64),
    ]


# EVENT_RECORD — Windows 8+ 的现代事件 payload 结构（推荐用这个）
# https://learn.microsoft.com/en-us/windows/win32/api/evntcons/ns-evntcons-event_record
#
# 原型:
#   typedef struct _EVENT_RECORD {
#       EVENT_HEADER              EventHeader;
#       ETW_BUFFER_CONTEXT        BufferContext;
#       USHORT                    ExtendedDataCount;
#       USHORT                    UserDataLength;   // payload 字节数
#       PEVENT_HEADER_EXTENDED_DATA_ITEM ExtendedData;
#       PVOID                     UserData;         // 指向 payload 起始处
#       PVOID                     UserContext;
#   } EVENT_RECORD;
class EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventHeader",         EVENT_HEADER),
        ("BufferContext",       ETW_BUFFER_CONTEXT),
        ("ExtendedDataCount",   wt.USHORT),
        ("UserDataLength",      wt.USHORT),
        ("ExtendedData",        ctypes.POINTER(EVENT_HEADER_EXTENDED_DATA_ITEM)),
        ("UserData",            ctypes.c_void_p),
        ("UserContext",         ctypes.c_void_p),
    ]


PROCESS_TRACE_MODE_REAL_TIME       = 0x00000100
PROCESS_TRACE_MODE_EVENT_RECORD    = 0x10000000
PROCESS_TRACE_MODE_RAW_TIMESTAMP   = 0x00001000


# 回调函数类型 (WINAPI, 参数是 PEVENT_RECORD, 返回 void)
EVENT_RECORD_CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.POINTER(EVENT_RECORD))


# EVENT_TRACE_HEADER_CLASS - EVENT_TRACE_HEADER 里的 Class 子结构
# （原本是 union，pywintrace 展开成 struct）
class EVENT_TRACE_HEADER_CLASS(ctypes.Structure):
    _fields_ = [
        ("Type",     ctypes.c_ubyte),
        ("Level",    ctypes.c_ubyte),
        ("Version",  ctypes.c_uint16),
    ]


# EVENT_TRACE_HEADER (evntrace.h) — 老式（MOF）EVENT_TRACE 的 header
# 布局参考 pywintrace / Windows SDK evntrace.h
# 48 字节 (x64)。
#
# 注意：跟"新" EVENT_HEADER（evntcons.h）完全是两个东西，别搞混：
#   - EVENT_TRACE_HEADER 用在 EVENT_TRACE 里（我们只做占位）
#   - EVENT_HEADER 用在 EVENT_RECORD 里（我们真正读事件的地方）
class EVENT_TRACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("Size",           wt.USHORT),
        ("HeaderType",     ctypes.c_ubyte),
        ("MarkerFlags",    ctypes.c_ubyte),
        ("Class",          EVENT_TRACE_HEADER_CLASS),
        ("ThreadId",       wt.ULONG),
        ("ProcessId",      wt.ULONG),
        ("TimeStamp",      ctypes.c_int64),
        ("Guid",           _GUID),
        ("ClientContext",  wt.ULONG),
        ("Flags",          wt.ULONG),
    ]


# EVENT_TRACE (evntrace.h) — MOF 时代的老事件结构
# 我们不用它（用新的 EVENT_RECORD），但 EVENT_TRACE_LOGFILEW 里有它做占位字段
class EVENT_TRACE(ctypes.Structure):
    _fields_ = [
        ("Header",           EVENT_TRACE_HEADER),
        ("InstanceId",       wt.ULONG),
        ("ParentInstanceId", wt.ULONG),
        ("ParentGuid",       _GUID),
        ("MofData",          ctypes.c_void_p),
        ("MofLength",        wt.ULONG),
        ("ClientContext",    wt.ULONG),
    ]


# TIME_ZONE_INFORMATION (winbase.h) — 172 字节
class TIME_ZONE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Bias",         wt.LONG),
        ("StandardName", ctypes.c_wchar * 32),
        ("StandardDate", ctypes.c_uint16 * 8),   # SYSTEMTIME = 8 × WORD = 16 bytes
        ("StandardBias", wt.LONG),
        ("DaylightName", ctypes.c_wchar * 32),
        ("DaylightDate", ctypes.c_uint16 * 8),
        ("DaylightBias", wt.LONG),
    ]


# TRACE_LOGFILE_HEADER (evntrace.h) — 由 Windows 填回来的 session/文件元信息
# 我们不读它，但 EVENT_TRACE_LOGFILEW 里必须有它做占位字段
# 布局参考 pywintrace（Windows SDK 里 Version/VersionDetail 是 union，
# StartBuffers/PointerSize/EventsLost/CpuSpeedInMHz 也是 union，展开后用这些字段名）
class TRACE_LOGFILE_HEADER(ctypes.Structure):
    _fields_ = [
        ("BufferSize",         wt.ULONG),
        ("MajorVersion",       ctypes.c_byte),
        ("MinorVersion",       ctypes.c_byte),
        ("SubVersion",         ctypes.c_byte),
        ("SubMinorVersion",    ctypes.c_byte),
        ("ProviderVersion",    wt.ULONG),
        ("NumberOfProcessors", wt.ULONG),
        ("EndTime",            ctypes.c_int64),
        ("TimerResolution",    wt.ULONG),
        ("MaximumFileSize",    wt.ULONG),
        ("LogFileMode",        wt.ULONG),
        ("BuffersWritten",     wt.ULONG),
        ("StartBuffers",       wt.ULONG),
        ("PointerSize",        wt.ULONG),
        ("EventsLost",         wt.ULONG),
        ("CpuSpeedInMHz",      wt.ULONG),
        ("LoggerName",         wt.LPWSTR),
        ("LogFileName",        wt.LPWSTR),
        ("TimeZone",           TIME_ZONE_INFORMATION),
        ("BootTime",           ctypes.c_int64),
        ("PerfFreq",           ctypes.c_int64),
        ("StartTime",          ctypes.c_int64),
        ("ReservedFlags",      wt.ULONG),
        ("BuffersLost",        wt.ULONG),
    ]


# EVENT_TRACE_LOGFILEW — 传给 OpenTraceW 的 session 描述
# https://learn.microsoft.com/en-us/windows/win32/api/evntrace/ns-evntrace-event_trace_logfilew
#
# 原型:
#   typedef struct _EVENT_TRACE_LOGFILEW {
#       LPWSTR LogFileName;              // NULL 表示 real-time session
#       LPWSTR LoggerName;               // real-time 时填 session 名
#       LONGLONG CurrentTime;
#       ULONG BuffersRead;
#       union { PROCESS_TRACE_MODE; ULONG LogFileMode; };
#       EVENT_TRACE CurrentEvent;                    // 占位
#       TRACE_LOGFILE_HEADER LogfileHeader;          // 占位
#       PEVENT_TRACE_BUFFER_CALLBACKW BufferCallback;
#       ULONG BufferSize; Filled; EventsLost;
#       union {
#         PEVENT_CALLBACK EventCallback;             // 老版本
#         PEVENT_RECORD_CALLBACK EventRecordCallback;// Vista+ 推荐
#       };
#       ULONG IsKernelTrace;
#       PVOID Context;
#   } EVENT_TRACE_LOGFILEW;
#
# 重点：CurrentEvent 和 LogfileHeader 的字节大小必须精确对齐，否则后面的
# EventRecordCallback 字段错位，Windows 就找不到我们的回调函数指针。
class EVENT_TRACE_LOGFILEW(ctypes.Structure):
    _fields_ = [
        ("LogFileName",         wt.LPWSTR),
        ("LoggerName",          wt.LPWSTR),
        ("CurrentTime",         ctypes.c_int64),
        ("BuffersRead",         wt.ULONG),
        ("ProcessTraceMode",    wt.ULONG),
        ("CurrentEvent",        EVENT_TRACE),
        ("LogfileHeader",       TRACE_LOGFILE_HEADER),
        ("BufferCallback",      ctypes.c_void_p),
        ("BufferSize",          wt.ULONG),
        ("Filled",              wt.ULONG),
        ("EventsLost",          wt.ULONG),
        ("EventRecordCallback", EVENT_RECORD_CALLBACK),
        ("IsKernelTrace",       wt.ULONG),
        ("Context",             ctypes.c_void_p),
    ]


# ============ API 绑定 ============

advapi32 = ctypes.windll.advapi32

# OpenTraceW — 打开一个用于消费的 session（可以是 real-time 或 .etl 文件）
# 返回 TRACEHANDLE，失败返回 INVALID_PROCESSTRACE_HANDLE (0xFFFFFFFFFFFFFFFF)
OpenTraceW = advapi32.OpenTraceW
OpenTraceW.restype = ctypes.c_uint64
OpenTraceW.argtypes = [ctypes.POINTER(EVENT_TRACE_LOGFILEW)]

INVALID_PROCESSTRACE_HANDLE = 0xFFFFFFFFFFFFFFFF

# ProcessTrace — 阻塞式地消费 handle 数组里所有 session 的事件
# 每个事件回调你的 EventRecordCallback。real-time session 只有 session 停时才返回
ProcessTrace = advapi32.ProcessTrace
ProcessTrace.restype = wt.ULONG
ProcessTrace.argtypes = [
    ctypes.POINTER(ctypes.c_uint64),  # HandleArray
    wt.ULONG,                          # HandleCount
    ctypes.c_void_p,                   # StartTime (LPFILETIME, 可 NULL)
    ctypes.c_void_p,                   # EndTime (LPFILETIME, 可 NULL)
]

CloseTrace = advapi32.CloseTrace
CloseTrace.restype = wt.ULONG
CloseTrace.argtypes = [ctypes.c_uint64]


# ============ 事件打包格式 ============
# 紧凑二进制布局，consumer 收到 EVENT_RECORD 后立即打包成 bytes 塞 deque。
# 目的：避免 Python dict 的 600 字节内存开销，让每事件仅 ~90 字节
#
# 布局（50 字节 header + 变长 payload）:
#   偏移  字段              大小
#   0     timestamp         8   (int64, 100ns)
#   8     provider_guid    16   (bytes)
#   24    event_id          2   (uint16)
#   26    level             1   (uint8)
#   27    opcode            1   (uint8)
#   28    keyword           8   (uint64)
#   36    process_id        4   (uint32)
#   40    thread_id         4   (uint32)
#   44    processor         1   (uint8)
#   45    pad               1
#   46    payload_len       2   (uint16)
#   48    pad               2
#   50+   payload           N
_PACKED_HEADER = struct.Struct("<Q16sHBBQIIBxHxx")
PACKED_HEADER_SIZE = _PACKED_HEADER.size
assert PACKED_HEADER_SIZE == 50, f"header 大小应为 50 字节，实际 {PACKED_HEADER_SIZE}"


def unpack_event(data: bytes) -> dict:
    """把 pack 好的 bytes 还原成 dict（供 analyzer 用）"""
    if len(data) < PACKED_HEADER_SIZE:
        raise ValueError(f"event bytes 太短: {len(data)} < {PACKED_HEADER_SIZE}")
    (
        timestamp, guid, event_id, level, opcode, keyword,
        pid, tid, processor, payload_len,
    ) = _PACKED_HEADER.unpack_from(data, 0)
    payload = data[PACKED_HEADER_SIZE:PACKED_HEADER_SIZE + payload_len]
    return {
        "timestamp":     timestamp,
        "provider_guid": guid.hex(),
        "event_id":      event_id,
        "level":         level,
        "opcode":        opcode,
        "keyword":       keyword,
        "process_id":    pid,
        "thread_id":     tid,
        "processor":     processor,
        "payload":       bytes(payload),
    }


_PAYLOAD_LEN_OFFSET = 46  # payload_len 字段在 header 里的偏移


def read_dump(path: Path):
    """读一个 dump 文件（.bin 或 .bin.gz），yield 每个事件 bytes"""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as f:
        while True:
            header = f.read(PACKED_HEADER_SIZE)
            if len(header) < PACKED_HEADER_SIZE:
                break
            payload_len = struct.unpack_from("<H", header, _PAYLOAD_LEN_OFFSET)[0]
            payload = f.read(payload_len) if payload_len else b""
            yield header + payload


# ============ Consumer 主类 ============

class EtwConsumer:
    """
    Real-time session 的 consumer。
    在独立线程里跑 ProcessTraceW，收到事件立即打包塞 deque。
    """

    def __init__(self, session_name: str, ring_capacity: int = 1_000_000):
        """
        Args:
            session_name: 要消费的 real-time session 名（与 EtwRealtimeSession 一致）
            ring_capacity: 内存环形 buffer 最多保留多少个事件
        """
        self._session_name = session_name
        self._trace_handle = 0
        self._thread: Optional[threading.Thread] = None
        self._running = False

        self.ring: deque = deque(maxlen=ring_capacity)
        self._ring_lock = threading.Lock()

        # 统计
        self.total_events = 0
        self.total_bytes = 0
        self.dropped_events = 0

        # 保住 callback 引用（防 GC），Windows 拿这个函数指针
        self._callback = EVENT_RECORD_CALLBACK(self._on_event)

    def _on_event(self, record_ptr):
        """
        ETW 回调：把 EVENT_RECORD 打包成紧凑 bytes 塞进 deque。
        必须尽量快，慢了会丢事件（RealTimeBuffersLost 增加）。
        """
        try:
            rec = record_ptr.contents
            hdr = rec.EventHeader
            desc = hdr.EventDescriptor
            payload_len = rec.UserDataLength
            # GUID 16 字节
            guid_bytes = bytes(ctypes.string_at(ctypes.byref(hdr.ProviderId), 16))
            # 打包 header
            packed_header = _PACKED_HEADER.pack(
                hdr.TimeStamp,
                guid_bytes,
                desc.Id,
                desc.Level,
                desc.Opcode,
                desc.Keyword,
                hdr.ProcessId,
                hdr.ThreadId,
                rec.BufferContext.ProcessorNumber,
                payload_len,
            )
            # 拷 payload
            if payload_len > 0 and rec.UserData:
                payload = ctypes.string_at(rec.UserData, payload_len)
            else:
                payload = b""

            data = packed_header + payload
            with self._ring_lock:
                if len(self.ring) == self.ring.maxlen:
                    self.dropped_events += 1
                self.ring.append(data)
                self.total_events += 1
                self.total_bytes += len(data)
        except Exception as e:
            # callback 里不能抛异常，否则 ProcessTrace 崩
            logger.error(f"callback error: {e}", exc_info=True)

    def start(self):
        """启动 consumer 线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name=f"EtwConsumer-{self._session_name}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[{self._session_name}] consumer 线程已启动")

    def _run(self):
        """OpenTraceW + ProcessTrace，阻塞直到 session 停止"""
        logfile = EVENT_TRACE_LOGFILEW()
        ctypes.memset(ctypes.byref(logfile), 0, ctypes.sizeof(logfile))
        logfile.LogFileName = None

        # 关键：给 LoggerName 显式分配 wchar buffer 并保住引用。
        # 直接 logfile.LoggerName = self._session_name 会有坑——ctypes 会
        # 创建一个临时 wchar buffer 把地址塞进字段，但不持有 buffer 的引用，
        # 函数返回前就可能被 GC，Windows 拿到悬空指针会找不到 session。
        self._logger_name_buf = ctypes.create_unicode_buffer(self._session_name)
        logfile.LoggerName = ctypes.cast(self._logger_name_buf, wt.LPWSTR)

        logfile.ProcessTraceMode = (
            PROCESS_TRACE_MODE_REAL_TIME
            | PROCESS_TRACE_MODE_EVENT_RECORD
        )
        logfile.EventRecordCallback = self._callback

        # 保住 logfile 引用，防止 ProcessTrace 期间被 GC
        self._logfile = logfile

        handle = OpenTraceW(ctypes.byref(logfile))
        if handle == INVALID_PROCESSTRACE_HANDLE:
            err = ctypes.get_last_error()
            logger.error(f"OpenTraceW 失败, 错误码={err}")
            self._running = False
            return

        # OpenTraceW 返回 TRACEHANDLE (ULONG64)。ctypes restype 有时会被误当 int 处理，
        # 显式包一层保证正确
        self._trace_handle = ctypes.c_uint64(handle)
        logger.info(f"[{self._session_name}] OpenTraceW 成功, handle=0x{handle:016x}")
        logger.info(
            f"  BufferSize={logfile.BufferSize}, "
            f"LogfileMode/TraceMode=0x{logfile.ProcessTraceMode:x}, "
            f"EventRecordCallback=0x{ctypes.cast(logfile.EventRecordCallback, ctypes.c_void_p).value or 0:016x}, "
            f"BuffersRead={logfile.BuffersRead}"
        )

        logger.info(f"[{self._session_name}] 开始 ProcessTrace（阻塞直到 session 停止）")
        # 传 byref(单个 TRACEHANDLE)，跟 pywintrace 一致
        status = ProcessTrace(ctypes.byref(self._trace_handle), 1, None, None)
        # ProcessTrace 只在 session 被停时返回
        logger.info(f"[{self._session_name}] ProcessTrace 返回, 状态码 {status}, "
                    f"共接收 {self.total_events} 个事件")
        if status != 0:
            logger.warning(f"[{self._session_name}] ProcessTrace 返回非 0 状态: {status}")

        CloseTrace(self._trace_handle.value)
        self._trace_handle = ctypes.c_uint64(0)
        self._running = False
        logger.info(f"[{self._session_name}] consumer 线程退出")

    def stop(self, timeout: float = 5.0):
        """
        通知 consumer 线程退出。前提是 session 已经被 stop（这会让 ProcessTrace 返回）。
        """
        if not self._thread:
            return
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            logger.warning(f"[{self._session_name}] consumer 线程超时未退出")

    def snapshot_stats(self) -> dict:
        """当前 deque 状态"""
        with self._ring_lock:
            return {
                "total_events":   self.total_events,
                "total_bytes":    self.total_bytes,
                "ring_size":      len(self.ring),
                "ring_capacity":  self.ring.maxlen,
                "dropped_events": self.dropped_events,
            }

    def dump(self, output_file: Path, compress: bool = True):
        """
        把内存 deque 里所有事件序列化到文件。

        Args:
            output_file: 输出路径。compress=True 时会加 .gz 后缀
            compress: 是否 gzip 压缩

        Returns: (event_count, bytes_written)
        """
        output_file = Path(output_file)
        if compress and not str(output_file).endswith(".gz"):
            output_file = output_file.with_suffix(output_file.suffix + ".gz")
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # 拷贝快照，避免锁太久
        with self._ring_lock:
            events = list(self.ring)

        buf = io.BytesIO()
        for e in events:
            buf.write(e)
        raw = buf.getvalue()

        if compress:
            payload = gzip.compress(raw, compresslevel=1)
        else:
            payload = raw
        output_file.write_bytes(payload)

        return len(events), len(payload)

"""
ETW Session 管理

两种 session 模式：
- EtwBufferSession: buffering mode，内存环形 buffer（用于 hang 追溯，从内存 dump 提取）
- EtwFileSession:  file mode circular，磁盘环形文件（用于一般异常记录）
"""

import ctypes
import ctypes.wintypes as wt
import logging
from pathlib import Path
from typing import List, Optional

from .providers import GUID

logger = logging.getLogger("etw.session")

# ============ 常量 ============

WNODE_FLAG_TRACED_GUID = 0x00020000
EVENT_TRACE_FILE_MODE_SEQUENTIAL = 0x00000001
EVENT_TRACE_FILE_MODE_CIRCULAR = 0x00000002
EVENT_TRACE_BUFFERING_MODE = 0x00000400
EVENT_CONTROL_CODE_ENABLE_PROVIDER = 1
EVENT_TRACE_CONTROL_STOP = 1
EVENT_TRACE_CONTROL_FLUSH = 3
EVENT_TRACE_CONTROL_QUERY = 0

# Trace level
TRACE_LEVEL_CRITICAL = 1
TRACE_LEVEL_ERROR = 2
TRACE_LEVEL_WARNING = 3
TRACE_LEVEL_INFORMATION = 4
TRACE_LEVEL_VERBOSE = 5


# ============ 结构体 ============

class WNODE_HEADER(ctypes.Structure):
    _fields_ = [
        ("BufferSize", wt.ULONG),
        ("ProviderId", wt.ULONG),
        ("HistoricalContext", ctypes.c_uint64),
        ("TimeStamp", ctypes.c_int64),
        ("Guid", GUID),
        ("ClientContext", wt.ULONG),
        ("Flags", wt.ULONG),
    ]


class EVENT_TRACE_PROPERTIES(ctypes.Structure):
    _fields_ = [
        ("Wnode", WNODE_HEADER),
        ("BufferSize", wt.ULONG),
        ("MinimumBuffers", wt.ULONG),
        ("MaximumBuffers", wt.ULONG),
        ("MaximumFileSize", wt.ULONG),  # 单位: MB
        ("LogFileMode", wt.ULONG),
        ("FlushTimer", wt.ULONG),       # 单位: 秒
        ("EnableFlags", wt.ULONG),
        ("AgeLimit", ctypes.c_long),
        ("NumberOfBuffers", wt.ULONG),
        ("FreeBuffers", wt.ULONG),
        ("EventsLost", wt.ULONG),
        ("BuffersWritten", wt.ULONG),
        ("LogBuffersLost", wt.ULONG),
        ("RealTimeBuffersLost", wt.ULONG),
        ("LoggerThreadId", wt.HANDLE),
        ("LogFileNameOffset", wt.ULONG),
        ("LoggerNameOffset", wt.ULONG),
    ]


# ============ Event ID 白名单过滤 ============

# EVENT_FILTER_DESCRIPTOR.Type 常量
EVENT_FILTER_TYPE_EVENT_ID = 0x80000200

# EVENT_FILTER_EVENT_ID 结构（可变长度：末尾跟着 event id 数组）
# 定义头部部分，实际使用时手动构造 buffer
class EVENT_FILTER_EVENT_ID_HEADER(ctypes.Structure):
    _fields_ = [
        ("FilterIn", wt.BOOLEAN),   # TRUE = 白名单（只保留列出的），FALSE = 黑名单
        ("Reserved", ctypes.c_ubyte),
        ("Count", wt.USHORT),       # 后面 event id 数组的长度
        # 后面跟着 USHORT Events[Count]
    ]


class EVENT_FILTER_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Ptr", ctypes.c_uint64),   # 指向过滤数据的指针
        ("Size", wt.ULONG),
        ("Type", wt.ULONG),
    ]


class ENABLE_TRACE_PARAMETERS(ctypes.Structure):
    _fields_ = [
        ("Version", wt.ULONG),
        ("EnableProperty", wt.ULONG),
        ("ControlFlags", wt.ULONG),
        ("SourceId", GUID),
        ("EnableFilterDesc", ctypes.POINTER(EVENT_FILTER_DESCRIPTOR)),
        ("FilterDescCount", wt.ULONG),
    ]

ENABLE_TRACE_PARAMETERS_VERSION_2 = 2


# ============ API 绑定 ============

advapi32 = ctypes.windll.advapi32

StartTraceW = advapi32.StartTraceW
StartTraceW.restype = wt.ULONG
StartTraceW.argtypes = [ctypes.POINTER(ctypes.c_uint64), wt.LPCWSTR, ctypes.c_void_p]

ControlTraceW = advapi32.ControlTraceW
ControlTraceW.restype = wt.ULONG
ControlTraceW.argtypes = [ctypes.c_uint64, wt.LPCWSTR, ctypes.c_void_p, wt.ULONG]

EnableTraceEx2 = advapi32.EnableTraceEx2
EnableTraceEx2.restype = wt.ULONG
EnableTraceEx2.argtypes = [
    ctypes.c_uint64, ctypes.POINTER(GUID), wt.ULONG,
    ctypes.c_ubyte, ctypes.c_uint64, ctypes.c_uint64,
    wt.ULONG, ctypes.c_void_p,
]


# ============ 通用工具 ============

def _alloc_properties(session_name: str, file_name: Optional[str] = None):
    """
    分配 EVENT_TRACE_PROPERTIES 缓冲区
    布局: [PROPERTIES][LogFileName?][LoggerName]
    """
    session_name_bytes = (len(session_name) + 1) * ctypes.sizeof(ctypes.c_wchar)

    if file_name:
        file_name_bytes = (len(file_name) + 1) * ctypes.sizeof(ctypes.c_wchar)
        buf_size = ctypes.sizeof(EVENT_TRACE_PROPERTIES) + file_name_bytes + session_name_bytes
    else:
        file_name_bytes = 0
        buf_size = ctypes.sizeof(EVENT_TRACE_PROPERTIES) + session_name_bytes

    buf = (ctypes.c_ubyte * buf_size)()
    ctypes.memset(buf, 0, buf_size)

    props = ctypes.cast(buf, ctypes.POINTER(EVENT_TRACE_PROPERTIES))
    props.contents.Wnode.BufferSize = buf_size
    props.contents.LoggerNameOffset = ctypes.sizeof(EVENT_TRACE_PROPERTIES) + file_name_bytes

    if file_name:
        props.contents.LogFileNameOffset = ctypes.sizeof(EVENT_TRACE_PROPERTIES)
        # 写入 UTF-16 文件名
        ctypes.memmove(
            ctypes.addressof(buf) + props.contents.LogFileNameOffset,
            ctypes.c_wchar_p(file_name),
            file_name_bytes,
        )

    return buf, props


def _stop_session(session_name: str):
    """停掉指定 session"""
    buf, _ = _alloc_properties(session_name)
    ControlTraceW(0, session_name, buf, EVENT_TRACE_CONTROL_STOP)


# ============ Buffer Session（用于 hang 追溯，暂不使用）============

class EtwBufferSession:
    """
    Buffering mode session。事件仅在内存中环形保留，平时零 IO。
    仅用于 hang 追溯场景（配合内存 dump 使用）。
    """

    def __init__(self, session_name: str = "WinStatusCheckerBuffer",
                 buffer_size_mb: int = 64):
        self._session_name = session_name
        self._buffer_size_mb = buffer_size_mb
        self._trace_handle = ctypes.c_uint64(0)
        self._props_buf = None

    def start(self, providers: List[GUID], level: int = TRACE_LEVEL_VERBOSE) -> bool:
        _stop_session(self._session_name)

        single_buf_kb = 1024
        num_buffers = self._buffer_size_mb * 1024 // single_buf_kb

        self._props_buf, props = _alloc_properties(self._session_name)
        props.contents.Wnode.Flags = WNODE_FLAG_TRACED_GUID
        props.contents.Wnode.ClientContext = 1
        props.contents.BufferSize = single_buf_kb
        props.contents.MinimumBuffers = num_buffers
        props.contents.MaximumBuffers = num_buffers
        props.contents.LogFileMode = EVENT_TRACE_BUFFERING_MODE

        status = StartTraceW(
            ctypes.byref(self._trace_handle),
            self._session_name,
            self._props_buf,
        )
        if status != 0:
            logger.error(f"[{self._session_name}] StartTrace 失败: {status}")
            return False

        logger.info(f"[{self._session_name}] Buffering 已启动, {self._buffer_size_mb}MB 内存 buffer")

        for provider_guid in providers:
            EnableTraceEx2(
                self._trace_handle, ctypes.byref(provider_guid),
                EVENT_CONTROL_CODE_ENABLE_PROVIDER, level,
                0xFFFFFFFFFFFFFFFF, 0, 0, None,
            )
        return True

    def stop(self):
        _stop_session(self._session_name)


# ============ File Session（用于关键事件流水日志）============

class EtwFileSession:
    """
    File mode circular session。事件持续写入 .etl 文件，超过大小限制后循环覆盖。
    用于关键事件流水日志。
    """

    def __init__(self, session_name: str = "WinStatusCheckerFile",
                 log_file: Path = None, max_file_size_mb: int = 500):
        """
        Args:
            session_name: session 名称
            log_file: .etl 输出文件路径
            max_file_size_mb: 最大文件大小（MB），超过后循环覆盖
        """
        self._session_name = session_name
        self._log_file = log_file
        self._max_file_size_mb = max_file_size_mb
        self._trace_handle = ctypes.c_uint64(0)
        self._props_buf = None

    def start(self, providers,
              level: int = TRACE_LEVEL_INFORMATION) -> bool:
        """
        启动 file circular session。

        Args:
            providers: [(guid, keyword, event_id_whitelist), ...] 列表
                       event_id_whitelist=None 表示不做 event id 过滤（订阅全部）
                       event_id_whitelist=[540, 541] 表示只订阅这些 event
            level: 事件级别过滤
        """
        assert self._log_file is not None, "必须指定 log_file"
        self._log_file.parent.mkdir(parents=True, exist_ok=True)

        _stop_session(self._session_name)

        file_path = str(self._log_file.absolute())
        self._props_buf, props = _alloc_properties(self._session_name, file_path)

        props.contents.Wnode.Flags = WNODE_FLAG_TRACED_GUID
        props.contents.Wnode.ClientContext = 1
        props.contents.BufferSize = 64
        props.contents.MinimumBuffers = 4
        props.contents.MaximumBuffers = 16
        props.contents.LogFileMode = EVENT_TRACE_FILE_MODE_CIRCULAR
        props.contents.MaximumFileSize = self._max_file_size_mb
        props.contents.FlushTimer = 1

        status = StartTraceW(
            ctypes.byref(self._trace_handle),
            self._session_name,
            self._props_buf,
        )
        if status != 0:
            logger.error(f"[{self._session_name}] StartTrace 失败: {status}")
            if status == 5:
                logger.error("  权限不足，需要管理员")
            return False

        logger.info(
            f"[{self._session_name}] File circular 已启动, "
            f"文件={file_path}, 最大={self._max_file_size_mb}MB, level={level}"
        )

        # 保存所有 ctypes 结构体的引用，防止 GC（关键！）
        self._filter_refs = []

        enabled = 0
        for entry in providers:
            # 兼容 (guid, keyword) 或 (guid, keyword, event_id_whitelist)
            if len(entry) == 2:
                provider_guid, keyword = entry
                event_id_whitelist = None
            else:
                provider_guid, keyword, event_id_whitelist = entry

            enable_params_ptr = None
            filter_desc = ""

            if event_id_whitelist:
                # 构造 event id 白名单过滤
                refs = self._build_event_id_filter(event_id_whitelist)
                self._filter_refs.append(refs)
                # refs 是 dict，包含 params/filter_desc/filter_buf 的引用
                enable_params_ptr = ctypes.byref(refs["params"])
                filter_desc = f" event_id 白名单={event_id_whitelist}"

            status = EnableTraceEx2(
                self._trace_handle, ctypes.byref(provider_guid),
                EVENT_CONTROL_CODE_ENABLE_PROVIDER, level,
                keyword, 0, 0, enable_params_ptr,
            )

            if status == 0:
                enabled += 1
                logger.info(f"  订阅 {provider_guid} keyword=0x{keyword:x}{filter_desc}")
            else:
                logger.warning(f"订阅失败: {provider_guid} 错误码={status}")

        logger.info(f"[{self._session_name}] 订阅 {enabled}/{len(providers)} 个 provider")
        return True

    def _build_event_id_filter(self, event_ids):
        """
        构造 event id 白名单过滤所需的所有 ctypes 结构。
        返回 dict 包含所有需要保持引用的对象。

        内存布局:
            filter_buf: [FilterIn:1][Reserved:1][Count:2][EventIds:count*2]
            filter_desc: EVENT_FILTER_DESCRIPTOR{Ptr=&filter_buf, Size, Type}
            params: ENABLE_TRACE_PARAMETERS{EnableFilterDesc=&filter_desc, Count=1}
        """
        count = len(event_ids)
        header_size = ctypes.sizeof(EVENT_FILTER_EVENT_ID_HEADER)
        total_size = header_size + count * ctypes.sizeof(wt.USHORT)

        # 1. 分配 filter buffer
        filter_buf = (ctypes.c_ubyte * total_size)()
        ctypes.memset(filter_buf, 0, total_size)

        # 填充 header
        header = ctypes.cast(filter_buf, ctypes.POINTER(EVENT_FILTER_EVENT_ID_HEADER))
        header.contents.FilterIn = 1
        header.contents.Reserved = 0
        header.contents.Count = count

        # 填充 event id 数组
        events_array_type = wt.USHORT * count
        events_ptr = ctypes.cast(
            ctypes.addressof(filter_buf) + header_size,
            ctypes.POINTER(events_array_type)
        )
        for i, eid in enumerate(event_ids):
            events_ptr.contents[i] = eid

        # 2. 分配 EVENT_FILTER_DESCRIPTOR
        filter_desc = EVENT_FILTER_DESCRIPTOR()
        filter_desc.Ptr = ctypes.addressof(filter_buf)
        filter_desc.Size = total_size
        filter_desc.Type = EVENT_FILTER_TYPE_EVENT_ID

        # 3. 分配 ENABLE_TRACE_PARAMETERS
        params = ENABLE_TRACE_PARAMETERS()
        params.Version = ENABLE_TRACE_PARAMETERS_VERSION_2
        params.EnableProperty = 0
        params.ControlFlags = 0
        ctypes.memset(ctypes.byref(params.SourceId), 0, ctypes.sizeof(GUID))
        params.EnableFilterDesc = ctypes.pointer(filter_desc)
        params.FilterDescCount = 1

        # 返回 dict 保持所有引用（重点：三个对象生命周期必须一致）
        return {
            "filter_buf": filter_buf,
            "filter_desc": filter_desc,
            "params": params,
        }

    def get_stats(self) -> dict:
        """获取 session 当前统计"""
        buf, props = _alloc_properties(self._session_name)
        status = ControlTraceW(0, self._session_name, buf, EVENT_TRACE_CONTROL_QUERY)
        if status != 0:
            return {"error": status}
        p = props.contents
        return {
            "buffers_written": p.BuffersWritten,
            "events_lost": p.EventsLost,
            "log_buffers_lost": p.LogBuffersLost,
            "realtime_buffers_lost": p.RealTimeBuffersLost,
            "number_of_buffers": p.NumberOfBuffers,
            "free_buffers": p.FreeBuffers,
        }

    def stop(self):
        _stop_session(self._session_name)
        logger.info(f"[{self._session_name}] 已停止")

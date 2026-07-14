"""
ETW Session 管理

三种 session 模式：
- EtwFileSession:     file mode circular，磁盘环形文件（关键低频事件长期落盘）
- EtwRealtimeSession: real-time mode，事件推给用户态 consumer，零磁盘 IO
                      （广撒网订阅，consumer 侧维护内存环形，Ctrl+C 时 dump）
- EtwBufferSession:   buffering mode，仅内存 buffer，靠 crash dump 提取
                      （目前没用，Save-EtwTraceSession 对它不生效）
"""

import ctypes
import ctypes.wintypes as wt
import logging
from pathlib import Path
from typing import List, Optional

from .providers import GUID

logger = logging.getLogger("etw.session")

# ============ 常量 ============
# 都是从 SDK 头文件 wmistr.h / evntrace.h 里抄的 #define，Windows API 用它们
# 当作 bitmask 或枚举值。我们只抄用到的，没抄全。

# --- WNODE_HEADER.Flags 位掩码（wmistr.h） ---
# 标识这个 WNODE 的 Guid 字段有效。所有 ETW session 都要设。
WNODE_FLAG_TRACED_GUID = 0x00020000

# --- EVENT_TRACE_PROPERTIES.LogFileMode 位掩码（evntrace.h） ---
EVENT_TRACE_FILE_MODE_SEQUENTIAL = 0x00000001  # 顺序写文件，写满就报错
EVENT_TRACE_FILE_MODE_CIRCULAR   = 0x00000002  # 环形写文件，写满覆盖旧的（我们用这个）
EVENT_TRACE_REAL_TIME_MODE       = 0x00000100  # 实时投递给 consumer，不写文件
EVENT_TRACE_BUFFERING_MODE       = 0x00000400  # 只在内存 buffer 环形保留，不落盘

# --- EnableTraceEx2 的 ControlCode 参数（evntrace.h） ---
EVENT_CONTROL_CODE_ENABLE_PROVIDER = 1  # 启用一个 provider（我们只用这一个）

# --- ControlTraceW 的 ControlCode 参数（evntrace.h） ---
EVENT_TRACE_CONTROL_QUERY = 0  # 查 session 状态
EVENT_TRACE_CONTROL_STOP  = 1  # 停止 session
EVENT_TRACE_CONTROL_FLUSH = 3  # 强制 flush 到磁盘

# --- Trace level（evntrace.h TRACE_LEVEL_*） ---
# EnableTraceEx2 的 Level 参数。数值越大越啰嗦，用作"至少这个级别以上的事件才发"。
# 特殊值：Level=0 (LogAlways) 的事件不受此过滤影响，永远会发。
TRACE_LEVEL_CRITICAL    = 1
TRACE_LEVEL_ERROR       = 2
TRACE_LEVEL_WARNING     = 3
TRACE_LEVEL_INFORMATION = 4
TRACE_LEVEL_VERBOSE     = 5


# ============ 结构体 ============
# 下面全部照抄 SDK 头文件的 struct 布局，字段顺序 / 大小 / 对齐必须一致，
# 否则 Windows 按字节读进去就错位。

# WNODE_HEADER — 所有 WMI/ETW 结构体的通用头（wmistr.h）
# https://learn.microsoft.com/en-us/windows/win32/etw/wnode-header
#
# 原型（简化去掉了 union）：
#   typedef struct _WNODE_HEADER {
#       ULONG          BufferSize;         // 整个 WNODE 的总字节数（含尾部数据）
#       ULONG          ProviderId;         // 保留，填 0
#       ULONG64        HistoricalContext;  // 由 API 填回 trace handle
#       LARGE_INTEGER  TimeStamp;          // API 返回时的时间戳
#       GUID           Guid;               // session 的 GUID（我们不关心，填零）
#       ULONG          ClientContext;      // 时间戳单位：1=QueryPerformanceCounter,
#                                          //           2=系统时间, 3=CPU 计数器
#       ULONG          Flags;              // 位掩码：WNODE_FLAG_TRACED_GUID 等
#   } WNODE_HEADER;
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


# EVENT_TRACE_PROPERTIES — session 的所有配置 + 运行时统计都塞这一个结构体里（evntrace.h）
# https://learn.microsoft.com/en-us/windows/win32/api/evntrace/ns-evntrace-event_trace_properties
#
# 变长布局: [EVENT_TRACE_PROPERTIES][LogFileName wchar_t[]][LoggerName wchar_t[]]
# 两个 *Offset 字段告诉 Windows 字符串放在结构体后面哪个偏移，
# 详见 _alloc_properties() 里的拼装。
#
# 用途分两拨：
#   - 传给 StartTraceW: 我们填 BufferSize/LogFileMode/MaximumFileSize 等【输入】字段
#   - ControlTraceW(QUERY) 返回时：Windows 填 BuffersWritten/EventsLost 等【输出】字段
#
# 原型：
#   typedef struct _EVENT_TRACE_PROPERTIES {
#       WNODE_HEADER Wnode;               // 见上面
#       ULONG BufferSize;                 // 单个 buffer 大小（KB）
#       ULONG MinimumBuffers;             // 最少 buffer 个数
#       ULONG MaximumBuffers;             // 最多 buffer 个数
#       ULONG MaximumFileSize;            // .etl 文件最大大小（MB），环形写模式用
#       ULONG LogFileMode;                // EVENT_TRACE_FILE_MODE_* / BUFFERING 位掩码
#       ULONG FlushTimer;                 // 强制 flush 间隔（秒），0=只有 buffer 满才 flush
#       ULONG EnableFlags;                // 旧版 NT Kernel Logger 用，新版本忽略
#       LONG  AgeLimit;                   // 保留字段
#       ULONG NumberOfBuffers;            // [输出] 当前 buffer 总数
#       ULONG FreeBuffers;                // [输出] 空闲 buffer 数
#       ULONG EventsLost;                 // [输出] 因 buffer 满被丢的事件数
#       ULONG BuffersWritten;             // [输出] 已写入磁盘的 buffer 数
#       ULONG LogBuffersLost;             // [输出] 写盘失败丢失的 buffer 数
#       ULONG RealTimeBuffersLost;        // [输出] 实时消费者跟不上丢的 buffer 数
#       HANDLE LoggerThreadId;            // [输出] logger 线程 handle
#       ULONG LogFileNameOffset;          // [输入] 文件名相对结构体首地址的偏移
#       ULONG LoggerNameOffset;           // [输入] session 名相对结构体首地址的偏移
#   } EVENT_TRACE_PROPERTIES;
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
# 这三个结构体互相嵌套，专门用来在 EnableTraceEx2 里做 event id 级别的过滤。
# 内存布局（三层指针链）：
#
#   ENABLE_TRACE_PARAMETERS
#       └── EnableFilterDesc ──► EVENT_FILTER_DESCRIPTOR
#                                    └── Ptr ──► filter_buf 裸内存块
#                                                 └── [EVENT_FILTER_EVENT_ID][USHORT Events[]]

# EVENT_FILTER_DESCRIPTOR.Type 的取值（evntprov.h）
# 0x80000200 表示 buffer 里放的是"event id 数组"，让 Windows 用它做白/黑名单过滤
EVENT_FILTER_TYPE_EVENT_ID = 0x80000200


# EVENT_FILTER_EVENT_ID — event id 数组的头部（evntprov.h）
# https://learn.microsoft.com/en-us/windows/win32/api/evntprov/ns-evntprov-event_filter_event_id
#
# 变长结构体：末尾跟着 USHORT Events[Count]。ctypes 里只声明头部，
# 用 memcpy 或指针切片往后填 event id 数组。
#
# 原型：
#   typedef struct _EVENT_FILTER_EVENT_ID {
#       BOOLEAN FilterIn;       // TRUE=白名单（只留列出的）, FALSE=黑名单
#       UCHAR   Reserved;
#       USHORT  Count;          // 后面数组的元素个数
#       USHORT  Events[ANYSIZE_ARRAY];   // 具体的 event id 列表
#   } EVENT_FILTER_EVENT_ID;
class EVENT_FILTER_EVENT_ID_HEADER(ctypes.Structure):
    _fields_ = [
        ("FilterIn", wt.BOOLEAN),
        ("Reserved", ctypes.c_ubyte),
        ("Count", wt.USHORT),
        # 尾部 USHORT Events[Count] 手动拼
    ]


# EVENT_FILTER_DESCRIPTOR — 通用"过滤器描述符"，指向过滤数据本体（evntprov.h）
# https://learn.microsoft.com/en-us/windows/desktop/api/Evntprov/ns-evntprov-event_filter_descriptor
#
# Windows 用 (Type, Ptr, Size) 三元组描述"过滤数据在哪儿、什么格式、多大"。
# Type 决定 Windows 怎么解析 Ptr 指向的数据。我们只用 EVENT_ID 类型。
#
# 原型：
#   typedef struct _EVENT_FILTER_DESCRIPTOR {
#       ULONGLONG Ptr;    // 指向过滤数据（这里是 EVENT_FILTER_EVENT_ID 结构）
#       ULONG     Size;   // 过滤数据字节数
#       ULONG     Type;   // EVENT_FILTER_TYPE_* 中的一个
#   } EVENT_FILTER_DESCRIPTOR;
class EVENT_FILTER_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Ptr", ctypes.c_uint64),
        ("Size", wt.ULONG),
        ("Type", wt.ULONG),
    ]


# ENABLE_TRACE_PARAMETERS — EnableTraceEx2 第 8 个参数指向的配置结构（evntrace.h）
# https://learn.microsoft.com/en-us/windows/win32/api/evntrace/ns-evntrace-enable_trace_parameters
#
# 我们只用它来挂 event id 过滤器。原本还可以放 provider 私有配置，我们没用。
#
# 原型：
#   typedef struct _ENABLE_TRACE_PARAMETERS {
#       ULONG  Version;                            // 必须填 2
#       ULONG  EnableProperty;                     // EVENT_ENABLE_PROPERTY_* 位掩码，0=默认
#       ULONG  ControlFlags;                       // 保留，填 0
#       GUID   SourceId;                           // 谁启用的这个 provider（诊断用，可全零）
#       PEVENT_FILTER_DESCRIPTOR EnableFilterDesc; // 指向过滤器描述符（数组）
#       ULONG  FilterDescCount;                    // 数组元素个数（我们只用一个，填 1）
#   } ENABLE_TRACE_PARAMETERS;
class ENABLE_TRACE_PARAMETERS(ctypes.Structure):
    _fields_ = [
        ("Version", wt.ULONG),
        ("EnableProperty", wt.ULONG),
        ("ControlFlags", wt.ULONG),
        ("SourceId", GUID),
        ("EnableFilterDesc", ctypes.POINTER(EVENT_FILTER_DESCRIPTOR)),
        ("FilterDescCount", wt.ULONG),
    ]

# Version 字段必须填 2（对应 Windows 8.1+ 的结构布局）
ENABLE_TRACE_PARAMETERS_VERSION_2 = 2


# ============ API 绑定 ============
# ETW 相关 API 都在 advapi32.dll，Windows 装机就有。
# 每个 API 都要设 restype 和 argtypes，否则 ctypes 会按 int 默认 marshal 参数，
# 64 位指针/handle 会被截成 32 位，直接段错误或返回 87 (INVALID_PARAMETER)。

advapi32 = ctypes.windll.advapi32


# StartTraceW — 创建并启动一个 ETW session
# https://learn.microsoft.com/en-us/windows/win32/api/evntrace/nf-evntrace-starttracew
#
# 原型:
#   ULONG StartTraceW(
#       _Out_ PTRACEHANDLE           TraceHandle,     // 输出：新 session 的 handle
#       _In_  LPCWSTR                InstanceName,    // 输入：session 名（要 UTF-16）
#       _Inout_ PEVENT_TRACE_PROPERTIES Properties    // 输入输出：session 配置
#   );
#
# 返回值：ERROR_SUCCESS(0) 成功，非 0 是 Win32 错误码（比如 5=权限不足，183=session 已存在）
StartTraceW = advapi32.StartTraceW
StartTraceW.restype = wt.ULONG
StartTraceW.argtypes = [
    ctypes.POINTER(ctypes.c_uint64),  # TraceHandle (out)  — TRACEHANDLE = ULONG64
    wt.LPCWSTR,                       # InstanceName        — session 名字
    ctypes.c_void_p,                  # Properties          — 变长结构体，用 void* 避开类型
]


# ControlTraceW — 停止 / 查询 / flush 一个已有 session
# https://learn.microsoft.com/en-us/windows/win32/api/evntrace/nf-evntrace-controltracew
#
# 原型:
#   ULONG ControlTraceW(
#       _In_    TRACEHANDLE              TraceHandle,   // handle 或 0（后者用 name 找）
#       _In_    LPCWSTR                  InstanceName,  // session 名字
#       _Inout_ PEVENT_TRACE_PROPERTIES  Properties,    // 配置/输出
#       _In_    ULONG                    ControlCode    // EVENT_TRACE_CONTROL_STOP/FLUSH/QUERY
#   );
ControlTraceW = advapi32.ControlTraceW
ControlTraceW.restype = wt.ULONG
ControlTraceW.argtypes = [
    ctypes.c_uint64,   # TraceHandle
    wt.LPCWSTR,        # InstanceName
    ctypes.c_void_p,   # Properties
    wt.ULONG,          # ControlCode
]


# EnableTraceEx2 — 给已启动的 session 挂上 / 取下 provider 订阅
# https://learn.microsoft.com/en-us/windows/win32/api/evntrace/nf-evntrace-enabletraceex2
#
# 原型:
#   ULONG EnableTraceEx2(
#       _In_ TRACEHANDLE                TraceHandle,        // 之前 StartTrace 返回的
#       _In_ LPCGUID                    ProviderId,         // 要订阅的 provider GUID
#       _In_ ULONG                      ControlCode,        // 1=启用, 0=禁用
#       _In_ UCHAR                      Level,              // TRACE_LEVEL_*
#       _In_ ULONGLONG                  MatchAnyKeyword,    // 位掩码：任意 bit 匹配就发
#       _In_ ULONGLONG                  MatchAllKeyword,    // 位掩码：必须全部 bit 匹配才发
#       _In_ ULONG                      Timeout,            // 0=异步立即返回
#       _In_opt_ PENABLE_TRACE_PARAMETERS EnableParameters  // 过滤器等扩展参数，可 NULL
#   );
#
# Match*Keyword 的过滤逻辑：
#   如果 MatchAnyKeyword=0，等于不按 keyword 过滤（全接收）
#   否则 event 的 keyword 位掩码要满足：
#       (event_kw & MatchAnyKeyword) != 0  AND  (event_kw & MatchAllKeyword) == MatchAllKeyword
EnableTraceEx2 = advapi32.EnableTraceEx2
EnableTraceEx2.restype = wt.ULONG
EnableTraceEx2.argtypes = [
    ctypes.c_uint64,          # TraceHandle
    ctypes.POINTER(GUID),     # ProviderId
    wt.ULONG,                 # ControlCode
    ctypes.c_ubyte,           # Level
    ctypes.c_uint64,          # MatchAnyKeyword
    ctypes.c_uint64,          # MatchAllKeyword
    wt.ULONG,                 # Timeout
    ctypes.c_void_p,          # EnableParameters (optional)
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
    Buffering mode session。事件仅在内核内存环形 buffer 里循环，平时零磁盘 IO。

    需要 snapshot 到 .etl 文件时，用 Save-EtwTraceSession PowerShell cmdlet
    （或底层的 MSFT_EtwTraceSession.Send CIM 方法）。
    """

    def __init__(self, session_name: str = "WinStatusCheckerBuffer",
                 buffer_size_mb: int = 64):
        self._session_name = session_name
        self._buffer_size_mb = buffer_size_mb
        self._trace_handle = ctypes.c_uint64(0)
        self._props_buf = None
        self._filter_refs = []

    def start(self, providers, level: int = TRACE_LEVEL_INFORMATION) -> bool:
        """
        启动 buffering mode session。

        Args:
            providers: [(guid, keyword, event_id_whitelist), ...] 与 EtwFileSession 一致
            level: 事件级别过滤
        """
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
            if status == 5:
                logger.error("  权限不足，需要管理员")
            return False

        logger.info(
            f"[{self._session_name}] Buffering 已启动, "
            f"{self._buffer_size_mb}MB 内存 buffer ({num_buffers} × 1024KB), level={level}"
        )

        enabled = 0
        for entry in providers:
            if len(entry) == 2:
                provider_guid, keyword = entry
                event_id_whitelist = None
            else:
                provider_guid, keyword, event_id_whitelist = entry

            enable_params_ptr = None
            filter_info = ""
            if event_id_whitelist:
                # 复用 EtwFileSession 的 filter 构造逻辑
                refs = EtwFileSession._build_event_id_filter(self, event_id_whitelist)
                self._filter_refs.append(refs)
                enable_params_ptr = ctypes.byref(refs["params"])
                filter_info = f" event_id 白名单={event_id_whitelist}"

            status = EnableTraceEx2(
                self._trace_handle, ctypes.byref(provider_guid),
                EVENT_CONTROL_CODE_ENABLE_PROVIDER, level,
                keyword, 0, 0, enable_params_ptr,
            )
            if status == 0:
                enabled += 1
                logger.info(f"  订阅 {provider_guid} keyword=0x{keyword:x}{filter_info}")
            else:
                logger.warning(f"订阅失败: {provider_guid} 错误码={status}")

        logger.info(f"[{self._session_name}] 订阅 {enabled}/{len(providers)} 个 provider")
        return True

    def get_stats(self) -> dict:
        """获取 session 当前统计"""
        buf, props = _alloc_properties(self._session_name)
        status = ControlTraceW(
            self._trace_handle.value, None, buf, EVENT_TRACE_CONTROL_QUERY,
        )
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


# ============ Realtime Session（事件推给用户态 consumer，零磁盘 IO）============

class EtwRealtimeSession:
    """
    Real-time mode session。事件通过内核 buffer 实时推送给 consumer 线程，
    不写任何磁盘文件。

    用法：
        1. session.start(providers)
        2. 另开一个 consumer 线程用 EtwConsumer.process() 拉事件
        3. Ctrl+C 时先 stop consumer 再 stop session

    LogFileMode = EVENT_TRACE_REAL_TIME_MODE 让 Windows 知道这个 session
    没有 .etl 文件，事件应该等 consumer 用 OpenTraceW+ProcessTrace 来拉。
    """

    def __init__(self, session_name: str = "WinStatusCheckerRealtime",
                 buffer_size_kb: int = 128,
                 min_buffers: int = 32, max_buffers: int = 64):
        """
        Args:
            session_name: session 名称
            buffer_size_kb: 单个内核 buffer 大小（KB）
            min_buffers / max_buffers: 内核 buffer 池上下限
                buffer 少了 consumer 慢会丢事件；buffer 多了浪费内存
                默认 128 KB × 32~64 = 4~8 MB 内核 buffer 池，足够扛
                consumer 短暂卡顿（比如 GC / 内存分配）
        """
        self._session_name = session_name
        self._buffer_size_kb = buffer_size_kb
        self._min_buffers = min_buffers
        self._max_buffers = max_buffers
        self._trace_handle = ctypes.c_uint64(0)
        self._props_buf = None
        self._filter_refs = []

    def start(self, providers, level: int = TRACE_LEVEL_INFORMATION) -> bool:
        """
        启动 real-time session。

        Args:
            providers: [(guid, keyword, event_id_whitelist), ...] 与 EtwFileSession 一致
            level: 事件级别过滤
        """
        _stop_session(self._session_name)

        self._props_buf, props = _alloc_properties(self._session_name)
        props.contents.Wnode.Flags = WNODE_FLAG_TRACED_GUID
        props.contents.Wnode.ClientContext = 1  # QueryPerformanceCounter 时间戳
        props.contents.BufferSize = self._buffer_size_kb
        props.contents.MinimumBuffers = self._min_buffers
        props.contents.MaximumBuffers = self._max_buffers
        # 关键：只设 REAL_TIME_MODE，不带 FILE_MODE 的位；LogFileNameOffset 保持 0
        props.contents.LogFileMode = EVENT_TRACE_REAL_TIME_MODE
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
            f"[{self._session_name}] Real-time 已启动, "
            f"buffer={self._buffer_size_kb}KB × {self._min_buffers}~{self._max_buffers}, "
            f"level={level}"
        )

        enabled = 0
        for entry in providers:
            if len(entry) == 2:
                provider_guid, keyword = entry
                event_id_whitelist = None
            else:
                provider_guid, keyword, event_id_whitelist = entry

            enable_params_ptr = None
            filter_info = ""
            if event_id_whitelist:
                # 复用 EtwFileSession 的 filter 构造逻辑
                refs = EtwFileSession._build_event_id_filter(self, event_id_whitelist)
                self._filter_refs.append(refs)
                enable_params_ptr = ctypes.byref(refs["params"])
                filter_info = f" event_id 白名单={event_id_whitelist}"

            status = EnableTraceEx2(
                self._trace_handle, ctypes.byref(provider_guid),
                EVENT_CONTROL_CODE_ENABLE_PROVIDER, level,
                keyword, 0, 0, enable_params_ptr,
            )
            if status == 0:
                enabled += 1
                logger.info(f"  订阅 {provider_guid} keyword=0x{keyword:x}{filter_info}")
            else:
                logger.warning(f"订阅失败: {provider_guid} 错误码={status}")

        logger.info(f"[{self._session_name}] 订阅 {enabled}/{len(providers)} 个 provider")
        return True

    def get_stats(self) -> dict:
        """获取 session 当前统计"""
        buf, props = _alloc_properties(self._session_name)
        status = ControlTraceW(
            self._trace_handle.value, None, buf, EVENT_TRACE_CONTROL_QUERY,
        )
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

    @property
    def session_name(self) -> str:
        """consumer 需要用这个名字 OpenTraceW"""
        return self._session_name


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
        # ETW buffer 上限 16 MB per buffer，PC 内存充足给宽点。
        # 256 KB × 32 buffer = 8 MB 内存 buffer 池，足够扛几十秒的事件突发
        props.contents.BufferSize = 256
        props.contents.MinimumBuffers = 16
        props.contents.MaximumBuffers = 32
        props.contents.LogFileMode = EVENT_TRACE_FILE_MODE_CIRCULAR
        props.contents.MaximumFileSize = self._max_file_size_mb
        # 60 秒才强制 flush，让 buffer 填得多一些再写盘
        # File Session 用作"事后复盘"，几十秒延迟能接受
        # 历史踩坑：BufferSize=64 + FlushTimer=1 → 空 buffer 也被刷 → 306 KB/s
        # 历史踩坑：BufferSize=8  + FlushTimer=60 → 事件突发装不下 → lost=118/min
        props.contents.FlushTimer = 60

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

    # Windows 定义的 event id 白名单最大长度（evntprov.h MAX_EVENT_FILTER_EVENT_ID_COUNT）
    # 超过这个数，EnableTraceEx2 会返回 87 (INVALID_PARAMETER)
    MAX_EVENT_FILTER_EVENT_ID_COUNT = 64

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
        if count > self.MAX_EVENT_FILTER_EVENT_ID_COUNT:
            raise ValueError(
                f"event id 白名单长度 {count} 超过 Windows 上限 "
                f"{self.MAX_EVENT_FILTER_EVENT_ID_COUNT}，请精简"
            )
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
        # QUERY 时 Windows 会回填 LoggerName / LogFileName 字符串到 buffer 末尾，
        # 必须多留 2KB 空间（session 名 + 文件名各 1024 wchar），否则报 234 (MORE_DATA)。
        buf, props = _alloc_properties(
            self._session_name, str(self._log_file.absolute())
        )
        status = ControlTraceW(
            self._trace_handle.value, None, buf, EVENT_TRACE_CONTROL_QUERY,
        )
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

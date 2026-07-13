"""
项目配置文件
"""

# ============ ETW 采集配置 ============

# .etl 文件最大大小（MB），超过后循环覆盖
ETL_MAX_SIZE_MB = 500

# 事件级别过滤: 1=Critical, 2=Error, 3=Warning, 4=Information, 5=Verbose
# 默认 Information，保留有诊断价值的 Info 事件（进程启停、频率变化等）
# 高频背景事件（DxgKrnl Present 等）用 event id 白名单单独过滤
ETW_LEVEL = 4


# ============ ETW Event ID 白名单 ============
#
# 某些 provider（如 DxgKrnl）的高频事件被标为 Level=0 (LogAlways) 且
# Keywords 为空，导致 Level 过滤和 Keyword 黑名单都无效。
# 对这类 provider，用 event id 白名单：只保留列表中的 event id，其他全部丢弃。
#
# 格式: {provider_name: [event_id, ...]}
# 如果 provider 不在这个 dict 里，表示不做 event id 过滤（订阅全部）。

ETW_EVENT_ID_WHITELIST = {
    # DxgKrnl: 只保留 TDR（GPU 驱动超时恢复）相关事件
    "DxgKrnl": [
        540,  # TdrPayloadEngineTimeout - GPU 引擎超时
        541,  # TdrPayloadVSyncTimeout - VSync 超时
        547,  # TdrCaptureDumpStart - 开始生成 TDR dump
        548,  # TdrCaptureDumpFinish - TDR dump 完成
    ],
    # Kernel-Disk: 只保留 flush 事件（read/write 太密集）
    # event 10=Read, 11=Write, 14=Flush
    "Kernel-Disk": [
        14,  # 磁盘 flush（低频，能反映磁盘压力）
    ],
}


# ============ ETW Keyword 黑名单 ============
#
# 每个 provider 的 keyword 定义可用命令查询：
#   logman query providers "<provider name>"
#
# 逻辑：默认订阅所有 keyword，然后从中排除黑名单里的位。
# 最终传给 EnableTraceEx2 的 MatchAnyKeyword = ~sum(黑名单 keywords)
#
# 格式: {provider_name: [(keyword_value, keyword_name, reason), ...]}

ETW_KEYWORD_BLACKLIST = {
    # DxgKrnl (GPU) - 事件量最大的 provider，主要是每帧一个的 Present 事件
    "DxgKrnl": [
        (0x0000000008000000, "Present",
         "每帧一个事件，60fps=60/s，游戏时更高。帧率信息价值低，不用于诊断"),
        (0x0000000000000040, "Resource",
         "GPU 资源创建/销毁事件，量大且日常无用"),
        (0x0000000000000080, "Memory",
         "显存分配事件，量大；显存耗尽会通过 Base/Error 事件反映"),
        (0x0000000000200000, "VidMmWorkerThread",
         "显存管理线程内部事件，量大且无诊断价值"),
        (0x0000000000000002, "Profiler",
         "GPU profiler 事件，仅性能分析用"),
        (0x0000000000000004, "References",
         "对象引用计数事件，量大且无用"),
        (0x0000000000000100, "StatusChangeNotify",
         "状态变更通知，低价值高频"),
        (0x0000000020000000, "PerfData",
         "性能计数器数据，高频"),
    ],

    # Kernel-Process - 进程/线程事件
    "Kernel-Process": [
        (0x0000000000000020, "THREAD",
         "线程启停事件量大，进程级别的 START/STOP 已够用"),
        (0x0000000000000040, "IMAGE",
         "DLL 加载事件，游戏启动时几百个"),
        (0x0000000000000080, "CPU_PRIORITY",
         "CPU 优先级变化事件，频率高"),
        (0x0000000000000100, "OTHER_PRIORITY",
         "其他优先级事件，频率高"),
        (0x0000000000002000, "WORK_ON_BEHALF",
         "内部工作项事件"),
    ],

    # CPU-Power - CPU 电源/频率
    "CPU-Power": [
        (0x0000000000000001, "Perf",
         "CPU 性能计数器高频采样"),
        (0x0000000000000100, "EnergyEstimation",
         "能耗估算，高频"),
        # 保留: Diag(0x2), PowerDiagnostics(0x4), Profiles(0x40) 这些低频关键事件
    ],

    # TCPIP - 网络协议栈
    "TCPIP": [
        (0x0000000000000100, "Transfer",
         "每个数据包的传输事件，量最大"),
        (0x0000000000000004, "Tcb",
         "TCB(传输控制块)事件，每个连接持续产生"),
        (0x0000000000000800, "Rss",
         "接收端缩放事件，高频"),
        (0x0000000000000040, "Ctcp",
         "复合 TCP 内部事件"),
        (0x0000000100000000, "SendPath",
         "发送路径细节，每包一个"),
        (0x0000000200000000, "ReceivePath",
         "接收路径细节，每包一个"),
        # 保留: Endpoint, ConnectPath, ClosePath, Dropped, Diagnosis, Interface
    ],

    # NDIS - 网卡链路层（如果订阅）
    "NDIS": [
        # NDIS 事件默认量不大，先不做黑名单
    ],

    # Kernel-PnP - 设备即插即用（事件本来就少，无需过滤）
    "Kernel-PnP": [],

    # Kernel-Disk - 磁盘 I/O
    # 只有 Analytic keyword (0x8000000000000000)，不做 keyword 黑名单
    # 通过 event id 白名单只保留 flush（见上面）
    "Kernel-Disk": [],

    # Kernel-Memory - 内存管理
    # 保留 MEMINFO(0x20)、MEMINFO_NODE(0x400)、WS_SWAP，
    # 屏蔽高频的 PHYSICAL_ALLOC 和 ACG。
    # 注意：实测 filter_validation memory_pressure 场景里，Kernel-Memory 的
    #   MEMINFO id=1 payload 直接给可用页数（FreePageCount 等），是判断
    #   内存压力最直接的信号，主流程务必消费这个事件。
    "Kernel-Memory": [
        (0x0000000000000200, "PHYSICAL_ALLOC",
         "物理内存分配事件，量非常大"),
    ],

    # Kernel-Power - 系统电源管理（休眠/唤醒/温度/idle）
    # 实测（io_estimate.py）不加过滤时每秒 8000+ 事件，占总 IO 65%
    # 保留: Diagnostic(0x4), Thermal(0x20), SleepDiagnostic(0x1000),
    #      WakeDiagnostics(0x10000)
    #      —— 这些是"事后重建"用得着的诊断事件
    "Kernel-Power": [
        (0x0000000000000001, "Scenario",
         "电源场景标记，量大"),
        (0x0000000000000002, "Simple",
         "简单周期性 tick 事件 (event 557)，最高频"),
        (0x0000000000000008, "Performance",
         "电源性能采样，高频"),
        (0x0000000000000010, "Idle",
         "CPU idle 状态切换，每次进出 idle 都发"),
        (0x0000000000000040, "PerfTrackContext",
         "性能跟踪上下文，高频"),
        (0x0000000000000080, "PowerSetting",
         "电源设置变更（含高频的 ACPI 事件）"),
        (0x0000000000000100, "RuntimeFx",
         "运行时电源框架事件"),
        (0x0000000000004000, "TimerResolution",
         "定时器分辨率变化，游戏切换时会多"),
        (0x0000000000008000, "PowerAggregator",
         "电源聚合器"),
    ],

    # USB-USBPORT - USB 2.0 端口层
    # 现有测试机上事件量极低（不到 100 个/2min），暂不做过滤
    "USB-USBPORT": [],

    # USB-USBHUB3 - USB 3.0 集线器
    "USB-USBHUB3": [],

    # BTH-BTHPORT / BTH-BTHUSB - Bluetooth 协议栈
    "BTH-BTHPORT": [],
    "BTH-BTHUSB": [],

    # Input-HIDCLASS - HID 类驱动
    "Input-HIDCLASS": [],

    # Kernel-Audio - 音频子系统
    # 待观察，暂不过滤
    "Kernel-Audio": [],
}


# ============ 日志配置 ============

LOG_DIR = "logs"
LOG_MAX_SIZE_MB = 50
LOG_BACKUP_COUNT = 5
LOG_RETAIN_DAYS = 7


# ============ 进程优先级 ============

# "idle" / "below_normal" / "normal"
PROCESS_PRIORITY = "below_normal"

"""
项目配置文件
"""

# ============ ETW 采集配置 ============

# .etl 文件最大大小（MB），超过后循环覆盖（用于 File Session）
ETL_MAX_SIZE_MB = 500

# 事件级别过滤: 1=Critical, 2=Error, 3=Warning, 4=Information, 5=Verbose
# 默认 Information，保留有诊断价值的 Info 事件（进程启停、频率变化等）
# 高频背景事件（DxgKrnl Present 等）用 event id 白名单单独过滤
ETW_LEVEL = 4


# ============ 双 Session 架构 ============
#
# 我们跑两个 ETW session，覆盖不同的故障场景：
#
#   Session A: File Circular（长期落盘）
#     - 极窄订阅，只收"崩溃/掉线"这种确凿的低频关键事件
#     - IO 极低（~50 KB/s），SSD 无感
#     - 目的：蓝屏/hang 后重启，能从落盘的 .etl 复盘
#
#   Session B: Real-Time Consumer（纯内存 deque + Ctrl+C dump）
#     - 广撒网订阅，事件通过 kernel → consumer → Python 内存环形
#     - 零磁盘 IO（除了 Ctrl+C 时一次性 dump ~10 MB gzip）
#     - 目的：用户感知卡顿时立即 Ctrl+C，拿到最近 N 分钟历史
#
# 两个 session 事件不重合，各司其职。

# --- Session A (File Session) 订阅哪些 provider ---
# 用 provider name 作 key，跟 ETW_KEYWORD_BLACKLIST / ETW_EVENT_ID_WHITELIST 一致
ETW_FILE_SESSION_PROVIDERS = [
    "Kernel-Process",   # id 1/2 = START/STOP + ExitCode，识别进程崩溃
    "DxgKrnl",          # 通过 event id 白名单只保留 TDR（540/541/547/548）
    "Kernel-PnP",       # 设备加载/卸载（USB 断连之类）
    "Kernel-Memory",    # MEMINFO 事件，反映内存压力
    "TCPIP",            # 网络连接断开事件
]

# --- Session B (Realtime Consumer) 订阅哪些 provider ---
# 剩下所有需要广撒网的 provider，不落盘所以事件多点没关系
ETW_REALTIME_PROVIDERS = [
    "CPU-Power",        # CPU 频率/idle 状态变化，反映 CPU 状态
    "Kernel-Power",     # 系统电源事件（休眠/唤醒/温度）
    "Kernel-Disk",      # 磁盘 IO（不做过滤，看瞬时 spike）
    "USB-USBPORT",      # USB 2.0 端口层
    "USB-USBHUB3",      # USB 3.0 集线器
    "USB-USBXHCI",      # USB 3.0 主控（Selective Suspend）
    "BTH-BTHPORT",      # Bluetooth 协议栈
    "BTH-BTHUSB",       # Bluetooth USB 传输层
    "Input-HIDCLASS",   # HID 类驱动
    "Kernel-Audio",     # 音频子系统（buffer underrun 之类）
]


# ============ ETW Event ID 白名单 ============
#
# 某些 provider（如 DxgKrnl）的高频事件被标为 Level=0 (LogAlways) 且
# Keywords 为空，导致 Level 过滤和 Keyword 黑名单都无效。
# 对这类 provider，用 event id 白名单：只保留列表中的 event id，其他全部丢弃。
#
# 格式: {provider_name: [event_id, ...]}
# 如果 provider 不在这个 dict 里，表示不做 event id 过滤（订阅全部）。

#
# 白名单基于 filter_validation 5 个场景（cpu_saturation / cpu_throttle /
# disk_io_spike / memory_pressure / network_disconnect / process_crash）的
# filtered.report.xml + events.xml 统计：只保留"某场景下显著出现"的 event id，
# 剔除背景噪音（比如 Kernel-Process id=21 ThreadWorkOnBehalfUpdate）。
#
# 每个 event id 后面的注释说明它讲的 story——即"看到这个事件说明系统里发生了什么"。

ETW_EVENT_ID_WHITELIST = {
    # ==== DxgKrnl - GPU 驱动超时（TDR）====
    # 罕见事件，是"GPU 卡死"的确凿信号
    "DxgKrnl": [
        540,   # TdrPayloadEngineTimeout    → GPU 引擎超时（3D/Video/Compute 某个 engine 卡死）
        541,   # TdrPayloadVSyncTimeout     → VSync 超时（画面撕裂/掉帧最直接的信号）
        547,   # TdrCaptureDumpStart        → TDR 恢复开始生成 dump
        548,   # TdrCaptureDumpFinish       → TDR dump 完成（意味着已经"重启"过 GPU 一次）
    ],

    # ==== Kernel-Process - 进程生命周期 ====
    # 识别进程崩溃、DLL 加载/卸载模式
    # ⚠️ 排除 id=21 ThreadWorkOnBehalfUpdate（4万/2min，纯背景噪音）
    "Kernel-Process": [
        1,     # ProcessStart               → 新进程启动（有 CommandLine，能识别谁启动了什么）
        2,     # ProcessStop                → 进程退出（含 ExitCode，能区分正常退出 vs 崩溃 0xC0000005）
        3,     # ThreadStart                → 线程启动（配合 5/6 反映进程活跃度）
        5,     # ImageLoad                  → DLL 被加载到进程（游戏启动几百个）
        6,     # ImageUnload                → DLL 从进程卸载
        10,    # IoPriorityChange           → 进程 I/O 优先级变化（用户操作 vs 后台）
    ],

    # ==== Kernel-PnP - 设备即插即用 ====
    # 网卡/USB/HID 断连时会大量出现
    # 主 story：一次断连一般 500/501/502 循环 + 700/701 驱动 unload/load + 各 subsystem 事件
    "Kernel-PnP": [
        500,   # DevQuery_QueryProcessing    → 设备查询开始
        501,   # DevQuery_QueryProcessing    → 处理设备状态变化（网卡断连时最活跃，一次 ~2800 个）
        502,   # DevQuery_QueryProcessing    → 处理完成
        503,   # DevQuery_QueryProcessing    → 查询完成
        700,   # CfgMgr_DeviceList           → 设备列表变化（驱动 load）
        701,   # CfgMgr_DeviceList           → 设备列表变化（驱动 unload）
        702,   # CfgMgr_DeviceList           → PnP 通知开始
        703,   # CfgMgr_DeviceList           → PnP 通知完成
        # 800~815 段：NetworkStack 相关（网卡断连 100% 出现）
        800, 801, 802, 803, 804,
        807, 808, 813, 814, 815,
        # 850 段：另一批 subsystem 状态事件
        850, 851, 860,
        # 1100~1200 段：网络驱动 rundown（Disable/Enable-NetAdapter 触发）
        1102, 1103, 1104, 1108, 1109, 1110, 1111,
        1120, 1121, 1122, 1132,
        1170, 1171, 1175, 1176, 1177,
        1190, 1191,
    ],

    # ==== TCPIP - 网络协议栈 ====
    # 用户断网、游戏丢连接、DNS 失败都在这里
    # 主 story: SYN → 建连 → 传输 → FIN/RST → 关闭
    #
    # ⚠️ Windows 上限 MAX_EVENT_FILTER_EVENT_ID_COUNT = 64 个 event id
    #    TCPIP 场景太丰富，我们必须挑核心的。原始 70 个的完整列表见 git 历史
    #    （commit 前的版本），砍掉的都是"network_disconnect 独有的低频通知类事件"，
    #    留下的是"任意场景都可能出现的连接生命周期事件"。
    "TCPIP": [
        # 连接生命周期 —— 建连/断开的完整状态机（story 的骨架）
        1001,  # TcpEndpointCreation         → TCP endpoint 创建（socket() 调用）
        1002,  # TcpRequestConnect           → 请求建连（connect() 调用）
        1003,  # TcpInspectConnectComplete   → connect 通过防火墙
        1004,  # TcpTcbSynSend               → 发出 SYN 包
        1008,  # TcpBindEndpointComplete     → bind() 完成
        1009,  # TcpCloseEndpoint            → endpoint 关闭（socket 释放）
        1013,  # TcpCreateEndpointComplete   → endpoint 创建完成
        1031,  # TcpConnectTcbProceeding     → 建连中
        1033,  # TcpConnectTcbComplete       → 三次握手完成
        1038,  # TcpCloseTcbRequest          → 请求关闭连接（close 起始）
        1039,  # TcpAbortTcbRequest          → 请求强制中止（RST 发出，异常断连的关键信号）
        1043,  # TcpDisconnectTcbComplete    → 断开完成
        1044,  # TcpShutdownTcb              → shutdown() 调用
        1051,  # TcpTcbStateChange           → 状态机迁移（Established → Closing 等）
        1176,  # TcpDeliveryFin              → 收到 FIN（对方主动关闭）
        1603,  # TcpDisconnect               → 应用层发起断开

        # UDP 生命周期
        1391,  # UdpCreateEndpointComplete   → UDP endpoint 创建
        1396,  # UdpBindEndpointComplete     → UDP bind
        1397,  # UdpCloseEndpointBound       → UDP 关闭
        1398,  # UdpCloseEndpointUnBound     → UDP 未绑定关闭

        # 端口分配（每次建连都发一对，能反映连接数量）
        1191,  # TcpAcquirePort              → 分配端口
        1193,  # TcpReleasePort              → 释放端口

        # 数据传输相关（低频但关键）
        1074,  # TcpDataTransferReceive      → 收到数据（不含每包详情）
        1223,  # TcpTemplateParameters       → 连接模板参数（RTO/CwndRestart）
        1454,  # InetInspect (Send)          → 防火墙检查发送方向
        1455,  # InetInspect (AcquirePort)   → 防火墙检查端口获取
        1544,  # TcpipSetSockOpt             → setsockopt() 调用（游戏设置 TCP keepalive）

        # 网络接口/路由状态变化（断线时会激增）
        1486,  # TcpipStatusIndication       → 接口状态变化通知（NDIS status）
        1639,  # IpDestinationCacheInvalidation → IP 目标缓存失效（网络配置变化）

        # 路由/邻居/UDP 状态（低频，网络异常时会出现）
        1017, 1021, 1034, 1040,
        1127, 1128, 1130, 1136, 1137, 1144, 1145, 1146,
        1184, 1194, 1226, 1230,
        1433, 1434, 1435, 1436, 1437, 1438,   # NIC rundown
        1466, 1467, 1468, 1478, 1479,          # 网络重传/超时
        1485, 1490, 1491, 1497,
        1514, 1521, 1524, 1526,
        # 目前 64 个，正好卡在 Windows 上限 MAX_EVENT_FILTER_EVENT_ID_COUNT
        # 如果要新增，先从上面砍一个再加
    ],

    # ==== Kernel-Memory - 内存管理 ====
    # MEMINFO/MEMINFO_NODE 的 payload 里带可用页数，是内存压力核心指标
    "Kernel-Memory": [
        1,     # MemInfo                     → 内存快照（FreePageCount/ZeroPageCount，判断压力）
        2,     # MemInfoEx                   → 内存快照扩展信息
        8,     # Acg                         → Arbitrary Code Guard 状态（Windows 安全机制状态）
        11,    # (network_disconnect 独有，可能是 NIC 驱动分页事件)
        12,    # MemInfoNode                 → NUMA 节点内存统计（多路 CPU 相关）
        14,    # (network_disconnect 独有)
    ],

    # 注意：以下 provider 只在 Realtime session 里订阅，Realtime 不应用 event id 白名单：
    #   CPU-Power / Kernel-Power / Kernel-Disk / USB-* / BTH-* / Input-HIDCLASS / Kernel-Audio
    # 所以它们不需要在这里列白名单。
    # 如果未来 Kernel-Power event 557 tick 太吵，考虑加"event id 黑名单"机制单独砍。
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
    #
    # 实测（io_estimate.py）Kernel-Power 每 2min 发 45 万事件，占总 IO 66%。
    # 主要凶手：event 557（"259" task，属于 Diagnostic keyword），
    # 每秒几千个 tick 型事件，价值极低。
    #
    # ⚠️ 命名陷阱：微软的 `Diagnostic` keyword 不是"故障诊断"专用，
    #   它包含了大量高频周期性事件。所以要屏蔽。
    # ⚠️ TimerResolution 单独砍不够——event 63/95 keyword 是
    #   Diagnostic|TimerResolution 复合，只要不砍 Diagnostic 就漏。
    #
    # 保留: Thermal(0x20), SleepDiagnostic(0x1000), WakeDiagnostics(0x10000),
    #      PowerSetting(0x80) —— 休眠/唤醒/温度/电源计划切换
    "Kernel-Power": [
        (0x0000000000000001, "Scenario",
         "电源场景标记，量大"),
        (0x0000000000000002, "Simple",
         "简单周期性 tick 事件"),
        (0x0000000000000004, "Diagnostic",
         "电源诊断（陷阱：含高频 tick 事件 557），占总 IO 一半"),
        (0x0000000000000008, "Performance",
         "电源性能采样，高频"),
        (0x0000000000000010, "Idle",
         "CPU idle 状态切换，每次进出 idle 都发"),
        (0x0000000000000040, "PerfTrackContext",
         "性能跟踪上下文，高频"),
        (0x0000000000000100, "RuntimeFx",
         "运行时电源框架事件"),
        (0x0000000000000400, "DiagnosticLight",
         "轻量诊断事件"),
        (0x0000000000004000, "TimerResolution",
         "定时器分辨率变化"),
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

    # USB-USBXHCI - USB 3.0 主控层（比 Hub3 更底层）
    # 主要抓 Selective Suspend 引起的 D-state 变化
    "USB-USBXHCI": [],
}


# ============ 日志配置 ============

LOG_DIR = "logs"
LOG_MAX_SIZE_MB = 50
LOG_BACKUP_COUNT = 5
LOG_RETAIN_DAYS = 7


# ============ 进程优先级 ============

# "idle" / "below_normal" / "normal"
PROCESS_PRIORITY = "below_normal"

"""
项目配置文件
调整监控频率、报警阈值等参数
"""

# 监控采样间隔（秒）- 越小越实时，但越吃资源
# 推荐 2-3 秒，对游戏几乎无影响
MONITOR_INTERVAL = 2

# Web 服务端口
WEB_PORT = 8870

# 报警阈值
ALERT_THRESHOLDS = {
    # 网络相关
    "packet_loss_percent": 5,        # 丢包率超过 5% 报警
    "latency_ms": 100,               # 延迟超过 100ms 报警
    "jitter_ms": 30,                 # 抖动超过 30ms 报警
    "network_down_seconds": 10,      # 网络断开超过 10 秒报警

    # GPU 相关
    "gpu_temp_celsius": 85,          # GPU 温度超过 85°C 报警
    "gpu_usage_percent": 98,         # GPU 使用率持续 98% 报警
    "gpu_memory_percent": 95,        # 显存使用超过 95% 报警

    # 系统资源
    "memory_percent": 90,            # 内存使用超过 90% 报警
    "cpu_throttle_ratio": 0.7,       # CPU 频率低于最大值 70% 视为降频

    # 驱动相关
    "driver_check_interval": 30,     # 驱动状态检查间隔（秒）

    # 启动检测
    "min_refresh_hz": 120,           # 期望最低刷新率
    "min_memory_gb": 8.0,            # 期望最低内存
}

# 日志配置
LOG_DIR = "logs"
LOG_MAX_SIZE_MB = 50
LOG_BACKUP_COUNT = 5
CLEAR_LOGS_ON_START = True

# Web 页面刷新间隔（秒）
WEB_REFRESH_INTERVAL = 2

# 进程优先级：设为 "below_normal" 确保不抢游戏资源
# 可选: "idle", "below_normal", "normal"
PROCESS_PRIORITY = "below_normal"

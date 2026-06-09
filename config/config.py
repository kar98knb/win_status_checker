"""
项目配置文件
调整监控频率、报警阈值等参数
"""

# 监控采样间隔（秒）- 越小越实时，但越吃资源
# 推荐 2-3 秒，对游戏几乎无影响
MONITOR_INTERVAL = 2

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
LOG_RETAIN_DAYS = 7              # 日志保留天数，超过自动清理

# 进程优先级：设为 "below_normal" 确保不抢游戏资源
# 可选: "idle", "below_normal", "normal"
PROCESS_PRIORITY = "below_normal"

# 进程焦点白名单（这些进程高占用是正常的，不会被锁定为焦点）
FOCUS_WHITELIST = {
    # 浏览器
    "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe",
    # 通讯
    "discord.exe", "telegram.exe", "wechat.exe", "qq.exe", "teams.exe",
    # 系统
    "explorer.exe", "dwm.exe", "csrss.exe", "svchost.exe", "system",
    "searchhost.exe", "runtimebroker.exe", "shellexperiencehost.exe",
    # 开发工具
    "code.exe", "devenv.exe", "idea64.exe", "pycharm64.exe",
    # 媒体
    "spotify.exe", "vlc.exe",
    # 本项目
    "python.exe", "python3.exe", "python3.13.exe", "pythonw.exe",
}

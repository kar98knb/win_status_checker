"""
系统资源监控模块
监控：CPU 使用率/温度/频率、内存、磁盘 I/O、后台进程抢占
"""

import time
import psutil
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ProcessInfo:
    """高占用进程信息"""
    name: str = ""
    pid: int = 0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "pid": self.pid,
            "cpu_percent": round(self.cpu_percent, 1),
            "memory_mb": round(self.memory_mb, 0),
        }


@dataclass
class SystemStatus:
    """系统资源状态"""
    # CPU
    cpu_usage_percent: float = 0.0
    cpu_freq_mhz: float = 0.0
    cpu_freq_max_mhz: float = 0.0
    cpu_temp_celsius: float = -1.0  # -1 表示不可用
    cpu_throttled: bool = False     # 是否降频

    # 内存
    memory_total_gb: float = 0.0
    memory_used_gb: float = 0.0
    memory_percent: float = 0.0
    memory_available_gb: float = 0.0

    # 磁盘 I/O
    disk_read_mb_per_sec: float = 0.0
    disk_write_mb_per_sec: float = 0.0
    disk_queue_length: float = 0.0

    # 后台进程抢占
    top_processes: List[ProcessInfo] = field(default_factory=list)
    has_resource_hog: bool = False  # 是否有抢资源的后台进程

    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "cpu_usage_percent": round(self.cpu_usage_percent, 1),
            "cpu_freq_mhz": round(self.cpu_freq_mhz, 0),
            "cpu_freq_max_mhz": round(self.cpu_freq_max_mhz, 0),
            "cpu_temp_celsius": round(self.cpu_temp_celsius, 1),
            "cpu_throttled": self.cpu_throttled,
            "memory_total_gb": round(self.memory_total_gb, 1),
            "memory_used_gb": round(self.memory_used_gb, 1),
            "memory_percent": round(self.memory_percent, 1),
            "memory_available_gb": round(self.memory_available_gb, 1),
            "disk_read_mb_per_sec": round(self.disk_read_mb_per_sec, 1),
            "disk_write_mb_per_sec": round(self.disk_write_mb_per_sec, 1),
            "top_processes": [p.to_dict() for p in self.top_processes],
            "has_resource_hog": self.has_resource_hog,
            "timestamp": self.timestamp,
        }


# 已知的后台抢资源进程
_KNOWN_HOGS = {
    "msmpeng.exe",          # Windows Defender 扫描
    "tiworker.exe",         # Windows Update
    "trustedinstaller.exe", # Windows 模块安装
    "searchindexer.exe",    # Windows 搜索索引
    "compattelrunner.exe",  # 兼容性遥测
    "windowsupdate.exe",
    "msiexec.exe",          # 安装程序
    "svchost.exe",          # 可能是 Windows Update 服务
}


class SystemMonitor:
    """系统资源监控器"""

    def __init__(self):
        self._last_disk_io = psutil.disk_io_counters()
        self._last_disk_time = time.time()
        # 初始化 CPU percent（第一次调用返回 0）
        psutil.cpu_percent(interval=None)

    def collect(self) -> SystemStatus:
        """采集系统资源状态"""
        status = SystemStatus(timestamp=time.time())

        self._collect_cpu(status)
        self._collect_memory(status)
        self._collect_disk_io(status)
        self._collect_top_processes(status)

        return status

    def _collect_cpu(self, status: SystemStatus):
        """采集 CPU 状态"""
        # 使用率（非阻塞，基于上次调用的时间差）
        status.cpu_usage_percent = psutil.cpu_percent(interval=None)

        # 频率
        freq = psutil.cpu_freq()
        if freq:
            status.cpu_freq_mhz = freq.current
            status.cpu_freq_max_mhz = freq.max
            # 降频检测：当前频率低于最大频率的 70%
            if freq.max > 0 and freq.current < freq.max * 0.7:
                status.cpu_throttled = True

        # 温度（Windows 上 psutil 通常拿不到，尝试一下）
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    if entries:
                        status.cpu_temp_celsius = entries[0].current
                        break
        except (AttributeError, Exception):
            # Windows 上 sensors_temperatures 可能不存在
            status.cpu_temp_celsius = -1

    def _collect_memory(self, status: SystemStatus):
        """采集内存状态"""
        mem = psutil.virtual_memory()
        status.memory_total_gb = mem.total / (1024 ** 3)
        status.memory_used_gb = mem.used / (1024 ** 3)
        status.memory_percent = mem.percent
        status.memory_available_gb = mem.available / (1024 ** 3)

    def _collect_disk_io(self, status: SystemStatus):
        """采集磁盘 I/O 速率"""
        try:
            current_io = psutil.disk_io_counters()
            current_time = time.time()
            elapsed = current_time - self._last_disk_time

            if elapsed > 0 and current_io:
                status.disk_read_mb_per_sec = (
                    (current_io.read_bytes - self._last_disk_io.read_bytes)
                    / elapsed / (1024 * 1024)
                )
                status.disk_write_mb_per_sec = (
                    (current_io.write_bytes - self._last_disk_io.write_bytes)
                    / elapsed / (1024 * 1024)
                )

            self._last_disk_io = current_io
            self._last_disk_time = current_time
        except Exception:
            pass

    def _collect_top_processes(self, status: SystemStatus):
        """检测后台高占用进程"""
        try:
            procs = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    info = proc.info
                    cpu = info.get('cpu_percent', 0) or 0
                    mem_info = info.get('memory_info')
                    mem_mb = mem_info.rss / (1024 * 1024) if mem_info else 0

                    # 只关注 CPU > 10% 的进程
                    if cpu > 10:
                        procs.append(ProcessInfo(
                            name=info.get('name', ''),
                            pid=info.get('pid', 0),
                            cpu_percent=cpu,
                            memory_mb=mem_mb,
                        ))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # 按 CPU 使用率排序，取前 5
            procs.sort(key=lambda p: p.cpu_percent, reverse=True)
            status.top_processes = procs[:5]

            # 检测已知的资源抢占进程
            for p in status.top_processes:
                if p.name.lower() in _KNOWN_HOGS and p.cpu_percent > 15:
                    status.has_resource_hog = True
                    break
        except Exception:
            pass

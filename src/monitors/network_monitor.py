"""
网络状态监控模块
监控：网络连通性、延迟、丢包率、上下行速率
"""

import time
import psutil
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NetworkStatus:
    """网络状态数据"""
    is_connected: bool = False
    latency_ms: float = 0.0
    packet_loss_percent: float = 0.0
    bytes_sent_per_sec: float = 0.0
    bytes_recv_per_sec: float = 0.0
    active_connections: int = 0
    adapter_name: str = ""
    adapter_status: str = ""
    dns_ok: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "is_connected": self.is_connected,
            "latency_ms": round(self.latency_ms, 1),
            "packet_loss_percent": round(self.packet_loss_percent, 1),
            "bytes_sent_per_sec": round(self.bytes_sent_per_sec, 0),
            "bytes_recv_per_sec": round(self.bytes_recv_per_sec, 0),
            "active_connections": self.active_connections,
            "adapter_name": self.adapter_name,
            "adapter_status": self.adapter_status,
            "dns_ok": self.dns_ok,
            "timestamp": self.timestamp,
        }


class NetworkMonitor:
    """网络监控器"""

    def __init__(self):
        self._last_io = psutil.net_io_counters()
        self._last_time = time.time()
        # 使用多个目标，TCP 方式测延迟（避免 ICMP 被屏蔽）
        self._tcp_targets = [
            ("www.baidu.com", 80),
            ("dns.alidns.com", 53),
            ("8.8.8.8", 53),
        ]

    def collect(self) -> NetworkStatus:
        """采集一次网络状态"""
        status = NetworkStatus(timestamp=time.time())

        # 1. 网络接口信息
        self._collect_adapter_info(status)

        # 2. 网络流量速率
        self._collect_throughput(status)

        # 3. 延迟和丢包（用 TCP 连接）
        self._collect_ping(status)

        # 4. 活跃连接数
        try:
            connections = psutil.net_connections(kind='inet')
            status.active_connections = len([
                c for c in connections if c.status == 'ESTABLISHED'
            ])
        except (psutil.AccessDenied, PermissionError):
            status.active_connections = -1

        return status

    def _collect_adapter_info(self, status: NetworkStatus):
        """获取网络适配器信息"""
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()

        for name, stat in stats.items():
            # 跳过回环和虚拟接口
            if name.lower() in ('loopback pseudo-interface 1', 'lo'):
                continue
            if stat.isup and name in addrs:
                for addr in addrs[name]:
                    # 找到有 IPv4 地址的活跃接口
                    if addr.family.name == 'AF_INET' and addr.address != '127.0.0.1':
                        status.adapter_name = name
                        status.adapter_status = "正常" if stat.isup else "断开"
                        status.is_connected = True
                        return

        status.adapter_status = "未连接"
        status.is_connected = False

    def _collect_throughput(self, status: NetworkStatus):
        """计算网络吞吐量"""
        current_io = psutil.net_io_counters()
        current_time = time.time()
        elapsed = current_time - self._last_time

        if elapsed > 0:
            status.bytes_sent_per_sec = (
                current_io.bytes_sent - self._last_io.bytes_sent
            ) / elapsed
            status.bytes_recv_per_sec = (
                current_io.bytes_recv - self._last_io.bytes_recv
            ) / elapsed

        self._last_io = current_io
        self._last_time = current_time

    def _collect_ping(self, status: NetworkStatus):
        """通过 TCP 连接检测延迟和丢包（比 ICMP ping 更可靠）"""
        import socket

        successes = 0
        total_latency = 0.0
        attempts = len(self._tcp_targets)

        for host, port in self._tcp_targets:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                start = time.time()
                sock.connect((host, port))
                latency = (time.time() - start) * 1000  # 转为毫秒
                sock.close()
                successes += 1
                total_latency += latency
            except (socket.timeout, socket.error, OSError):
                pass

        if successes > 0:
            status.latency_ms = total_latency / successes
            status.packet_loss_percent = (1 - successes / attempts) * 100
            status.dns_ok = True
        else:
            status.latency_ms = -1
            status.packet_loss_percent = 100
            status.dns_ok = False

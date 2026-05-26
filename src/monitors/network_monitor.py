"""
网络状态监控模块
监控：网络连通性、延迟、丢包率、抖动(Jitter)、上下行速率
"""

import time
import socket
import psutil
from dataclasses import dataclass, field
from typing import Optional, List
from collections import deque


@dataclass
class NetworkStatus:
    """网络状态数据"""
    is_connected: bool = False
    latency_ms: float = 0.0
    packet_loss_percent: float = 0.0
    jitter_ms: float = 0.0          # 网络抖动
    bytes_sent_per_sec: float = 0.0
    bytes_recv_per_sec: float = 0.0
    active_connections: int = 0
    adapter_name: str = ""
    adapter_status: str = ""
    dns_ok: bool = False
    link_down_count: int = 0        # 链路闪断次数（累计）
    nic_errors_delta: int = 0       # 网卡错误包增量（本周期）
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "is_connected": self.is_connected,
            "latency_ms": round(self.latency_ms, 1),
            "packet_loss_percent": round(self.packet_loss_percent, 1),
            "jitter_ms": round(self.jitter_ms, 1),
            "bytes_sent_per_sec": round(self.bytes_sent_per_sec, 0),
            "bytes_recv_per_sec": round(self.bytes_recv_per_sec, 0),
            "active_connections": self.active_connections,
            "adapter_name": self.adapter_name,
            "adapter_status": self.adapter_status,
            "dns_ok": self.dns_ok,
            "link_down_count": self.link_down_count,
            "nic_errors_delta": self.nic_errors_delta,
            "timestamp": self.timestamp,
        }


class NetworkMonitor:
    """网络监控器"""

    def __init__(self, jitter_sample_count: int = 10):
        """
        Args:
            jitter_sample_count: 计算抖动时保留的延迟样本数量
        """
        self._last_io = psutil.net_io_counters()
        self._last_time = time.time()
        # 使用多个目标，TCP 方式测延迟（避免 ICMP 被屏蔽）
        self._tcp_targets = [
            ("www.baidu.com", 80),
            ("dns.alidns.com", 53),
            ("8.8.8.8", 53),
        ]
        # 抖动计算：保留最近 N 次延迟样本
        self._latency_history: deque = deque(maxlen=jitter_sample_count)
        # 链路闪断检测
        self._last_link_up = True
        self._link_down_count = 0
        # 网卡错误包基线
        self._last_errors = {"errin": 0, "errout": 0, "dropin": 0, "dropout": 0}
        self._error_deltas = {"errin": 0, "errout": 0, "dropin": 0, "dropout": 0}
        self._active_nic: Optional[str] = None
        self._init_error_baseline()

    def collect(self) -> NetworkStatus:
        """采集一次网络状态"""
        status = NetworkStatus(timestamp=time.time())

        # 1. 网络接口信息 + 链路闪断检测
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

        # 5. 网卡错误包检测
        self._collect_nic_errors(status)

        return status

    def _init_error_baseline(self):
        """初始化网卡错误包基线"""
        try:
            io_per_nic = psutil.net_io_counters(pernic=True)
            # 找到活跃网卡
            stats = psutil.net_if_stats()
            for name, stat in stats.items():
                if stat.isup and name.lower() not in ('loopback pseudo-interface 1', 'lo'):
                    self._active_nic = name
                    if name in io_per_nic:
                        nic = io_per_nic[name]
                        self._last_errors = {
                            "errin": nic.errin,
                            "errout": nic.errout,
                            "dropin": nic.dropin,
                            "dropout": nic.dropout,
                        }
                    break
        except Exception:
            pass

    def _collect_adapter_info(self, status: NetworkStatus):
        """获取网络适配器信息 + 链路闪断检测"""
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        found = False

        for name, stat in stats.items():
            # 跳过回环和虚拟接口
            if name.lower() in ('loopback pseudo-interface 1', 'lo'):
                continue
            if stat.isup and name in addrs:
                for addr in addrs[name]:
                    # 找到有 IPv4 地址的活跃接口
                    if addr.family.name == 'AF_INET' and addr.address != '127.0.0.1':
                        status.adapter_name = name
                        status.adapter_status = "正常"
                        status.is_connected = True
                        self._active_nic = name
                        found = True
                        break
                if found:
                    break

        if not found:
            status.adapter_status = "未连接"
            status.is_connected = False

        # 链路闪断检测：记录 link 状态变化
        current_link_up = status.is_connected
        if self._last_link_up and not current_link_up:
            # 从连接变为断开 = 一次闪断
            self._link_down_count += 1
        self._last_link_up = current_link_up

        status.link_down_count = self._link_down_count

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
        successes = 0
        total_latency = 0.0
        latencies = []
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
                latencies.append(latency)
            except (socket.timeout, socket.error, OSError):
                pass

        if successes > 0:
            status.latency_ms = total_latency / successes
            status.packet_loss_percent = (1 - successes / attempts) * 100
            status.dns_ok = True

            # 记录延迟样本用于抖动计算
            for lat in latencies:
                self._latency_history.append(lat)

            # 计算抖动（相邻延迟差的平均值）
            status.jitter_ms = self._calculate_jitter()
        else:
            status.latency_ms = -1
            status.packet_loss_percent = 100
            status.dns_ok = False
            status.jitter_ms = -1

    def _calculate_jitter(self) -> float:
        """计算网络抖动（相邻延迟样本差值的平均）"""
        history = list(self._latency_history)
        if len(history) < 2:
            return 0.0

        diffs = [abs(history[i] - history[i - 1]) for i in range(1, len(history))]
        return sum(diffs) / len(diffs)

    def _collect_nic_errors(self, status: NetworkStatus):
        """检测网卡错误包增量（物理层问题指标）"""
        if not self._active_nic:
            return

        try:
            io_per_nic = psutil.net_io_counters(pernic=True)
            if self._active_nic not in io_per_nic:
                return

            nic = io_per_nic[self._active_nic]
            current = {
                "errin": nic.errin,
                "errout": nic.errout,
                "dropin": nic.dropin,
                "dropout": nic.dropout,
            }

            # 计算增量
            self._error_deltas = {
                k: current[k] - self._last_errors[k]
                for k in current
            }
            self._last_errors = current

            status.nic_errors_delta = sum(self._error_deltas.values())
        except Exception:
            status.nic_errors_delta = 0

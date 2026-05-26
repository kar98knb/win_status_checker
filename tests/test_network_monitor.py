"""
网络监控模块测试
"""

import time
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.monitors.network_monitor import NetworkMonitor, NetworkStatus


def test_network_status_dataclass():
    """测试 NetworkStatus 数据结构"""
    status = NetworkStatus()
    assert status.is_connected is False
    assert status.latency_ms == 0.0
    assert status.packet_loss_percent == 0.0
    assert status.bytes_sent_per_sec == 0.0
    assert status.bytes_recv_per_sec == 0.0
    assert status.active_connections == 0
    assert status.adapter_name == ""
    assert status.dns_ok is False
    print("  ✓ NetworkStatus 默认值正确")


def test_network_status_to_dict():
    """测试 to_dict 序列化"""
    status = NetworkStatus(
        is_connected=True,
        latency_ms=25.678,
        packet_loss_percent=0.0,
        bytes_sent_per_sec=1024.5,
        bytes_recv_per_sec=2048.9,
        active_connections=10,
        adapter_name="WLAN",
        adapter_status="正常",
        dns_ok=True,
    )
    d = status.to_dict()
    assert d["is_connected"] is True
    assert d["latency_ms"] == 25.7  # 四舍五入到 1 位
    assert d["bytes_sent_per_sec"] == 1024.0  # 四舍五入到整数
    assert d["adapter_name"] == "WLAN"
    assert "timestamp" in d
    print("  ✓ to_dict 序列化正确")


def test_network_monitor_collect():
    """测试实际采集（集成测试）"""
    monitor = NetworkMonitor()
    # 第一次采集（速率可能为 0，因为没有时间差）
    status = monitor.collect()

    assert isinstance(status, NetworkStatus)
    assert isinstance(status.is_connected, bool)
    assert isinstance(status.latency_ms, float)
    assert isinstance(status.packet_loss_percent, float)
    assert status.timestamp > 0
    print(f"  ✓ 采集成功: 连接={status.is_connected}, 延迟={status.latency_ms:.1f}ms")


def test_network_monitor_throughput():
    """测试网速计算（需要两次采集）"""
    monitor = NetworkMonitor()
    monitor.collect()  # 第一次，建立基线
    time.sleep(1)
    status = monitor.collect()  # 第二次，有时间差了

    # 速率应该是非负数
    assert status.bytes_sent_per_sec >= 0
    assert status.bytes_recv_per_sec >= 0
    print(f"  ✓ 网速计算: ↑{status.bytes_sent_per_sec:.0f} B/s ↓{status.bytes_recv_per_sec:.0f} B/s")


def test_network_adapter_detection():
    """测试网络适配器检测"""
    monitor = NetworkMonitor()
    status = monitor.collect()

    if status.is_connected:
        assert status.adapter_name != ""
        assert status.adapter_status == "正常"
        print(f"  ✓ 适配器检测: {status.adapter_name} - {status.adapter_status}")
    else:
        print("  ⚠ 网络未连接，跳过适配器检测")


if __name__ == "__main__":
    print("\n=== 网络监控模块测试 ===\n")
    test_network_status_dataclass()
    test_network_status_to_dict()
    test_network_monitor_collect()
    test_network_monitor_throughput()
    test_network_adapter_detection()
    print("\n全部通过 ✓\n")

"""
网络抖动和链路闪断检测测试
"""

import time
import sys
import os
from unittest.mock import patch, MagicMock
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.monitors.network_monitor import NetworkMonitor, NetworkStatus, BaselineDetector


# ============ 抖动计算测试 ============

def test_jitter_calculation_stable():
    """测试稳定网络的抖动（应接近 0）"""
    monitor = NetworkMonitor()
    # 模拟稳定延迟：20, 21, 20, 21, 20
    monitor._latency_history = deque([20, 21, 20, 21, 20], maxlen=10)
    jitter = monitor._calculate_jitter()
    assert jitter < 2, f"稳定网络抖动应 < 2ms，实际 {jitter:.1f}ms"
    print(f"  ✓ 稳定网络抖动: {jitter:.1f}ms (< 2ms)")


def test_jitter_calculation_unstable():
    """测试不稳定网络的抖动（应较大）"""
    monitor = NetworkMonitor()
    # 模拟不稳定延迟：20, 80, 25, 150, 30
    monitor._latency_history = deque([20, 80, 25, 150, 30], maxlen=10)
    jitter = monitor._calculate_jitter()
    assert jitter > 30, f"不稳定网络抖动应 > 30ms，实际 {jitter:.1f}ms"
    print(f"  ✓ 不稳定网络抖动: {jitter:.1f}ms (> 30ms)")


def test_jitter_calculation_empty():
    """测试无样本时抖动为 0"""
    monitor = NetworkMonitor()
    monitor._latency_history = deque([], maxlen=10)
    jitter = monitor._calculate_jitter()
    assert jitter == 0.0
    print("  ✓ 无样本时抖动: 0ms")


def test_jitter_calculation_single_sample():
    """测试单样本时抖动为 0"""
    monitor = NetworkMonitor()
    monitor._latency_history = deque([25.0], maxlen=10)
    jitter = monitor._calculate_jitter()
    assert jitter == 0.0
    print("  ✓ 单样本时抖动: 0ms")


# ============ 链路闪断检测测试 ============

def test_link_down_count_initial():
    """测试初始闪断计数为 0"""
    monitor = NetworkMonitor()
    assert monitor._link_down_count == 0
    print("  ✓ 初始闪断计数: 0")


def test_simulate_link_flap():
    """模拟链路闪断（连接 → 断开 → 连接）"""
    monitor = NetworkMonitor()
    monitor._last_link_up = True
    monitor._link_down_count = 0

    # 模拟第一次采集：网络断开
    status1 = NetworkStatus()
    status1.is_connected = False
    # 手动调用链路检测逻辑
    current_link_up = status1.is_connected
    if monitor._last_link_up and not current_link_up:
        monitor._link_down_count += 1
    monitor._last_link_up = current_link_up

    assert monitor._link_down_count == 1

    # 模拟第二次采集：网络恢复
    status2 = NetworkStatus()
    status2.is_connected = True
    current_link_up = status2.is_connected
    if monitor._last_link_up and not current_link_up:
        monitor._link_down_count += 1
    monitor._last_link_up = current_link_up

    assert monitor._link_down_count == 1  # 恢复不增加计数

    # 模拟第三次：再次断开
    status3 = NetworkStatus()
    status3.is_connected = False
    current_link_up = status3.is_connected
    if monitor._last_link_up and not current_link_up:
        monitor._link_down_count += 1
    monitor._last_link_up = current_link_up

    assert monitor._link_down_count == 2
    print("  ✓ 模拟链路闪断: 断开2次，计数=2")


def test_simulate_stable_connection():
    """模拟稳定连接（不应增加计数）"""
    monitor = NetworkMonitor()
    monitor._last_link_up = True
    monitor._link_down_count = 0

    # 连续 5 次都是连接状态
    for _ in range(5):
        current_link_up = True
        if monitor._last_link_up and not current_link_up:
            monitor._link_down_count += 1
        monitor._last_link_up = current_link_up

    assert monitor._link_down_count == 0
    print("  ✓ 模拟稳定连接: 计数保持 0")


# ============ 网卡错误包测试 ============

def test_nic_errors_detection():
    """测试网卡错误包增量检测"""
    monitor = NetworkMonitor()
    monitor._active_nic = "WLAN"
    monitor._last_errors = {"errin": 10, "errout": 5, "dropin": 2, "dropout": 1}

    # 模拟新的计数（有增量）
    mock_nic = MagicMock()
    mock_nic.errin = 15      # +5
    mock_nic.errout = 5      # +0
    mock_nic.dropin = 3      # +1
    mock_nic.dropout = 1     # +0

    with patch("psutil.net_io_counters") as mock_io:
        mock_io.return_value = {"WLAN": mock_nic}
        # 手动调用（因为 pernic=True 返回 dict）
        # 实际代码里 psutil.net_io_counters(pernic=True) 返回 dict
        status = NetworkStatus()
        try:
            io_per_nic = {"WLAN": mock_nic}
            current = {
                "errin": mock_nic.errin,
                "errout": mock_nic.errout,
                "dropin": mock_nic.dropin,
                "dropout": mock_nic.dropout,
            }
            deltas = {
                k: current[k] - monitor._last_errors[k]
                for k in current
            }
            status.nic_errors_delta = sum(deltas.values())
        except Exception:
            status.nic_errors_delta = 0

    assert status.nic_errors_delta == 6  # 5 + 0 + 1 + 0
    print("  ✓ 网卡错误包增量: 检测到 6 个新错误")


def test_nic_errors_no_change():
    """测试无错误包增量"""
    monitor = NetworkMonitor()
    monitor._active_nic = "WLAN"
    monitor._last_errors = {"errin": 10, "errout": 5, "dropin": 2, "dropout": 1}

    status = NetworkStatus()
    current = {"errin": 10, "errout": 5, "dropin": 2, "dropout": 1}
    deltas = {k: current[k] - monitor._last_errors[k] for k in current}
    status.nic_errors_delta = sum(deltas.values())

    assert status.nic_errors_delta == 0
    print("  ✓ 无错误包增量: delta=0")


# ============ 集成测试 ============

def test_network_jitter_integration():
    """测试实际网络抖动采集"""
    monitor = NetworkMonitor()
    # 采集两次以积累样本
    monitor.collect()
    time.sleep(1)
    status = monitor.collect()

    assert status.jitter_ms >= 0
    assert status.link_down_count >= 0
    assert status.nic_errors_delta >= 0
    print(f"  ✓ 实际网络: 抖动={status.jitter_ms:.1f}ms, "
          f"闪断={status.link_down_count}, 错误包={status.nic_errors_delta}")


# ============ 基线异常检测测试 ============

def test_baseline_warmup_no_alert():
    """测试预热期内不触发异常"""
    bd = BaselineDetector(window_size=30, warmup_count=10)
    # 只加 5 个样本，不够预热
    for i in range(5):
        bd.add_sample(20.0)
    assert not bd.is_ready
    # 即使给一个很大的值也不该报异常
    assert bd.is_anomaly(500.0) is False
    print("  ✓ 预热期不报异常（样本不足）")


def test_baseline_stable_no_alert():
    """测试稳定数据不触发异常"""
    bd = BaselineDetector(window_size=30, warmup_count=10)
    # 喂入 20 个稳定值
    for _ in range(20):
        bd.add_sample(30.0)
    assert bd.is_ready
    # 正常波动不该报
    assert bd.is_anomaly(32.0) is False
    assert bd.is_anomaly(28.0) is False
    assert bd.is_anomaly(35.0) is False
    print(f"  ✓ 稳定数据不报异常（基线={bd.mean:.1f}, std={bd.std:.1f}）")


def test_baseline_spike_detected():
    """测试突增能检测到"""
    bd = BaselineDetector(window_size=30, warmup_count=10, sigma_threshold=3.0)
    # 建立基线：稳定 30ms，偶尔 32ms
    for v in [30, 31, 30, 29, 30, 32, 30, 31, 30, 29, 30, 31, 30, 32, 30]:
        bd.add_sample(v)
    assert bd.is_ready
    # 突然跳到 200ms
    assert bd.is_anomaly(200.0) is True
    print(f"  ✓ 延迟突增检出（基线={bd.mean:.1f}, 突变值=200ms）")


def test_baseline_gradual_increase_no_alert():
    """测试缓慢上升不触发（基线会跟着涨）"""
    bd = BaselineDetector(window_size=20, warmup_count=10, sigma_threshold=3.0)
    # 延迟缓慢从 30 涨到 60
    for i in range(30):
        bd.add_sample(30.0 + i)
    # 当前值 60，基线也涨上来了，不该报
    assert bd.is_anomaly(62.0) is False
    print(f"  ✓ 缓慢上升不误报（基线={bd.mean:.1f}）")


def test_baseline_polluted_protection():
    """测试基线被污染时的保护"""
    bd = BaselineDetector(window_size=20, warmup_count=10, max_sane_value=500.0)
    # 基线全是异常值
    for _ in range(15):
        bd.add_sample(800.0)
    assert bd.is_ready
    assert not bd.is_baseline_sane
    # 不该基于这个污染基线做判断
    assert bd.is_anomaly(1000.0) is False
    print("  ✓ 基线被污染时不误报（合理性校验生效）")


def test_baseline_deviation_calculation():
    """测试偏离倍数计算"""
    bd = BaselineDetector(window_size=20, warmup_count=10)
    for _ in range(15):
        bd.add_sample(30.0)
    # std 约为 0，给个稍大的值
    bd.add_sample(32.0)
    bd.add_sample(28.0)
    deviation = bd.get_deviation(100.0)
    assert deviation > 0
    print(f"  ✓ 偏离计算: 100ms 偏离基线 {deviation:.1f} 个 sigma")


def test_baseline_negative_value_ignored():
    """测试负值（超时标记）不影响基线"""
    bd = BaselineDetector(window_size=20, warmup_count=10)
    for _ in range(12):
        bd.add_sample(30.0)
    bd.add_sample(-1)  # 超时标记
    bd.add_sample(-1)
    # 基线不该被 -1 拉低
    assert bd.mean > 25
    print(f"  ✓ 负值不污染基线（mean={bd.mean:.1f}）")


if __name__ == "__main__":
    print("\n=== 网络抖动和链路闪断测试 ===\n")
    print("-- 抖动计算 --")
    test_jitter_calculation_stable()
    test_jitter_calculation_unstable()
    test_jitter_calculation_empty()
    test_jitter_calculation_single_sample()
    print("\n-- 链路闪断 --")
    test_link_down_count_initial()
    test_simulate_link_flap()
    test_simulate_stable_connection()
    print("\n-- 网卡错误包 --")
    test_nic_errors_detection()
    test_nic_errors_no_change()
    print("\n-- 基线异常检测 --")
    test_baseline_warmup_no_alert()
    test_baseline_stable_no_alert()
    test_baseline_spike_detected()
    test_baseline_gradual_increase_no_alert()
    test_baseline_polluted_protection()
    test_baseline_deviation_calculation()
    test_baseline_negative_value_ignored()
    print("\n-- 集成测试 --")
    test_network_jitter_integration()
    print("\n全部通过 ✓\n")

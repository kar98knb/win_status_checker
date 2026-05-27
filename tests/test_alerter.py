"""
报警模块测试
覆盖：冷却机制、报警触发逻辑、阈值判断
"""

import sys
import os
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.alerts.alerter import Alerter


# ============ 冷却机制测试 ============

def test_cooldown_first_alert():
    """测试首次报警正常触发"""
    alerter = Alerter(cooldown_seconds=60)

    # mock 掉通知发送，只测逻辑
    with patch.object(alerter, '_send_notification'):
        alerter.alert("test_type", "标题", "内容", "warning")

    assert "test_type" in alerter._last_alert_time
    print("  ✓ 首次报警: 正常触发")


def test_cooldown_blocks_repeat():
    """测试冷却期内重复报警被阻止"""
    alerter = Alerter(cooldown_seconds=60)
    call_count = 0

    original_send = alerter._send_notification

    def counting_send(*args):
        nonlocal call_count
        call_count += 1

    with patch.object(alerter, '_send_notification', counting_send):
        alerter.alert("test_type", "标题", "内容1", "warning")
        alerter.alert("test_type", "标题", "内容2", "warning")  # 应被冷却
        alerter.alert("test_type", "标题", "内容3", "warning")  # 应被冷却

    assert call_count == 1, f"冷却期内应只触发 1 次，实际 {call_count} 次"
    print("  ✓ 冷却机制: 60s 内重复报警被阻止")


def test_cooldown_different_types():
    """测试不同类型报警互不影响"""
    alerter = Alerter(cooldown_seconds=60)
    call_count = 0

    def counting_send(*args):
        nonlocal call_count
        call_count += 1

    with patch.object(alerter, '_send_notification', counting_send):
        alerter.alert("type_a", "标题A", "内容", "warning")
        alerter.alert("type_b", "标题B", "内容", "warning")
        alerter.alert("type_c", "标题C", "内容", "critical")

    assert call_count == 3, f"不同类型应各触发 1 次，实际 {call_count} 次"
    print("  ✓ 不同类型报警: 互不影响冷却")


def test_cooldown_expires():
    """测试冷却过期后可再次触发"""
    alerter = Alerter(cooldown_seconds=1)  # 1 秒冷却
    call_count = 0

    def counting_send(*args):
        nonlocal call_count
        call_count += 1

    with patch.object(alerter, '_send_notification', counting_send):
        alerter.alert("test_type", "标题", "内容1", "warning")
        time.sleep(1.1)  # 等冷却过期
        alerter.alert("test_type", "标题", "内容2", "warning")

    assert call_count == 2, f"冷却过期后应再次触发，实际 {call_count} 次"
    print("  ✓ 冷却过期: 可再次触发")


# ============ check_and_alert 阈值测试 ============

def test_alert_network_down():
    """测试网络断开报警"""
    alerter = Alerter(cooldown_seconds=0)
    triggered = []

    def mock_alert(alert_type, title, msg, level):
        triggered.append(alert_type)

    alerter.alert = mock_alert

    net = MagicMock()
    net.is_connected = False
    net.packet_loss_percent = 0
    net.latency_ms = 0

    alerter.check_and_alert(net, None, None, {"packet_loss_percent": 5, "latency_ms": 100})
    assert "network_down" in triggered
    print("  ✓ 网络断开: 触发 network_down 报警")


def test_alert_packet_loss():
    """测试丢包报警"""
    alerter = Alerter(cooldown_seconds=0)
    triggered = []

    def mock_alert(alert_type, title, msg, level):
        triggered.append(alert_type)

    alerter.alert = mock_alert

    net = MagicMock()
    net.is_connected = True
    net.packet_loss_percent = 10
    net.latency_ms = 30

    alerter.check_and_alert(net, None, None, {"packet_loss_percent": 5, "latency_ms": 100})
    assert "packet_loss" in triggered
    print("  ✓ 丢包 10%: 触发 packet_loss 报警")


def test_alert_high_latency():
    """测试高延迟报警"""
    alerter = Alerter(cooldown_seconds=0)
    triggered = []

    def mock_alert(alert_type, title, msg, level):
        triggered.append(alert_type)

    alerter.alert = mock_alert

    net = MagicMock()
    net.is_connected = True
    net.packet_loss_percent = 0
    net.latency_ms = 200

    alerter.check_and_alert(net, None, None, {"packet_loss_percent": 5, "latency_ms": 100})
    assert "high_latency" in triggered
    print("  ✓ 延迟 200ms: 触发 high_latency 报警")


def test_alert_gpu_temp():
    """测试 GPU 过热报警"""
    alerter = Alerter(cooldown_seconds=0)
    triggered = []

    def mock_alert(alert_type, title, msg, level):
        triggered.append(alert_type)

    alerter.alert = mock_alert

    gpu = MagicMock()
    gpu.is_available = True
    gpu.temperature_celsius = 92
    gpu.memory_percent = 50
    gpu.gpu_usage_percent = 80

    alerter.check_and_alert(None, gpu, None, {"gpu_temp_celsius": 85, "gpu_memory_percent": 95, "gpu_usage_percent": 98})
    assert "gpu_temp" in triggered
    print("  ✓ GPU 92°C: 触发 gpu_temp 报警")


def test_alert_gpu_memory():
    """测试显存不足报警"""
    alerter = Alerter(cooldown_seconds=0)
    triggered = []

    def mock_alert(alert_type, title, msg, level):
        triggered.append(alert_type)

    alerter.alert = mock_alert

    gpu = MagicMock()
    gpu.is_available = True
    gpu.temperature_celsius = 70
    gpu.memory_percent = 97
    gpu.gpu_usage_percent = 80

    alerter.check_and_alert(None, gpu, None, {"gpu_temp_celsius": 85, "gpu_memory_percent": 95, "gpu_usage_percent": 98})
    assert "gpu_memory" in triggered
    print("  ✓ 显存 97%: 触发 gpu_memory 报警")


def test_alert_driver_failure():
    """测试驱动异常报警"""
    alerter = Alerter(cooldown_seconds=0)
    triggered = []

    def mock_alert(alert_type, title, msg, level):
        triggered.append(alert_type)

    alerter.alert = mock_alert

    driver = MagicMock()
    driver.all_mice_ok = False
    driver.all_keyboards_ok = True
    driver.all_audio_ok = False
    driver.all_controllers_ok = True
    driver.all_bluetooth_ok = True

    alerter.check_and_alert(None, None, driver, {})
    assert "mouse_driver" in triggered
    assert "audio_driver" in triggered
    assert "keyboard_driver" not in triggered
    print("  ✓ 驱动异常: 精确触发对应设备报警")


def test_no_alert_when_normal():
    """测试正常状态不触发报警"""
    alerter = Alerter(cooldown_seconds=0)
    triggered = []

    def mock_alert(alert_type, title, msg, level):
        triggered.append(alert_type)

    alerter.alert = mock_alert

    net = MagicMock()
    net.is_connected = True
    net.packet_loss_percent = 0
    net.latency_ms = 20

    gpu = MagicMock()
    gpu.is_available = True
    gpu.temperature_celsius = 60
    gpu.memory_percent = 40
    gpu.gpu_usage_percent = 50

    driver = MagicMock()
    driver.all_mice_ok = True
    driver.all_keyboards_ok = True
    driver.all_audio_ok = True
    driver.all_controllers_ok = True
    driver.all_bluetooth_ok = True

    alerter.check_and_alert(net, gpu, driver, {
        "packet_loss_percent": 5, "latency_ms": 100,
        "gpu_temp_celsius": 85, "gpu_memory_percent": 95, "gpu_usage_percent": 98,
    })
    assert len(triggered) == 0, f"正常状态不应触发报警，实际触发: {triggered}"
    print("  ✓ 正常状态: 无报警触发")


if __name__ == "__main__":
    print("\n=== 报警模块测试 ===\n")
    print("-- 冷却机制 --")
    test_cooldown_first_alert()
    test_cooldown_blocks_repeat()
    test_cooldown_different_types()
    test_cooldown_expires()
    print("\n-- 阈值触发 --")
    test_alert_network_down()
    test_alert_packet_loss()
    test_alert_high_latency()
    test_alert_gpu_temp()
    test_alert_gpu_memory()
    test_alert_driver_failure()
    test_no_alert_when_normal()
    print("\n全部通过 ✓\n")

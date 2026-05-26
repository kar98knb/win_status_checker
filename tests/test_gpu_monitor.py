"""
GPU 监控模块测试
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.monitors.gpu_monitor import GPUMonitor, GPUStatus


def test_gpu_status_dataclass():
    """测试 GPUStatus 数据结构"""
    status = GPUStatus()
    assert status.gpu_name == "未检测到"
    assert status.gpu_usage_percent == 0.0
    assert status.memory_total_mb == 0.0
    assert status.is_available is False
    assert status.driver_version == "未知"
    print("  ✓ GPUStatus 默认值正确")


def test_gpu_status_to_dict():
    """测试 to_dict 序列化"""
    status = GPUStatus(
        gpu_name="Test GPU",
        gpu_usage_percent=45.678,
        memory_total_mb=8192.0,
        memory_used_mb=4096.0,
        memory_percent=50.0,
        temperature_celsius=72.3,
        driver_version="31.0.101.5333",
        is_available=True,
    )
    d = status.to_dict()
    assert d["gpu_name"] == "Test GPU"
    assert d["gpu_usage_percent"] == 45.7
    assert d["memory_total_mb"] == 8192
    assert d["temperature_celsius"] == 72.3
    assert d["is_available"] is True
    assert "timestamp" in d
    print("  ✓ to_dict 序列化正确")


def test_gpu_safe_float():
    """测试安全浮点数转换"""
    assert GPUMonitor._safe_float("42.5") == 42.5
    assert GPUMonitor._safe_float("[N/A]") == 0.0
    assert GPUMonitor._safe_float("N/A") == 0.0
    assert GPUMonitor._safe_float("  100  ") == 100.0
    assert GPUMonitor._safe_float("abc") == 0.0
    assert GPUMonitor._safe_float("") == 0.0
    print("  ✓ _safe_float 边界情况处理正确")


def test_gpu_monitor_collect():
    """测试实际采集（集成测试）"""
    monitor = GPUMonitor()
    status = monitor.collect()

    assert isinstance(status, GPUStatus)
    assert status.timestamp > 0

    if status.is_available:
        assert status.gpu_name != "未检测到"
        assert status.driver_version != "未知"
        print(f"  ✓ GPU 采集成功: {status.gpu_name}")
        print(f"    使用率={status.gpu_usage_percent}%, 显存={status.memory_total_mb}MB")
        print(f"    温度={status.temperature_celsius}°C, 驱动={status.driver_version}")
    else:
        print("  ⚠ 未检测到 GPU（可能是虚拟机环境）")


def test_gpu_nvidia_smi_check():
    """测试 nvidia-smi 检测"""
    monitor = GPUMonitor()
    # 不管有没有 NVIDIA 卡，这个方法不应该抛异常
    result = monitor._nvidia_smi_available
    assert isinstance(result, bool)
    print(f"  ✓ nvidia-smi 可用: {result}")


if __name__ == "__main__":
    print("\n=== GPU 监控模块测试 ===\n")
    test_gpu_status_dataclass()
    test_gpu_status_to_dict()
    test_gpu_safe_float()
    test_gpu_monitor_collect()
    test_gpu_nvidia_smi_check()
    print("\n全部通过 ✓\n")

"""
系统资源监控模块测试
"""

import time
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.monitors.system_monitor import SystemMonitor, SystemStatus, ProcessInfo


# ============ 数据结构测试 ============

def test_system_status_dataclass():
    """测试 SystemStatus 默认值"""
    status = SystemStatus()
    assert status.cpu_usage_percent == 0.0
    assert status.cpu_freq_mhz == 0.0
    assert status.cpu_throttled is False
    assert status.memory_total_gb == 0.0
    assert status.memory_percent == 0.0
    assert status.disk_read_mb_per_sec == 0.0
    assert status.top_processes == []
    assert status.has_resource_hog is False
    print("  ✓ SystemStatus 默认值正确")


def test_system_status_to_dict():
    """测试 SystemStatus 序列化"""
    status = SystemStatus(
        cpu_usage_percent=45.6,
        cpu_freq_mhz=3200.0,
        cpu_freq_max_mhz=4500.0,
        memory_total_gb=16.0,
        memory_used_gb=10.5,
        memory_percent=65.6,
        memory_available_gb=5.5,
        disk_read_mb_per_sec=120.3,
        disk_write_mb_per_sec=50.7,
    )
    d = status.to_dict()
    assert d["cpu_usage_percent"] == 45.6
    assert d["cpu_freq_mhz"] == 3200
    assert d["memory_percent"] == 65.6
    assert d["disk_read_mb_per_sec"] == 120.3
    assert "timestamp" in d
    print("  ✓ SystemStatus.to_dict 序列化正确")


def test_process_info_to_dict():
    """测试 ProcessInfo 序列化"""
    p = ProcessInfo(name="game.exe", pid=1234, cpu_percent=85.3, memory_mb=2048.7)
    d = p.to_dict()
    assert d["name"] == "game.exe"
    assert d["pid"] == 1234
    assert d["cpu_percent"] == 85.3
    assert d["memory_mb"] == 2049
    print("  ✓ ProcessInfo.to_dict 正确")


# ============ 集成测试 ============

def test_system_monitor_collect():
    """测试实际采集"""
    monitor = SystemMonitor()
    time.sleep(0.5)  # 给 cpu_percent 一点时间差
    status = monitor.collect()

    assert isinstance(status, SystemStatus)
    assert status.cpu_usage_percent >= 0
    assert status.memory_total_gb > 0
    assert status.memory_percent > 0
    assert status.memory_available_gb > 0
    assert status.timestamp > 0

    print(f"  ✓ 系统资源采集成功:")
    print(f"    CPU: {status.cpu_usage_percent}%, "
          f"频率={status.cpu_freq_mhz:.0f}/{status.cpu_freq_max_mhz:.0f}MHz, "
          f"降频={status.cpu_throttled}")
    print(f"    内存: {status.memory_used_gb:.1f}/{status.memory_total_gb:.1f}GB "
          f"({status.memory_percent}%)")
    print(f"    磁盘: 读={status.disk_read_mb_per_sec:.1f}MB/s, "
          f"写={status.disk_write_mb_per_sec:.1f}MB/s")
    print(f"    高占用进程: {len(status.top_processes)} 个")


def test_system_monitor_cpu_freq():
    """测试 CPU 频率获取"""
    monitor = SystemMonitor()
    status = monitor.collect()

    # 应该能获取到频率（除非是虚拟机）
    assert status.cpu_freq_max_mhz > 0, "应能获取 CPU 最大频率"
    assert status.cpu_freq_mhz > 0, "应能获取 CPU 当前频率"
    print(f"  ✓ CPU 频率: {status.cpu_freq_mhz:.0f}MHz / 最大 {status.cpu_freq_max_mhz:.0f}MHz")


def test_system_monitor_memory():
    """测试内存采集"""
    monitor = SystemMonitor()
    status = monitor.collect()

    assert status.memory_total_gb >= 1, "总内存应至少 1GB"
    assert status.memory_used_gb > 0
    assert status.memory_available_gb > 0
    assert 0 < status.memory_percent < 100
    # 已用 + 可用 应该接近总量
    assert abs((status.memory_used_gb + status.memory_available_gb) - status.memory_total_gb) < 2
    print(f"  ✓ 内存: {status.memory_available_gb:.1f}GB 可用")


def test_system_monitor_disk_io():
    """测试磁盘 I/O 采集"""
    monitor = SystemMonitor()
    monitor.collect()  # 第一次建立基线
    time.sleep(1)
    status = monitor.collect()  # 第二次有时间差

    # 速率应该是非负数
    assert status.disk_read_mb_per_sec >= 0
    assert status.disk_write_mb_per_sec >= 0
    print(f"  ✓ 磁盘 I/O: 读={status.disk_read_mb_per_sec:.1f}MB/s, "
          f"写={status.disk_write_mb_per_sec:.1f}MB/s")


# ============ 模拟测试 ============

def test_simulate_cpu_throttle():
    """模拟 CPU 降频"""
    monitor = SystemMonitor()
    status = SystemStatus()

    # mock cpu_freq 返回降频状态
    with patch("psutil.cpu_percent", return_value=80.0):
        mock_freq = MagicMock()
        mock_freq.current = 1500.0  # 当前 1.5GHz
        mock_freq.max = 4500.0      # 最大 4.5GHz（低于 70% = 降频）
        with patch("psutil.cpu_freq", return_value=mock_freq):
            monitor._collect_cpu(status)

    assert status.cpu_throttled is True
    assert status.cpu_freq_mhz == 1500.0
    assert status.cpu_freq_max_mhz == 4500.0
    print("  ✓ 模拟 CPU 降频: 正确检测到 (1500/4500MHz)")


def test_simulate_no_throttle():
    """模拟 CPU 正常频率"""
    monitor = SystemMonitor()
    status = SystemStatus()

    with patch("psutil.cpu_percent", return_value=50.0):
        mock_freq = MagicMock()
        mock_freq.current = 4200.0
        mock_freq.max = 4500.0
        with patch("psutil.cpu_freq", return_value=mock_freq):
            monitor._collect_cpu(status)

    assert status.cpu_throttled is False
    print("  ✓ 模拟 CPU 正常: 未误报降频")


def test_simulate_resource_hog():
    """模拟后台进程抢资源"""
    monitor = SystemMonitor()
    status = SystemStatus()

    # 模拟进程列表
    mock_procs = []
    for name, cpu in [("msmpeng.exe", 25.0), ("game.exe", 60.0), ("chrome.exe", 5.0)]:
        proc = MagicMock()
        proc.info = {
            "pid": 1000,
            "name": name,
            "cpu_percent": cpu,
            "memory_info": MagicMock(rss=500 * 1024 * 1024),
        }
        mock_procs.append(proc)

    with patch("psutil.process_iter", return_value=mock_procs):
        monitor._collect_top_processes(status)

    assert status.has_resource_hog is True, "应检测到 msmpeng.exe 抢资源"
    assert len(status.top_processes) == 2  # 只有 cpu > 10% 的
    assert status.top_processes[0].name == "game.exe"  # 按 CPU 排序
    assert status.top_processes[1].name == "msmpeng.exe"
    print("  ✓ 模拟后台抢资源: 正确检测到 msmpeng.exe")


def test_simulate_no_resource_hog():
    """模拟无抢资源进程"""
    monitor = SystemMonitor()
    status = SystemStatus()

    mock_procs = []
    for name, cpu in [("game.exe", 60.0), ("discord.exe", 3.0)]:
        proc = MagicMock()
        proc.info = {
            "pid": 2000,
            "name": name,
            "cpu_percent": cpu,
            "memory_info": MagicMock(rss=200 * 1024 * 1024),
        }
        mock_procs.append(proc)

    with patch("psutil.process_iter", return_value=mock_procs):
        monitor._collect_top_processes(status)

    assert status.has_resource_hog is False
    print("  ✓ 模拟正常进程: 未误报抢资源")


if __name__ == "__main__":
    print("\n=== 系统资源监控模块测试 ===\n")
    print("-- 数据结构 --")
    test_system_status_dataclass()
    test_system_status_to_dict()
    test_process_info_to_dict()
    print("\n-- 集成测试（真实硬件） --")
    test_system_monitor_collect()
    test_system_monitor_cpu_freq()
    test_system_monitor_memory()
    test_system_monitor_disk_io()
    print("\n-- 模拟测试 --")
    test_simulate_cpu_throttle()
    test_simulate_no_throttle()
    test_simulate_resource_hog()
    test_simulate_no_resource_hog()
    print("\n全部通过 ✓\n")

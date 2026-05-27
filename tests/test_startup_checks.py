"""
启动检测模块测试
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.checks.startup_checks import (
    run_startup_checks,
    StartupCheckResult,
    _check_power_plan,
    _check_display_refresh,
    _check_pending_reboot,
    _check_total_memory,
)


# ============ 数据结构测试 ============

def test_startup_check_result_dataclass():
    """测试 StartupCheckResult 默认值"""
    result = StartupCheckResult()
    assert result.power_plan == "未知"
    assert result.power_plan_ok is False
    assert result.display_refresh_rate == 0
    assert result.display_refresh_ok is True
    assert result.pending_reboot is False
    assert result.total_memory_gb == 0.0
    assert result.memory_ok is True
    assert result.warnings == []
    print("  ✓ StartupCheckResult 默认值正确")


def test_startup_check_result_to_dict():
    """测试序列化"""
    result = StartupCheckResult(
        power_plan="高性能",
        power_plan_ok=True,
        display_refresh_rate=165,
        total_memory_gb=16.0,
        warnings=["测试警告"],
    )
    d = result.to_dict()
    assert d["power_plan"] == "高性能"
    assert d["power_plan_ok"] is True
    assert d["display_refresh_rate"] == 165
    assert d["total_memory_gb"] == 16.0
    assert len(d["warnings"]) == 1
    print("  ✓ StartupCheckResult.to_dict 正确")


# ============ 集成测试 ============

def test_run_startup_checks_integration():
    """测试实际启动检测"""
    result = run_startup_checks()

    assert isinstance(result, StartupCheckResult)
    assert result.power_plan != "未知"  # 应该能获取到电源计划
    assert result.total_memory_gb > 0   # 应该能获取到内存
    assert result.display_refresh_rate >= 0

    print(f"  ✓ 启动检测完成:")
    print(f"    电源计划: {result.power_plan} (OK={result.power_plan_ok})")
    print(f"    刷新率: {result.display_refresh_rate}Hz (OK={result.display_refresh_ok})")
    print(f"    待重启更新: {result.pending_reboot}")
    print(f"    总内存: {result.total_memory_gb:.1f}GB (OK={result.memory_ok})")
    if result.warnings:
        for w in result.warnings:
            print(f"    ⚠ {w}")


# ============ 模拟测试 ============

def test_simulate_high_performance_plan():
    """模拟高性能电源计划"""
    result = StartupCheckResult()

    mock_output = MagicMock()
    mock_output.returncode = 0
    mock_output.stdout = "电源方案 GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (高性能)\n"

    with patch("subprocess.run", return_value=mock_output):
        _check_power_plan(result)

    assert result.power_plan == "高性能"
    assert result.power_plan_ok is True
    assert len(result.warnings) == 0
    print("  ✓ 模拟高性能电源计划: 无警告")


def test_simulate_balanced_plan():
    """模拟平衡电源计划"""
    result = StartupCheckResult()

    mock_output = MagicMock()
    mock_output.returncode = 0
    mock_output.stdout = "电源方案 GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (平衡)\n"

    with patch("subprocess.run", return_value=mock_output):
        _check_power_plan(result)

    assert result.power_plan == "平衡"
    assert result.power_plan_ok is False
    assert len(result.warnings) == 1
    assert "高性能" in result.warnings[0]
    print("  ✓ 模拟平衡电源计划: 正确报警")


def test_simulate_low_refresh_rate():
    """模拟低刷新率"""
    result = StartupCheckResult()

    mock_output = MagicMock()
    mock_output.returncode = 0
    mock_output.stdout = "60\n"

    with patch("subprocess.run", return_value=mock_output):
        _check_display_refresh(result, min_hz=120)

    assert result.display_refresh_rate == 60
    assert result.display_refresh_ok is False
    assert len(result.warnings) == 1
    assert "60Hz" in result.warnings[0]
    print("  ✓ 模拟 60Hz 刷新率: 正确报警")


def test_simulate_high_refresh_rate():
    """模拟高刷新率"""
    result = StartupCheckResult()

    mock_output = MagicMock()
    mock_output.returncode = 0
    mock_output.stdout = "165\n"

    with patch("subprocess.run", return_value=mock_output):
        _check_display_refresh(result, min_hz=120)

    assert result.display_refresh_rate == 165
    assert result.display_refresh_ok is True
    assert len(result.warnings) == 0
    print("  ✓ 模拟 165Hz 刷新率: 无警告")


def test_simulate_pending_reboot():
    """模拟有待重启更新"""
    result = StartupCheckResult()

    mock_output = MagicMock()
    mock_output.returncode = 0
    mock_output.stdout = "True\n"

    with patch("subprocess.run", return_value=mock_output):
        _check_pending_reboot(result)

    assert result.pending_reboot is True
    assert len(result.warnings) == 1
    assert "重启" in result.warnings[0]
    print("  ✓ 模拟待重启更新: 正确报警")


def test_simulate_no_pending_reboot():
    """模拟无待重启更新"""
    result = StartupCheckResult()

    mock_output = MagicMock()
    mock_output.returncode = 0
    mock_output.stdout = "False\n"

    with patch("subprocess.run", return_value=mock_output):
        _check_pending_reboot(result)

    assert result.pending_reboot is False
    assert len(result.warnings) == 0
    print("  ✓ 模拟无待重启更新: 无警告")


def test_simulate_low_memory():
    """模拟低内存"""
    result = StartupCheckResult()

    mock_mem = MagicMock()
    mock_mem.total = 4 * 1024 ** 3  # 4GB

    with patch("psutil.virtual_memory", return_value=mock_mem):
        _check_total_memory(result, min_gb=8.0)

    assert result.total_memory_gb < 5
    assert result.memory_ok is False
    assert len(result.warnings) == 1
    print("  ✓ 模拟 4GB 内存: 正确报警")


def test_simulate_enough_memory():
    """模拟充足内存"""
    result = StartupCheckResult()

    mock_mem = MagicMock()
    mock_mem.total = 32 * 1024 ** 3  # 32GB

    with patch("psutil.virtual_memory", return_value=mock_mem):
        _check_total_memory(result, min_gb=8.0)

    assert result.total_memory_gb > 30
    assert result.memory_ok is True
    assert len(result.warnings) == 0
    print("  ✓ 模拟 32GB 内存: 无警告")


if __name__ == "__main__":
    print("\n=== 启动检测模块测试 ===\n")
    print("-- 数据结构 --")
    test_startup_check_result_dataclass()
    test_startup_check_result_to_dict()
    print("\n-- 集成测试（真实环境） --")
    test_run_startup_checks_integration()
    print("\n-- 模拟测试 --")
    test_simulate_high_performance_plan()
    test_simulate_balanced_plan()
    test_simulate_low_refresh_rate()
    test_simulate_high_refresh_rate()
    test_simulate_pending_reboot()
    test_simulate_no_pending_reboot()
    test_simulate_low_memory()
    test_simulate_enough_memory()
    print("\n全部通过 ✓\n")

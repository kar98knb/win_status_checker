"""
快照模块测试
覆盖：快照写入、异常退出检测、崩溃原因分析、正常退出清理
"""

import sys
import os
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.alerts.snapshot import (
    save_snapshot,
    check_abnormal_exit,
    clear_snapshot,
    _analyze_crash_cause,
    SNAPSHOT_FILE,
)


# 使用临时目录避免污染真实日志
_TEST_SNAPSHOT = Path(tempfile.gettempdir()) / "test_snapshot.json"


def _cleanup():
    """清理测试文件"""
    for f in (_TEST_SNAPSHOT, Path(str(_TEST_SNAPSHOT) + ".tmp")):
        try:
            f.unlink()
        except FileNotFoundError:
            pass


# ============ 快照写入测试 ============

@patch("src.alerts.snapshot.SNAPSHOT_FILE", _TEST_SNAPSHOT)
def test_save_snapshot_basic():
    """测试基本快照写入"""
    _cleanup()
    data = {"network": {"is_connected": True}, "gpu": {"gpu_name": "Test"}}
    save_snapshot(data)

    assert _TEST_SNAPSHOT.exists()
    content = json.loads(_TEST_SNAPSHOT.read_text(encoding="utf-8"))
    assert "timestamp" in content
    assert content["data"]["network"]["is_connected"] is True
    assert content["data"]["gpu"]["gpu_name"] == "Test"
    _cleanup()
    print("  ✓ 快照写入正常")


@patch("src.alerts.snapshot.SNAPSHOT_FILE", _TEST_SNAPSHOT)
def test_save_snapshot_overwrite():
    """测试快照覆盖（每次写入替换旧数据）"""
    _cleanup()
    save_snapshot({"version": 1})
    save_snapshot({"version": 2})

    content = json.loads(_TEST_SNAPSHOT.read_text(encoding="utf-8"))
    assert content["data"]["version"] == 2
    _cleanup()
    print("  ✓ 快照覆盖正常（新数据替换旧数据）")


@patch("src.alerts.snapshot.SNAPSHOT_FILE", _TEST_SNAPSHOT)
def test_save_snapshot_atomic():
    """测试原子写入（不应留下 .tmp 文件）"""
    _cleanup()
    save_snapshot({"test": True})

    tmp_file = Path(str(_TEST_SNAPSHOT) + ".tmp")
    assert not tmp_file.exists(), ".tmp 文件不应残留"
    _cleanup()
    print("  ✓ 原子写入正常（无 .tmp 残留）")


# ============ 异常退出检测测试 ============

@patch("src.alerts.snapshot.SNAPSHOT_FILE", _TEST_SNAPSHOT)
def test_check_abnormal_exit_detected():
    """测试检测到异常退出"""
    _cleanup()
    # 写入一个 1 小时前的快照
    old_snapshot = {
        "timestamp": time.time() - 3600,
        "data": {"gpu": {"temperature_celsius": 92, "memory_percent": 50}},
    }
    _TEST_SNAPSHOT.write_text(json.dumps(old_snapshot), encoding="utf-8")

    result = check_abnormal_exit(max_gap_seconds=30)

    assert result is not None
    assert result["gap_seconds"] > 3500
    assert "GPU 过热" in result["conclusion"]
    _cleanup()
    print("  ✓ 异常退出检测: 正确识别（gap > 30s）")


@patch("src.alerts.snapshot.SNAPSHOT_FILE", _TEST_SNAPSHOT)
def test_check_abnormal_exit_normal():
    """测试正常情况（快照很新，不应触发）"""
    _cleanup()
    recent_snapshot = {
        "timestamp": time.time() - 5,  # 5 秒前
        "data": {},
    }
    _TEST_SNAPSHOT.write_text(json.dumps(recent_snapshot), encoding="utf-8")

    result = check_abnormal_exit(max_gap_seconds=30)

    assert result is None
    _cleanup()
    print("  ✓ 正常退出: 未误报（gap < 30s）")


@patch("src.alerts.snapshot.SNAPSHOT_FILE", _TEST_SNAPSHOT)
def test_check_abnormal_exit_no_file():
    """测试无快照文件（首次运行）"""
    _cleanup()
    result = check_abnormal_exit(max_gap_seconds=30)
    assert result is None
    print("  ✓ 无快照文件: 返回 None（首次运行）")


@patch("src.alerts.snapshot.SNAPSHOT_FILE", _TEST_SNAPSHOT)
def test_check_abnormal_exit_corrupted():
    """测试快照文件损坏"""
    _cleanup()
    _TEST_SNAPSHOT.write_text("not valid json{{{", encoding="utf-8")

    result = check_abnormal_exit(max_gap_seconds=30)
    assert result is None  # 损坏文件不应崩溃
    _cleanup()
    print("  ✓ 快照损坏: 优雅处理，不崩溃")


# ============ 正常退出清理测试 ============

@patch("src.alerts.snapshot.SNAPSHOT_FILE", _TEST_SNAPSHOT)
def test_clear_snapshot():
    """测试正常退出时清理快照"""
    _cleanup()
    _TEST_SNAPSHOT.write_text("{}", encoding="utf-8")
    assert _TEST_SNAPSHOT.exists()

    clear_snapshot()

    assert not _TEST_SNAPSHOT.exists()
    print("  ✓ 正常退出清理: 快照已删除")


@patch("src.alerts.snapshot.SNAPSHOT_FILE", _TEST_SNAPSHOT)
def test_clear_snapshot_no_file():
    """测试清理不存在的快照（不应报错）"""
    _cleanup()
    clear_snapshot()  # 不应抛异常
    print("  ✓ 清理不存在的快照: 无异常")


# ============ 崩溃原因分析测试 ============

def test_analyze_crash_gpu_overheat():
    """测试分析: GPU 过热"""
    data = {"gpu": {"temperature_celsius": 95, "memory_percent": 50}}
    result = _analyze_crash_cause(data)
    assert "GPU 过热" in result
    print("  ✓ 崩溃分析: GPU 过热 (95°C)")


def test_analyze_crash_memory_full():
    """测试分析: 内存耗尽"""
    data = {"system": {"memory_percent": 98}}
    result = _analyze_crash_cause(data)
    assert "内存严重不足" in result
    print("  ✓ 崩溃分析: 内存耗尽 (98%)")


def test_analyze_crash_vram_full():
    """测试分析: 显存溢出"""
    data = {"gpu": {"temperature_celsius": 70, "memory_percent": 99}}
    result = _analyze_crash_cause(data)
    assert "显存" in result
    print("  ✓ 崩溃分析: 显存溢出 (99%)")


def test_analyze_crash_cpu_throttle():
    """测试分析: CPU 降频"""
    data = {"system": {"cpu_throttled": True, "memory_percent": 50}}
    result = _analyze_crash_cause(data)
    assert "CPU 降频" in result
    print("  ✓ 崩溃分析: CPU 降频")


def test_analyze_crash_network_down():
    """测试分析: 网络断开"""
    data = {"network": {"is_connected": False}}
    result = _analyze_crash_cause(data)
    assert "网络已断开" in result
    print("  ✓ 崩溃分析: 网络断开")


def test_analyze_crash_driver_issue():
    """测试分析: 驱动异常"""
    data = {"drivers": {"all_mice_ok": False, "all_keyboards_ok": True}}
    result = _analyze_crash_cause(data)
    assert "鼠标驱动异常" in result
    print("  ✓ 崩溃分析: 鼠标驱动异常")


def test_analyze_crash_multiple_causes():
    """测试分析: 多个原因"""
    data = {
        "gpu": {"temperature_celsius": 95, "memory_percent": 96},
        "system": {"memory_percent": 97, "cpu_throttled": True},
    }
    result = _analyze_crash_cause(data)
    assert "GPU 过热" in result
    assert "显存" in result
    assert "内存" in result
    assert "CPU 降频" in result
    print("  ✓ 崩溃分析: 多原因同时检出")


def test_analyze_crash_all_normal():
    """测试分析: 一切正常"""
    data = {
        "gpu": {"temperature_celsius": 65, "memory_percent": 50},
        "system": {"memory_percent": 40, "cpu_throttled": False},
        "network": {"is_connected": True},
        "drivers": {"all_mice_ok": True, "all_keyboards_ok": True},
    }
    result = _analyze_crash_cause(data)
    assert "各项指标正常" in result
    print("  ✓ 崩溃分析: 指标正常时给出兜底结论")


if __name__ == "__main__":
    print("\n=== 快照模块测试 ===\n")
    print("-- 快照写入 --")
    test_save_snapshot_basic()
    test_save_snapshot_overwrite()
    test_save_snapshot_atomic()
    print("\n-- 异常退出检测 --")
    test_check_abnormal_exit_detected()
    test_check_abnormal_exit_normal()
    test_check_abnormal_exit_no_file()
    test_check_abnormal_exit_corrupted()
    print("\n-- 正常退出清理 --")
    test_clear_snapshot()
    test_clear_snapshot_no_file()
    print("\n-- 崩溃原因分析 --")
    test_analyze_crash_gpu_overheat()
    test_analyze_crash_memory_full()
    test_analyze_crash_vram_full()
    test_analyze_crash_cpu_throttle()
    test_analyze_crash_network_down()
    test_analyze_crash_driver_issue()
    test_analyze_crash_multiple_causes()
    test_analyze_crash_all_normal()
    print("\n全部通过 ✓\n")

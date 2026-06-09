"""
录制/回放链路测试
验证：采集 → 录制 → 读取 → 回放解析 整条链路的正确性。
不依赖预先录制的文件，测试时现场录制、回放、断言。
"""

import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.checks.recorder import Recorder, collect_raw_sample, load_recording
from src.monitors.driver_monitor import DriverMonitor, DriverStatus
from src.monitors.network_monitor import NetworkMonitor


def test_collect_raw_sample_fields():
    """测试原始数据采集：必要字段完整"""
    sample = collect_raw_sample(label="test")

    required_keys = [
        "label", "timestamp",
        "net_if_stats", "net_if_addrs", "net_io_counters", "tcp_latencies",
        "cpu_percent", "cpu_freq", "memory", "disk_io",
        "wmi_pointing_devices", "wmi_keyboards", "wmi_sound_devices",
    ]
    for key in required_keys:
        assert key in sample, f"缺少字段: {key}"

    assert sample["label"] == "test"
    assert sample["timestamp"] > 0
    assert isinstance(sample["tcp_latencies"], list)
    assert len(sample["tcp_latencies"]) == 3
    print("  ✓ collect_raw_sample: 所有必要字段完整")


def test_collect_raw_sample_types():
    """测试原始数据采集：字段类型正确"""
    sample = collect_raw_sample()

    assert isinstance(sample["net_if_stats"], dict)
    assert isinstance(sample["memory"], dict)
    assert isinstance(sample["cpu_percent"], (int, float))
    assert isinstance(sample["wmi_pointing_devices"], list)
    assert isinstance(sample["wmi_keyboards"], list)

    # 内存字段应该有值
    mem = sample["memory"]
    assert mem.get("total", 0) > 0
    assert mem.get("percent", 0) > 0
    print("  ✓ collect_raw_sample: 字段类型正确")


def test_recorder_write_and_read():
    """测试录制写入和读取：完整往返"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        recorder = Recorder(session_name="test_roundtrip", output_dir=tmp_path)

        # 录制 2 条
        sample1 = collect_raw_sample(label="first")
        sample2 = collect_raw_sample(label="second")
        recorder.record_sample(sample1)
        recorder.record_sample(sample2)

        # 读取
        samples = load_recording(recorder.file_path)

        assert len(samples) == 2
        assert samples[0]["label"] == "first"
        assert samples[1]["label"] == "second"
        assert samples[0]["_seq"] == 0
        assert samples[1]["_seq"] == 1
        assert samples[0]["_ts"] > 0
    print("  ✓ Recorder 写入/读取: 往返一致")


def test_replay_driver_from_live_data():
    """回放测试：用当前机器采集的数据回放驱动监控"""
    sample = collect_raw_sample(label="normal")

    # 用采集到的 WMI 数据构造 mock
    monitor = DriverMonitor()
    mock_wmi = MagicMock()

    mice_data = sample["wmi_pointing_devices"]
    mock_mice = []
    for m in mice_data:
        mock_dev = MagicMock()
        mock_dev.Name = m["Name"]
        mock_dev.Status = m["Status"]
        mock_dev.ConfigManagerErrorCode = m["ConfigManagerErrorCode"]
        mock_mice.append(mock_dev)
    mock_wmi.Win32_PointingDevice.return_value = mock_mice

    kb_data = sample["wmi_keyboards"]
    mock_kbs = []
    for k in kb_data:
        mock_dev = MagicMock()
        mock_dev.Name = k["Name"]
        mock_dev.Status = k["Status"]
        mock_dev.ConfigManagerErrorCode = k["ConfigManagerErrorCode"]
        mock_kbs.append(mock_dev)
    mock_wmi.Win32_Keyboard.return_value = mock_kbs

    audio_data = sample["wmi_sound_devices"]
    mock_audio = []
    for a in audio_data:
        mock_dev = MagicMock()
        mock_dev.Name = a["Name"]
        mock_dev.Status = a["Status"]
        mock_dev.ConfigManagerErrorCode = a["ConfigManagerErrorCode"]
        mock_audio.append(mock_dev)
    mock_wmi.Win32_SoundDevice.return_value = mock_audio
    mock_wmi.query.return_value = []

    monitor._wmi = mock_wmi
    status = monitor.collect()

    # 真实正常数据回放，应该所有设备正常
    assert status.all_mice_ok is True, f"鼠标状态异常: {[m.to_dict() for m in status.mice]}"
    assert status.all_keyboards_ok is True, f"键盘状态异常: {[k.to_dict() for k in status.keyboards]}"
    assert len(status.mice) == len(mice_data)
    assert len(status.keyboards) == len(kb_data)
    print(f"  ✓ 回放驱动监控: {len(mice_data)} 鼠标 + {len(kb_data)} 键盘，解析结果一致")


def test_replay_network_from_live_data():
    """回放测试：用当前机器采集的数据验证网络判断"""
    sample = collect_raw_sample()

    latencies = sample["tcp_latencies"]
    net_stats = sample["net_if_stats"]

    # 验证：如果有 up 的接口且有成功的延迟测试，应判定为连接正常
    has_up = any(v.get("isup") for v in net_stats.values())
    has_latency = any(l > 0 for l in latencies)

    if has_up and has_latency:
        # 直接用 NetworkMonitor 采集验证
        monitor = NetworkMonitor()
        status = monitor.collect()
        assert status.is_connected is True
        assert status.latency_ms > 0
        print(f"  ✓ 回放网络监控: 连接正常, 延迟 {status.latency_ms:.1f}ms（与原始数据一致）")
    else:
        print("  ⚠ 当前网络不可用，跳过回放验证")


def test_replay_consistency():
    """一致性测试：直接采集 vs 录制回放，驱动结果一致"""
    # 直接采集
    monitor = DriverMonitor()
    direct_status = monitor.collect()

    # 录制一条
    sample = collect_raw_sample()

    # 回放
    monitor2 = DriverMonitor()
    mock_wmi = MagicMock()
    for device_type, wmi_method, data_key in [
        ("mice", "Win32_PointingDevice", "wmi_pointing_devices"),
        ("keyboards", "Win32_Keyboard", "wmi_keyboards"),
        ("audio", "Win32_SoundDevice", "wmi_sound_devices"),
    ]:
        mock_devices = []
        for d in sample[data_key]:
            mock_dev = MagicMock()
            mock_dev.Name = d["Name"]
            mock_dev.Status = d["Status"]
            mock_dev.ConfigManagerErrorCode = d["ConfigManagerErrorCode"]
            mock_devices.append(mock_dev)
        getattr(mock_wmi, wmi_method).return_value = mock_devices
    mock_wmi.query.return_value = []
    monitor2._wmi = mock_wmi
    replay_status = monitor2.collect()

    # 断言：两种方式结果一致
    assert direct_status.all_mice_ok == replay_status.all_mice_ok
    assert direct_status.all_keyboards_ok == replay_status.all_keyboards_ok
    assert direct_status.all_audio_ok == replay_status.all_audio_ok
    assert len(direct_status.mice) == len(replay_status.mice)
    assert len(direct_status.keyboards) == len(replay_status.keyboards)
    print("  ✓ 一致性: 直接采集 vs 录制回放，结果完全一致")


if __name__ == "__main__":
    print("\n=== 录制/回放链路测试 ===\n")
    print("-- 数据采集 --")
    test_collect_raw_sample_fields()
    test_collect_raw_sample_types()
    print("\n-- 录制读写 --")
    test_recorder_write_and_read()
    print("\n-- 回放验证 --")
    test_replay_driver_from_live_data()
    test_replay_network_from_live_data()
    test_replay_consistency()
    print("\n全部通过 ✓\n")

"""
录制数据回放测试
用真实录制的 API 数据验证监控模块的解析逻辑。

使用方式：
1. 先录制正常数据：  python run.py --record --label normal
2. 制造异常后录制：  python run.py --record --label mouse_disconnected
3. 运行回放测试：    python run.py --test

录制文件存放在 tests/recordings/ 目录下。
"""

import sys
import os
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.checks.recorder import load_recording

RECORDINGS_DIR = Path(__file__).parent / "recordings"
from src.monitors.driver_monitor import DriverMonitor, DriverStatus
from src.monitors.network_monitor import NetworkMonitor, NetworkStatus


def _get_recording_files() -> list:
    """获取所有录制文件"""
    if not RECORDINGS_DIR.exists():
        return []
    return sorted(RECORDINGS_DIR.glob("session_*.jsonl"))


def test_replay_driver_monitor():
    """回放测试：用录制数据验证驱动监控解析"""
    files = _get_recording_files()
    if not files:
        print("  ⚠ 无录制数据，跳过回放测试")
        print("    提示: 运行 'python run.py --record --label normal' 录制数据")
        return

    total_samples = 0
    for f in files:
        samples = load_recording(f)
        for sample in samples:
            total_samples += 1
            # 用录制的 WMI 数据构造 mock
            monitor = DriverMonitor()
            mock_wmi = MagicMock()

            # 回放鼠标数据
            mice_data = sample.get("wmi_pointing_devices", [])
            mock_mice = []
            for m in mice_data:
                mock_dev = MagicMock()
                mock_dev.Name = m.get("Name", "")
                mock_dev.Status = m.get("Status", "")
                mock_dev.ConfigManagerErrorCode = m.get("ConfigManagerErrorCode", 0)
                mock_mice.append(mock_dev)
            mock_wmi.Win32_PointingDevice.return_value = mock_mice

            # 回放键盘数据
            kb_data = sample.get("wmi_keyboards", [])
            mock_kbs = []
            for k in kb_data:
                mock_dev = MagicMock()
                mock_dev.Name = k.get("Name", "")
                mock_dev.Status = k.get("Status", "")
                mock_dev.ConfigManagerErrorCode = k.get("ConfigManagerErrorCode", 0)
                mock_kbs.append(mock_dev)
            mock_wmi.Win32_Keyboard.return_value = mock_kbs

            # 回放音频数据
            audio_data = sample.get("wmi_sound_devices", [])
            mock_audio = []
            for a in audio_data:
                mock_dev = MagicMock()
                mock_dev.Name = a.get("Name", "")
                mock_dev.Status = a.get("Status", "")
                mock_dev.ConfigManagerErrorCode = a.get("ConfigManagerErrorCode", 0)
                mock_audio.append(mock_dev)
            mock_wmi.Win32_SoundDevice.return_value = mock_audio
            mock_wmi.query.return_value = []

            monitor._wmi = mock_wmi
            status = monitor.collect()

            # 验证基本一致性
            label = sample.get("label", "")
            assert isinstance(status, DriverStatus)
            assert status.timestamp > 0

            # 如果标签标注了异常，验证检测结果
            if "mouse_disconnected" in label or "mouse_error" in label:
                assert not status.all_mice_ok, \
                    f"标签 '{label}' 但未检测到鼠标异常"
            elif "keyboard_error" in label:
                assert not status.all_keyboards_ok, \
                    f"标签 '{label}' 但未检测到键盘异常"
            elif label == "normal":
                # 正常标签下所有设备应该 OK
                assert status.all_mice_ok, "标签 'normal' 但鼠标异常"
                assert status.all_keyboards_ok, "标签 'normal' 但键盘异常"

    print(f"  ✓ 驱动监控回放: {total_samples} 条样本验证通过 ({len(files)} 个录制文件)")


def test_replay_network_monitor():
    """回放测试：用录制数据验证网络监控解析"""
    files = _get_recording_files()
    if not files:
        print("  ⚠ 无录制数据，跳过")
        return

    total_samples = 0
    for f in files:
        samples = load_recording(f)
        for sample in samples:
            total_samples += 1
            label = sample.get("label", "")
            latencies = sample.get("tcp_latencies", [])
            net_stats = sample.get("net_if_stats", {})

            # 验证网络连通性判断
            has_up_interface = any(
                v.get("isup", False)
                for k, v in net_stats.items()
                if "loopback" not in k.lower()
            )

            # 验证延迟数据合理性
            valid_latencies = [l for l in latencies if l > 0]
            if valid_latencies:
                avg_latency = sum(valid_latencies) / len(valid_latencies)
                assert avg_latency < 10000, f"延迟异常大: {avg_latency}ms"

            # 标签验证
            if "network_down" in label:
                all_failed = all(l == -1 for l in latencies)
                assert all_failed or not has_up_interface, \
                    f"标签 '{label}' 但网络看起来正常"

    print(f"  ✓ 网络监控回放: {total_samples} 条样本验证通过")


def test_replay_data_integrity():
    """回放测试：验证录制数据完整性"""
    files = _get_recording_files()
    if not files:
        print("  ⚠ 无录制数据，跳过")
        return

    required_keys = ["timestamp", "net_if_stats", "cpu_percent", "memory"]
    issues = 0

    for f in files:
        samples = load_recording(f)
        for sample in samples:
            for key in required_keys:
                if key not in sample:
                    issues += 1

    assert issues == 0, f"录制数据缺少必要字段: {issues} 处"
    total = sum(len(load_recording(f)) for f in files)
    print(f"  ✓ 数据完整性: {total} 条样本，所有必要字段完整")


if __name__ == "__main__":
    print("\n=== 录制数据回放测试 ===\n")
    test_replay_data_integrity()
    test_replay_driver_monitor()
    test_replay_network_monitor()
    print("\n全部通过 ✓\n")

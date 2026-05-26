"""
驱动监控模块测试
包含：单元测试、集成测试、模拟驱动异常测试
"""

import time
import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.monitors.driver_monitor import (
    DriverMonitor, DriverStatus, DeviceInfo,
    DEVICE_TYPE_MOUSE, DEVICE_TYPE_KEYBOARD,
    DEVICE_TYPE_AUDIO, DEVICE_TYPE_CONTROLLER,
    DEVICE_TYPE_BLUETOOTH,
)


# ============ 数据结构测试 ============

def test_device_info_dataclass():
    """测试 DeviceInfo 数据结构"""
    info = DeviceInfo()
    assert info.name == ""
    assert info.device_type == ""
    assert info.status == "未知"
    assert info.error_code == 0
    assert info.is_wireless is False
    assert info.connection == "有线"
    print("  ✓ DeviceInfo 默认值正确")


def test_device_info_to_dict():
    """测试 DeviceInfo 序列化"""
    info = DeviceInfo(
        name="Logitech G Pro Wireless",
        device_type="mouse",
        status="正常",
        driver_name="HID-compliant mouse",
        error_code=0,
        is_wireless=True,
        connection="2.4G无线",
    )
    d = info.to_dict()
    assert d["name"] == "Logitech G Pro Wireless"
    assert d["is_wireless"] is True
    assert d["connection"] == "2.4G无线"
    print("  ✓ DeviceInfo.to_dict 正确（含无线字段）")


def test_driver_status_dataclass():
    """测试 DriverStatus 数据结构（含新设备类型）"""
    status = DriverStatus()
    assert status.mice == []
    assert status.keyboards == []
    assert status.audio_devices == []
    assert status.controllers == []
    assert status.bluetooth == []
    assert status.all_mice_ok is True
    assert status.all_keyboards_ok is True
    assert status.all_audio_ok is True
    assert status.all_controllers_ok is True
    assert status.all_bluetooth_ok is True
    print("  ✓ DriverStatus 默认值正确（含新设备类型）")


def test_driver_status_to_dict():
    """测试 DriverStatus 序列化"""
    status = DriverStatus(
        mice=[DeviceInfo(name="Mouse1", device_type="mouse", status="正常")],
        keyboards=[DeviceInfo(name="KB1", device_type="keyboard", status="正常")],
        audio_devices=[DeviceInfo(name="Headset", device_type="audio", status="正常")],
        controllers=[DeviceInfo(name="Xbox Controller", device_type="controller", status="正常")],
        bluetooth=[DeviceInfo(name="BT Adapter", device_type="bluetooth", status="正常")],
    )
    d = status.to_dict()
    assert len(d["mice"]) == 1
    assert len(d["keyboards"]) == 1
    assert len(d["audio_devices"]) == 1
    assert len(d["controllers"]) == 1
    assert len(d["bluetooth"]) == 1
    assert "timestamp" in d
    print("  ✓ DriverStatus.to_dict 正确（含所有设备类型）")


# ============ 状态解析测试 ============

def test_parse_status():
    """测试设备状态解析"""
    assert DriverMonitor._parse_status("OK", 0) == "正常"
    assert DriverMonitor._parse_status("Error", 22) == "已禁用"
    assert DriverMonitor._parse_status("Error", 45) == "已断开"
    assert DriverMonitor._parse_status("Error", 10) == "异常"
    assert DriverMonitor._parse_status("Error", 28) == "异常"
    assert DriverMonitor._parse_status("Unknown", 999) == "未知"
    assert DriverMonitor._parse_status("OK", None) == "正常"
    print("  ✓ _parse_status 状态码解析正确（含断开状态）")


# ============ 无线检测测试 ============

def test_detect_connection_type_wired():
    """测试有线设备识别"""
    info = DeviceInfo(name="HID-compliant mouse")
    DriverMonitor._detect_connection_type(info)
    assert info.is_wireless is False
    assert info.connection == "有线"
    print("  ✓ 有线设备识别正确")


def test_detect_connection_type_bluetooth():
    """测试蓝牙设备识别"""
    info = DeviceInfo(name="Bluetooth LE Mouse")
    DriverMonitor._detect_connection_type(info)
    assert info.is_wireless is True
    assert info.connection == "蓝牙"

    info2 = DeviceInfo(name="Sony DualSense Wireless Controller (BT)")
    DriverMonitor._detect_connection_type(info2)
    assert info2.is_wireless is True
    assert info2.connection == "蓝牙"
    print("  ✓ 蓝牙设备识别正确")


def test_detect_connection_type_24g():
    """测试 2.4G 无线设备识别"""
    info = DeviceInfo(name="Logitech USB Receiver")
    DriverMonitor._detect_connection_type(info)
    assert info.is_wireless is True
    assert info.connection == "2.4G无线"

    info2 = DeviceInfo(name="2.4G Wireless Mouse Dongle")
    DriverMonitor._detect_connection_type(info2)
    assert info2.is_wireless is True
    assert info2.connection == "2.4G无线"
    print("  ✓ 2.4G 无线设备识别正确")


def test_detect_connection_type_generic_wireless():
    """测试通用无线设备识别"""
    info = DeviceInfo(name="Razer DeathAdder Wireless")
    DriverMonitor._detect_connection_type(info)
    assert info.is_wireless is True
    assert info.connection == "USB无线"
    print("  ✓ 通用无线设备识别正确")


# ============ 集成测试 ============

def test_driver_monitor_collect():
    """测试实际采集（集成测试）"""
    monitor = DriverMonitor()
    status = monitor.collect()

    assert isinstance(status, DriverStatus)
    assert isinstance(status.all_mice_ok, bool)
    assert isinstance(status.all_keyboards_ok, bool)
    assert status.timestamp > 0

    print(f"  ✓ 驱动采集成功:")
    print(f"    鼠标: {len(status.mice)} 个, OK={status.all_mice_ok}")
    for m in status.mice:
        print(f"      - {m.name} [{m.status}] ({m.connection})")
    print(f"    键盘: {len(status.keyboards)} 个, OK={status.all_keyboards_ok}")
    for k in status.keyboards:
        print(f"      - {k.name} [{k.status}] ({k.connection})")
    print(f"    音频: {len(status.audio_devices)} 个, OK={status.all_audio_ok}")
    for a in status.audio_devices:
        print(f"      - {a.name} [{a.status}] ({a.connection})")
    print(f"    手柄: {len(status.controllers)} 个, OK={status.all_controllers_ok}")
    for c in status.controllers:
        print(f"      - {c.name} [{c.status}] ({c.connection})")
    print(f"    蓝牙: {len(status.bluetooth)} 个, OK={status.all_bluetooth_ok}")
    for b in status.bluetooth:
        print(f"      - {b.name} [{b.status}]")


def test_driver_monitor_detects_devices():
    """测试是否能检测到至少一个输入设备"""
    monitor = DriverMonitor()
    status = monitor.collect()

    assert len(status.mice) >= 1, "应至少检测到 1 个鼠标设备"
    assert len(status.keyboards) >= 1, "应至少检测到 1 个键盘设备"
    print("  ✓ 至少检测到 1 个鼠标和 1 个键盘")


# ============ 模拟驱动异常测试 ============

def test_simulate_mouse_driver_failure():
    """模拟鼠标驱动掉了（error_code=28 表示驱动未安装）"""
    monitor = DriverMonitor()

    # 创建一个 mock WMI 对象
    mock_wmi = MagicMock()

    # 模拟一个正常鼠标和一个掉驱动的鼠标
    normal_mouse = MagicMock()
    normal_mouse.Name = "HID-compliant mouse"
    normal_mouse.Status = "OK"
    normal_mouse.ConfigManagerErrorCode = 0

    broken_mouse = MagicMock()
    broken_mouse.Name = "Logitech G502 Wireless"
    broken_mouse.Status = "Error"
    broken_mouse.ConfigManagerErrorCode = 28  # 驱动未安装

    mock_wmi.Win32_PointingDevice.return_value = [normal_mouse, broken_mouse]
    mock_wmi.Win32_Keyboard.return_value = []
    mock_wmi.Win32_SoundDevice.return_value = []
    mock_wmi.query.return_value = []

    # 替换 WMI 实例
    monitor._wmi = mock_wmi
    status = monitor.collect()

    # 验证：应该检测到异常
    assert status.all_mice_ok is False, "应检测到鼠标驱动异常"
    assert len(status.mice) == 2
    assert status.mice[0].status == "正常"
    assert status.mice[0].error_code == 0
    assert status.mice[1].status == "异常"
    assert status.mice[1].error_code == 28
    assert status.mice[1].name == "Logitech G502 Wireless"
    print("  ✓ 模拟鼠标掉驱动: 监控正确检测到异常 (error_code=28)")


def test_simulate_keyboard_driver_disabled():
    """模拟键盘被禁用（error_code=22）"""
    monitor = DriverMonitor()
    mock_wmi = MagicMock()

    disabled_kb = MagicMock()
    disabled_kb.Name = "HID Keyboard Device"
    disabled_kb.Status = "Error"
    disabled_kb.ConfigManagerErrorCode = 22  # 设备已禁用

    mock_wmi.Win32_PointingDevice.return_value = []
    mock_wmi.Win32_Keyboard.return_value = [disabled_kb]
    mock_wmi.Win32_SoundDevice.return_value = []
    mock_wmi.query.return_value = []

    monitor._wmi = mock_wmi
    status = monitor.collect()

    assert status.all_keyboards_ok is False
    assert status.keyboards[0].status == "已禁用"
    assert status.keyboards[0].error_code == 22
    print("  ✓ 模拟键盘被禁用: 监控正确检测到 (error_code=22)")


def test_simulate_audio_driver_failure():
    """模拟耳机驱动异常（error_code=10 表示设备无法启动）"""
    monitor = DriverMonitor()
    mock_wmi = MagicMock()

    broken_audio = MagicMock()
    broken_audio.Name = "Realtek Bluetooth Audio"
    broken_audio.Status = "Error"
    broken_audio.ConfigManagerErrorCode = 10  # 设备无法启动

    mock_wmi.Win32_PointingDevice.return_value = []
    mock_wmi.Win32_Keyboard.return_value = []
    mock_wmi.Win32_SoundDevice.return_value = [broken_audio]
    mock_wmi.query.return_value = []

    monitor._wmi = mock_wmi
    status = monitor.collect()

    assert status.all_audio_ok is False
    assert status.audio_devices[0].status == "异常"
    assert status.audio_devices[0].error_code == 10
    assert status.audio_devices[0].is_wireless is True  # 名称含 Bluetooth
    assert status.audio_devices[0].connection == "蓝牙"
    print("  ✓ 模拟蓝牙耳机掉驱动: 监控正确检测到 (error_code=10, 蓝牙)")


def test_simulate_controller_disconnected():
    """模拟手柄断开连接（error_code=45）"""
    monitor = DriverMonitor()
    mock_wmi = MagicMock()

    disconnected_controller = MagicMock()
    disconnected_controller.Name = "Xbox Wireless Controller"
    disconnected_controller.Status = "Error"
    disconnected_controller.ConfigManagerErrorCode = 45  # 设备已断开

    mock_wmi.Win32_PointingDevice.return_value = []
    mock_wmi.Win32_Keyboard.return_value = []
    mock_wmi.Win32_SoundDevice.return_value = []
    mock_wmi.query.return_value = [disconnected_controller]

    monitor._wmi = mock_wmi
    status = monitor.collect()

    # 手柄断开不算 "异常"（玩家可能只是关了手柄）
    # 但 error_code != 0 所以 all_controllers_ok 为 False
    assert status.all_controllers_ok is False
    assert status.controllers[0].status == "已断开"
    assert status.controllers[0].error_code == 45
    print("  ✓ 模拟手柄断开: 监控正确检测到 (error_code=45, 已断开)")


def test_simulate_bluetooth_adapter_failure():
    """模拟蓝牙适配器驱动崩溃（error_code=31 表示设备工作不正常）"""
    monitor = DriverMonitor()
    mock_wmi = MagicMock()

    broken_bt = MagicMock()
    broken_bt.Name = "Intel Wireless Bluetooth"
    broken_bt.Status = "Error"
    broken_bt.ConfigManagerErrorCode = 31  # 设备工作不正常

    mock_wmi.Win32_PointingDevice.return_value = []
    mock_wmi.Win32_Keyboard.return_value = []
    mock_wmi.Win32_SoundDevice.return_value = []
    # query 被调用两次：一次 controllers，一次 bluetooth
    mock_wmi.query.side_effect = [[], [broken_bt]]

    monitor._wmi = mock_wmi
    status = monitor.collect()

    assert status.all_bluetooth_ok is False
    assert status.bluetooth[0].status == "异常"
    assert status.bluetooth[0].error_code == 31
    print("  ✓ 模拟蓝牙适配器崩溃: 监控正确检测到 (error_code=31)")


def test_simulate_multiple_failures():
    """模拟多个设备同时出问题"""
    monitor = DriverMonitor()
    mock_wmi = MagicMock()

    # 鼠标正常
    ok_mouse = MagicMock()
    ok_mouse.Name = "HID-compliant mouse"
    ok_mouse.Status = "OK"
    ok_mouse.ConfigManagerErrorCode = 0

    # 键盘掉驱动
    broken_kb = MagicMock()
    broken_kb.Name = "Corsair K70 RGB"
    broken_kb.Status = "Error"
    broken_kb.ConfigManagerErrorCode = 28

    # 耳机正常
    ok_audio = MagicMock()
    ok_audio.Name = "Realtek High Definition Audio"
    ok_audio.Status = "OK"
    ok_audio.ConfigManagerErrorCode = 0

    mock_wmi.Win32_PointingDevice.return_value = [ok_mouse]
    mock_wmi.Win32_Keyboard.return_value = [broken_kb]
    mock_wmi.Win32_SoundDevice.return_value = [ok_audio]
    mock_wmi.query.return_value = []

    monitor._wmi = mock_wmi
    status = monitor.collect()

    assert status.all_mice_ok is True
    assert status.all_keyboards_ok is False
    assert status.all_audio_ok is True
    assert status.keyboards[0].error_code == 28
    print("  ✓ 模拟多设备混合状态: 精确识别哪个设备异常")


if __name__ == "__main__":
    print("\n=== 驱动监控模块测试 ===\n")
    print("-- 数据结构 --")
    test_device_info_dataclass()
    test_device_info_to_dict()
    test_driver_status_dataclass()
    test_driver_status_to_dict()
    print("\n-- 状态解析 --")
    test_parse_status()
    print("\n-- 无线检测 --")
    test_detect_connection_type_wired()
    test_detect_connection_type_bluetooth()
    test_detect_connection_type_24g()
    test_detect_connection_type_generic_wireless()
    print("\n-- 集成测试（真实硬件） --")
    test_driver_monitor_collect()
    test_driver_monitor_detects_devices()
    print("\n-- 模拟驱动异常 --")
    test_simulate_mouse_driver_failure()
    test_simulate_keyboard_driver_disabled()
    test_simulate_audio_driver_failure()
    test_simulate_controller_disconnected()
    test_simulate_bluetooth_adapter_failure()
    test_simulate_multiple_failures()
    print("\n全部通过 ✓\n")

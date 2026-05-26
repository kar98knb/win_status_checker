"""
输入/输出设备驱动状态监控模块
监控：鼠标、键盘、耳机/音频、手柄/控制器、蓝牙适配器
支持有线和无线设备
"""

import time
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Optional


# 设备类型常量
DEVICE_TYPE_MOUSE = "mouse"
DEVICE_TYPE_KEYBOARD = "keyboard"
DEVICE_TYPE_AUDIO = "audio"
DEVICE_TYPE_CONTROLLER = "controller"
DEVICE_TYPE_BLUETOOTH = "bluetooth"


@dataclass
class DeviceInfo:
    """单个设备信息"""
    name: str = ""
    device_type: str = ""       # mouse / keyboard / audio / controller / bluetooth
    status: str = "未知"        # "正常" / "异常" / "已禁用" / "未知" / "已断开"
    driver_name: str = ""
    driver_version: str = ""
    driver_date: str = ""
    error_code: int = 0         # 0 = 正常
    is_wireless: bool = False   # 是否无线设备
    connection: str = "有线"    # "有线" / "蓝牙" / "2.4G无线" / "USB无线"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "device_type": self.device_type,
            "status": self.status,
            "driver_name": self.driver_name,
            "driver_version": self.driver_version,
            "driver_date": self.driver_date,
            "error_code": self.error_code,
            "is_wireless": self.is_wireless,
            "connection": self.connection,
        }


@dataclass
class DriverStatus:
    """驱动状态汇总"""
    mice: List[DeviceInfo] = field(default_factory=list)
    keyboards: List[DeviceInfo] = field(default_factory=list)
    audio_devices: List[DeviceInfo] = field(default_factory=list)
    controllers: List[DeviceInfo] = field(default_factory=list)
    bluetooth: List[DeviceInfo] = field(default_factory=list)
    all_mice_ok: bool = True
    all_keyboards_ok: bool = True
    all_audio_ok: bool = True
    all_controllers_ok: bool = True
    all_bluetooth_ok: bool = True
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "mice": [m.to_dict() for m in self.mice],
            "keyboards": [k.to_dict() for k in self.keyboards],
            "audio_devices": [a.to_dict() for a in self.audio_devices],
            "controllers": [c.to_dict() for c in self.controllers],
            "bluetooth": [b.to_dict() for b in self.bluetooth],
            "all_mice_ok": self.all_mice_ok,
            "all_keyboards_ok": self.all_keyboards_ok,
            "all_audio_ok": self.all_audio_ok,
            "all_controllers_ok": self.all_controllers_ok,
            "all_bluetooth_ok": self.all_bluetooth_ok,
            "timestamp": self.timestamp,
        }


# 无线设备关键词（用于判断连接方式）
_WIRELESS_KEYWORDS = [
    "wireless", "bluetooth", "bt", "2.4g", "wifi",
    "无线", "蓝牙", "dongle", "receiver",
]

_BLUETOOTH_KEYWORDS = ["bluetooth", "bt", "蓝牙"]
_24G_KEYWORDS = ["2.4g", "receiver", "dongle", "无线接收器"]


class DriverMonitor:
    """设备驱动监控器 - 使用 WMI + PnP"""

    def __init__(self):
        self._wmi = None
        self._init_wmi()

    def _init_wmi(self):
        """初始化 WMI 连接"""
        try:
            import wmi
            import pythoncom
            pythoncom.CoInitialize()
            self._wmi = wmi.WMI()
        except Exception:
            self._wmi = None

    def collect(self) -> DriverStatus:
        """采集所有设备驱动状态"""
        status = DriverStatus(timestamp=time.time())

        if self._wmi is None:
            self._init_wmi()

        if self._wmi:
            self._collect_mice(status)
            self._collect_keyboards(status)
            self._collect_audio(status)
            self._collect_controllers(status)
            self._collect_bluetooth(status)
        else:
            self._collect_via_powershell(status)

        return status

    def _collect_mice(self, status: DriverStatus):
        """采集鼠标设备信息"""
        try:
            devices = self._wmi.Win32_PointingDevice()
            for dev in devices:
                info = DeviceInfo(
                    name=dev.Name or "未知鼠标",
                    device_type=DEVICE_TYPE_MOUSE,
                    status=self._parse_status(dev.Status, dev.ConfigManagerErrorCode),
                    driver_name=dev.Name or "",
                    error_code=dev.ConfigManagerErrorCode or 0,
                )
                self._detect_connection_type(info)
                status.mice.append(info)
                if info.error_code != 0:
                    status.all_mice_ok = False
        except Exception:
            status.all_mice_ok = False

    def _collect_keyboards(self, status: DriverStatus):
        """采集键盘设备信息"""
        try:
            devices = self._wmi.Win32_Keyboard()
            for dev in devices:
                info = DeviceInfo(
                    name=dev.Name or "未知键盘",
                    device_type=DEVICE_TYPE_KEYBOARD,
                    status=self._parse_status(dev.Status, dev.ConfigManagerErrorCode),
                    driver_name=dev.Name or "",
                    error_code=dev.ConfigManagerErrorCode or 0,
                )
                self._detect_connection_type(info)
                status.keyboards.append(info)
                if info.error_code != 0:
                    status.all_keyboards_ok = False
        except Exception:
            status.all_keyboards_ok = False

    def _collect_audio(self, status: DriverStatus):
        """采集音频设备（耳机、扬声器、麦克风）"""
        try:
            # Win32_SoundDevice 获取音频设备
            devices = self._wmi.Win32_SoundDevice()
            for dev in devices:
                info = DeviceInfo(
                    name=dev.Name or "未知音频设备",
                    device_type=DEVICE_TYPE_AUDIO,
                    status=self._parse_status(dev.Status, dev.ConfigManagerErrorCode),
                    driver_name=dev.Name or "",
                    error_code=dev.ConfigManagerErrorCode or 0,
                )
                self._detect_connection_type(info)
                status.audio_devices.append(info)
                if info.error_code != 0:
                    status.all_audio_ok = False
        except Exception:
            status.all_audio_ok = False

    def _collect_controllers(self, status: DriverStatus):
        """采集游戏控制器/手柄"""
        try:
            # 通过 PNPEntity 查找游戏手柄
            # 排除 "Host Controller"、"Serial IO" 等系统控制器
            query = (
                "SELECT Name, Status, ConfigManagerErrorCode, PNPDeviceID "
                "FROM Win32_PnPEntity WHERE "
                "("
                "PNPClass = 'XboxComposite' OR "
                "PNPClass = 'XnaComposite' OR "
                "Name LIKE '%gamepad%' OR "
                "Name LIKE '%joystick%' OR "
                "Name LIKE '%Xbox%controller%' OR "
                "Name LIKE '%DualSense%' OR "
                "Name LIKE '%DualShock%' OR "
                "Name LIKE '%手柄%' OR "
                "Name LIKE '%game controller%'"
                ") AND "
                "Name NOT LIKE '%Host Controller%' AND "
                "Name NOT LIKE '%Serial IO%' AND "
                "Name NOT LIKE '%USB Root%' AND "
                "Name NOT LIKE '%PCI%'"
            )
            devices = self._wmi.query(query)
            for dev in devices:
                info = DeviceInfo(
                    name=dev.Name or "未知控制器",
                    device_type=DEVICE_TYPE_CONTROLLER,
                    status=self._parse_status(dev.Status, dev.ConfigManagerErrorCode),
                    driver_name=dev.Name or "",
                    error_code=dev.ConfigManagerErrorCode or 0,
                )
                self._detect_connection_type(info)
                status.controllers.append(info)
                if info.error_code != 0:
                    status.all_controllers_ok = False
        except Exception:
            # 没有手柄也是正常的
            pass

    def _collect_bluetooth(self, status: DriverStatus):
        """采集蓝牙适配器和已配对的主要设备"""
        try:
            query = (
                "SELECT Name, Status, ConfigManagerErrorCode "
                "FROM Win32_PnPEntity WHERE "
                "PNPClass = 'Bluetooth' OR "
                "Name LIKE '%Bluetooth%' OR "
                "Name LIKE '%蓝牙%'"
            )
            devices = self._wmi.query(query)

            # 过滤掉底层枚举服务，只保留有意义的设备
            _SKIP_KEYWORDS = [
                "通用属性", "枚举器", "rfcomm", "personal area",
                "串行", "com3", "com4", "com5", "com6",
                "generic attribute", "enumerator",
                "设备信息服务", "通用访问配置文件", "通用属性配置文件",
            ]

            for dev in devices:
                name = dev.Name or ""
                if not name:
                    continue
                # 跳过系统底层蓝牙服务
                name_lower = name.lower()
                if any(kw in name_lower for kw in _SKIP_KEYWORDS):
                    continue

                info = DeviceInfo(
                    name=name,
                    device_type=DEVICE_TYPE_BLUETOOTH,
                    status=self._parse_status(dev.Status, dev.ConfigManagerErrorCode),
                    driver_name=name,
                    error_code=dev.ConfigManagerErrorCode or 0,
                    is_wireless=True,
                    connection="蓝牙",
                )
                status.bluetooth.append(info)
                if info.error_code != 0:
                    status.all_bluetooth_ok = False
        except Exception:
            pass

    def _collect_via_powershell(self, status: DriverStatus):
        """PowerShell 后备方案"""
        device_classes = [
            ("Mouse", DEVICE_TYPE_MOUSE, status.mice),
            ("Keyboard", DEVICE_TYPE_KEYBOARD, status.keyboards),
            ("AudioEndpoint", DEVICE_TYPE_AUDIO, status.audio_devices),
            ("HIDClass", DEVICE_TYPE_CONTROLLER, status.controllers),
            ("Bluetooth", DEVICE_TYPE_BLUETOOTH, status.bluetooth),
        ]

        for pnp_class, device_type, device_list in device_classes:
            try:
                ps_cmd = (
                    f"Get-PnpDevice -Class {pnp_class} -ErrorAction SilentlyContinue | "
                    "Select-Object FriendlyName, Status, ConfigManagerErrorCode | "
                    "ConvertTo-Json"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if result.returncode == 0 and result.stdout.strip():
                    import json
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    for item in data:
                        error_code = item.get("ConfigManagerErrorCode", 0) or 0
                        info = DeviceInfo(
                            name=item.get("FriendlyName", "未知"),
                            device_type=device_type,
                            status=self._parse_status(
                                item.get("Status", ""),
                                error_code
                            ),
                            error_code=error_code,
                        )
                        self._detect_connection_type(info)
                        device_list.append(info)
            except Exception:
                pass

        # 更新汇总状态
        status.all_mice_ok = all(d.error_code == 0 for d in status.mice) if status.mice else True
        status.all_keyboards_ok = all(d.error_code == 0 for d in status.keyboards) if status.keyboards else True
        status.all_audio_ok = all(d.error_code == 0 for d in status.audio_devices) if status.audio_devices else True
        status.all_controllers_ok = all(d.error_code == 0 for d in status.controllers) if status.controllers else True
        status.all_bluetooth_ok = all(d.error_code == 0 for d in status.bluetooth) if status.bluetooth else True

    @staticmethod
    def _detect_connection_type(info: DeviceInfo):
        """根据设备名称推断连接方式"""
        name_lower = info.name.lower()

        # 检查是否无线
        if any(kw in name_lower for kw in _WIRELESS_KEYWORDS):
            info.is_wireless = True

            # 细分无线类型
            if any(kw in name_lower for kw in _BLUETOOTH_KEYWORDS):
                info.connection = "蓝牙"
            elif any(kw in name_lower for kw in _24G_KEYWORDS):
                info.connection = "2.4G无线"
            else:
                info.connection = "USB无线"
        else:
            info.is_wireless = False
            info.connection = "有线"

    @staticmethod
    def _parse_status(status_str: str, error_code: int) -> str:
        """解析设备状态"""
        if error_code is None:
            error_code = 0
        if error_code == 0:
            return "正常"
        elif error_code == 22:
            return "已禁用"
        elif error_code == 45:
            return "已断开"
        elif error_code in (1, 3, 10, 12, 14, 16, 18, 19, 20, 21, 24, 28, 31,
                            32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43,
                            44, 46, 47, 48, 49, 50, 51, 52, 53, 54):
            return "异常"
        else:
            return "未知"

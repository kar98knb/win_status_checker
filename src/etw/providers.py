"""
ETW Provider 定义

Provider GUID 来源：
- 用 `logman query providers` 命令可以列出所有本机注册的 provider
- 参考 Microsoft 官方文档 System Providers（Windows 10 20348+）：
  https://learn.microsoft.com/en-us/windows/win32/etw/system-providers
- NT Kernel Logger 常量：
  https://learn.microsoft.com/en-us/windows/win32/etw/nt-kernel-logger-constants

GUID 是微软定义的全局唯一标识符，跨 Windows 版本保持一致。
"""

import ctypes
from ctypes import wintypes


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, guid_str: str = ""):
        super().__init__()
        if guid_str:
            self._from_string(guid_str)

    def _from_string(self, s: str):
        """从 '{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}' 格式解析"""
        s = s.strip("{}")
        parts = s.split("-")
        self.Data1 = int(parts[0], 16)
        self.Data2 = int(parts[1], 16)
        self.Data3 = int(parts[2], 16)
        data4_hex = parts[3] + parts[4]
        for i in range(8):
            self.Data4[i] = int(data4_hex[i*2:i*2+2], 16)

    def __str__(self):
        d4 = "".join(f"{b:02x}" for b in self.Data4)
        return f"{{{self.Data1:08x}-{self.Data2:04x}-{self.Data3:04x}-{d4[:4]}-{d4[4:]}}}"


# ============ NT Kernel Logger 专用 GUID ============
# NT Kernel Logger session 必须用这个 GUID 创建（Wnode.Guid）
# 参考: https://learn.microsoft.com/en-us/windows/win32/etw/nt-kernel-logger-constants
SYSTEM_TRACE_CONTROL_GUID = GUID("{9E814AAD-3204-11D2-9A82-006008A86939}")


# ============ 用户模式 Provider（EnableTraceEx2 订阅）============
# 这些通过 EnableTraceEx2 API 订阅，可以在任意 session 里启用

# 进程启停
KERNEL_PROCESS = GUID("{22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}")

# 网络 TCP/IP
TCPIP = GUID("{2F07E2EE-15DB-40F1-90EF-9D7BA282188A}")

# 网络 NDIS（链路层）
NDIS = GUID("{CDEAD503-17F5-4A3E-B7AE-DF8CC2902FD9}")

# GPU 调度 (DxgKrnl)
DXGKRNL = GUID("{802EC45A-1E99-4B83-9920-87C98277BA9D}")

# CPU 电源管理/频率变化
KERNEL_PROCESSOR_POWER = GUID("{0F67E49F-FE51-4E9F-B490-6F2948CC6027}")

# 设备即插即用
KERNEL_PNP = GUID("{9C205A39-1250-487D-ABD7-E831C6290539}")

# 磁盘 I/O（用户模式版本）
KERNEL_FILE = GUID("{EDD08927-9CC4-4E65-B970-C2560FB5C289}")

# 磁盘 I/O（读/写/flush 事件）
KERNEL_DISK_NEW = GUID("{C7BDE69A-E1E0-4177-B6EF-283AD1525271}")

# 内存管理（工作集换页、meminfo）
KERNEL_MEMORY = GUID("{D1D93EF7-E1F2-4F45-9943-03D245FE6C00}")


# ============ IO 评估用扩展 Provider ============
# 这些 provider 用于"事后重建"场景，广撒网抓无线鼠标断连、
# 音频卡顿、Bluetooth 掉线等偶发问题。先跑 tests/io_estimate.py
# 评估订阅它们后的持续 IO 速率，再决定是否进主 config。

# USB 2.0 端口层（无线接收器 dongle 走这条路）
USB_USBPORT = GUID("{C88A4EF5-D048-4013-9408-E04B7DB2814A}")

# USB 3.0 集线器（新机型 dongle 走这条路）
USB_USBHUB3 = GUID("{AC52AD17-CC01-4F85-8DF5-4DCE4333C99B}")

# Bluetooth 协议栈（BLE 鼠标/耳机）
BTH_PORT = GUID("{8A1F9517-3A8C-4A9E-A018-4F17A200F277}")

# Bluetooth USB 传输层（BT 芯片本身的问题）
BTH_USB = GUID("{33693E1D-246A-471B-83BE-3E75F47A832D}")

# HID 类驱动（鼠标/键盘/手柄的 HID 数据流）
INPUT_HIDCLASS = GUID("{6465DA78-E7A0-4F39-B084-8F53C7C30DC6}")

# 音频子系统（音频卡顿、buffer underrun）
KERNEL_AUDIO = GUID("{AE4BD3BE-F36F-45B6-8D21-BDD6FB832853}")

# 系统电源事件（休眠/唤醒/电源计划切换）
KERNEL_POWER = GUID("{331C3B3A-2005-44C2-AC5E-77220C37D6B4}")

# USB 3.0 主控（xHCI），比 USBHUB3 更底层
# 主要用途：抓 USB Selective Suspend 引起的 D-state 变化（省电挂起/唤醒）
# 无线接收器卡顿最常见原因之一就是被挂起后唤醒延迟
USB_USBXHCI = GUID("{30E1D284-5D88-459C-83FD-6345B39B19EC}")


# ============ 事件 ID 常量 ============

class ProcessEvents:
    """Microsoft-Windows-Kernel-Process 事件 ID"""
    START = 1       # 进程启动
    STOP = 2        # 进程退出
    THREAD_START = 3
    THREAD_STOP = 4


class TcpipEvents:
    """Microsoft-Windows-TCPIP 事件 ID"""
    CONNECT_ATTEMPT = 12
    CONNECTION_CLOSED = 15
    DISCONNECT = 14
    SEND_FAILED = 17
    RECV_FAILED = 18


class DxgKrnlEvents:
    """Microsoft-Windows-DxgKrnl 事件 ID"""
    TDR_DETECTION = 34
    TDR_RECOVERY = 35
    TDR_FAILURE = 36
    PRESENT = 55


class PnPEvents:
    """Microsoft-Windows-Kernel-PnP 事件 ID"""
    DEVICE_ARRIVAL = 1
    DEVICE_REMOVAL = 2
    DRIVER_LOAD = 100
    DRIVER_UNLOAD = 101


# ============ Keyword 白名单 ============
# 用于 EnableTraceEx2 的 MatchAnyKeyword 参数，只订阅指定 keyword 的事件
# 用 `logman query providers "<name>"` 可查看每个 provider 的 keyword 定义

class Keywords:
    """各 provider 的 keyword 白名单（只关心的事件类别）"""

    # DxgKrnl: Base + DxgKrnl_Power + DriverEvents + Diagnostics
    # 特别注意：不要 Present (0x08000000)，那是每帧一个事件的高频源
    DXGKRNL = 0x00000001 | 0x00000200 | 0x00000400 | 0x00400000

    # Kernel-Process: PROCESS + JOB + PROCESS_FREEZE
    # 不要 THREAD/IMAGE 等细节
    KERNEL_PROCESS = 0x10 | 0x400 | 0x200

    # CPU-Power: Diag + Profiles
    # 只要状态变化，不要 Perf 的高频采样
    CPU_POWER = 0x02 | 0x40

    # TCPIP: Endpoint + ConnectPath + ClosePath + Dropped + Diagnosis
    # 只要连接生命周期和错误，不要每个包
    TCPIP = 0x01 | 0x00000400 | 0x0000000080 | 0x0000000400000000 | 0x0000001000000000 | 0x0000010000000000

    # PnP: 全部（事件量本来就少）
    PNP = 0xFFFFFFFFFFFFFFFF

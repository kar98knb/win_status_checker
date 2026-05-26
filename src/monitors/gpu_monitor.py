"""
GPU 状态监控模块
监控：GPU 使用率、显存、温度、驱动版本
"""

import time
import subprocess
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class GPUStatus:
    """GPU 状态数据"""
    gpu_name: str = "未检测到"
    gpu_usage_percent: float = 0.0
    memory_total_mb: float = 0.0
    memory_used_mb: float = 0.0
    memory_percent: float = 0.0
    temperature_celsius: float = 0.0
    driver_version: str = "未知"
    fan_speed_percent: float = 0.0
    power_draw_watts: float = 0.0
    is_available: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "gpu_name": self.gpu_name,
            "gpu_usage_percent": round(self.gpu_usage_percent, 1),
            "memory_total_mb": round(self.memory_total_mb, 0),
            "memory_used_mb": round(self.memory_used_mb, 0),
            "memory_percent": round(self.memory_percent, 1),
            "temperature_celsius": round(self.temperature_celsius, 1),
            "driver_version": self.driver_version,
            "fan_speed_percent": round(self.fan_speed_percent, 1),
            "power_draw_watts": round(self.power_draw_watts, 1),
            "is_available": self.is_available,
            "timestamp": self.timestamp,
        }


class GPUMonitor:
    """GPU 监控器 - 使用 nvidia-smi 命令行工具"""

    def __init__(self):
        self._nvidia_smi_available = self._check_nvidia_smi()

    def _check_nvidia_smi(self) -> bool:
        """检查 nvidia-smi 是否可用"""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def collect(self) -> GPUStatus:
        """采集 GPU 状态"""
        status = GPUStatus(timestamp=time.time())

        if self._nvidia_smi_available:
            self._collect_nvidia(status)
        else:
            # 尝试通过 WMI 获取基本 GPU 信息（适用于 AMD/Intel）
            self._collect_wmi_fallback(status)

        return status

    def _collect_nvidia(self, status: GPUStatus):
        """通过 nvidia-smi 采集 NVIDIA GPU 数据"""
        try:
            query = (
                "gpu_name,utilization.gpu,memory.total,memory.used,"
                "temperature.gpu,driver_version,fan.speed,power.draw"
            )
            result = subprocess.run(
                [
                    "nvidia-smi",
                    f"--query-gpu={query}",
                    "--format=csv,noheader,nounits"
                ],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            if result.returncode == 0 and result.stdout.strip():
                parts = [p.strip() for p in result.stdout.strip().split(",")]
                if len(parts) >= 6:
                    status.gpu_name = parts[0]
                    status.gpu_usage_percent = self._safe_float(parts[1])
                    status.memory_total_mb = self._safe_float(parts[2])
                    status.memory_used_mb = self._safe_float(parts[3])
                    status.temperature_celsius = self._safe_float(parts[4])
                    status.driver_version = parts[5]

                    if len(parts) >= 7:
                        status.fan_speed_percent = self._safe_float(parts[6])
                    if len(parts) >= 8:
                        status.power_draw_watts = self._safe_float(parts[7])

                    if status.memory_total_mb > 0:
                        status.memory_percent = (
                            status.memory_used_mb / status.memory_total_mb * 100
                        )

                    status.is_available = True

        except (subprocess.TimeoutExpired, Exception):
            status.is_available = False

    def _collect_wmi_fallback(self, status: GPUStatus):
        """WMI + 性能计数器后备方案（适用于 Intel/AMD 显卡）"""
        try:
            import wmi
            w = wmi.WMI()
            gpus = w.Win32_VideoController()
            if gpus:
                gpu = gpus[0]
                status.gpu_name = gpu.Name or "未知"
                status.driver_version = gpu.DriverVersion or "未知"
                if gpu.AdapterRAM:
                    status.memory_total_mb = int(gpu.AdapterRAM) / (1024 * 1024)
                status.is_available = True

                # 通过 Windows 性能计数器获取 GPU 使用率
                status.gpu_usage_percent = self._get_gpu_usage_from_counter()
                status.temperature_celsius = -1  # 非 NVIDIA 暂无温度接口
        except Exception:
            status.is_available = False

    def _get_gpu_usage_from_counter(self) -> float:
        """通过 Windows 性能计数器获取 GPU 总使用率"""
        try:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "(Get-Counter '\\GPU Engine(*engtype_3D*)\\Utilization Percentage' "
                    "-ErrorAction SilentlyContinue).CounterSamples | "
                    "Measure-Object -Property CookedValue -Sum | "
                    "Select-Object -ExpandProperty Sum"
                ],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0 and result.stdout.strip():
                usage = float(result.stdout.strip().replace(",", "."))
                return min(usage, 100.0)
        except (subprocess.TimeoutExpired, ValueError, Exception):
            pass
        return -1

    @staticmethod
    def _safe_float(value: str) -> float:
        """安全转换为浮点数"""
        try:
            # 处理 "[N/A]" 等情况
            cleaned = value.strip().replace("[N/A]", "0").replace("N/A", "0")
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0

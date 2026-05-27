"""
报警模块
当检测到异常时通过 Windows 系统通知弹窗报警
不会遮挡全屏游戏，通知会出现在操作中心
"""

import time
import logging
import threading
from typing import Dict, Optional

logger = logging.getLogger("alerter")


class Alerter:
    """报警器 - 使用 Windows Toast 通知"""

    def __init__(self, cooldown_seconds: int = 60):
        self._cooldown = cooldown_seconds
        self._last_alert_time: Dict[str, float] = {}
        self._lock = threading.Lock()

    def alert(self, alert_type: str, title: str, message: str, level: str = "warning"):
        with self._lock:
            now = time.time()
            last_time = self._last_alert_time.get(alert_type, 0)
            if now - last_time < self._cooldown:
                return
            self._last_alert_time[alert_type] = now

        log_msg = f"[{level.upper()}] {title}: {message}"
        if level == "critical":
            logger.critical(log_msg)
        elif level == "warning":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        threading.Thread(
            target=self._send_notification,
            args=(title, message, level),
            daemon=True
        ).start()

    def _send_notification(self, title: str, message: str, level: str):
        try:
            icon = "⚠️" if level == "warning" else "🔴" if level == "critical" else "ℹ️"
            full_title = f"{icon} 游戏监控 - {title}"
            ps_script = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$template = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>{full_title}</text>
            <text>{message}</text>
        </binding>
    </visual>
</toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("GameMonitor").Show($toast)
'''
            import subprocess
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, timeout=10, creationflags=0x08000000
            )
        except Exception as e:
            logger.debug(f"通知发送失败: {e}")
            try:
                import subprocess
                subprocess.run(
                    ["msg", "*", f"{title}\n{message}"],
                    capture_output=True, timeout=5, creationflags=0x08000000
                )
            except Exception:
                pass

    def check_and_alert(self, network_status, gpu_status, driver_status, thresholds: dict):
        # 网络报警
        if network_status:
            if not network_status.is_connected:
                self.alert("network_down", "网络断开", "检测到网络连接已断开！", "critical")
            elif network_status.packet_loss_percent > thresholds.get("packet_loss_percent", 5):
                self.alert("packet_loss", "网络丢包",
                           f"丢包率 {network_status.packet_loss_percent:.1f}%，可能影响游戏体验", "warning")
            elif network_status.latency_ms > thresholds.get("latency_ms", 100):
                self.alert("high_latency", "网络延迟高",
                           f"延迟 {network_status.latency_ms:.0f}ms，可能导致游戏卡顿", "warning")

        # GPU 报警
        if gpu_status and gpu_status.is_available:
            if gpu_status.temperature_celsius > thresholds.get("gpu_temp_celsius", 85) and gpu_status.temperature_celsius > 0:
                self.alert("gpu_temp", "GPU 过热",
                           f"GPU 温度 {gpu_status.temperature_celsius:.0f}°C，建议检查散热", "critical")
            if gpu_status.memory_percent > thresholds.get("gpu_memory_percent", 95):
                self.alert("gpu_memory", "显存不足",
                           f"显存使用 {gpu_status.memory_percent:.1f}%，可能导致游戏崩溃", "warning")
            if gpu_status.gpu_usage_percent > thresholds.get("gpu_usage_percent", 98):
                self.alert("gpu_usage", "GPU 满载",
                           f"GPU 使用率 {gpu_status.gpu_usage_percent:.0f}%", "info")

        # 驱动报警
        if driver_status:
            if not driver_status.all_mice_ok:
                self.alert("mouse_driver", "鼠标驱动异常", "检测到鼠标设备驱动异常，可能影响操作", "critical")
            if not driver_status.all_keyboards_ok:
                self.alert("keyboard_driver", "键盘驱动异常", "检测到键盘设备驱动异常，可能影响操作", "critical")
            if not driver_status.all_audio_ok:
                self.alert("audio_driver", "音频设备异常", "检测到耳机/音频设备驱动异常，可能影响语音", "warning")
            if not driver_status.all_controllers_ok:
                self.alert("controller_driver", "手柄驱动异常", "检测到游戏手柄/控制器驱动异常", "warning")
            if not driver_status.all_bluetooth_ok:
                self.alert("bluetooth_driver", "蓝牙异常", "蓝牙适配器或设备驱动异常，无线设备可能受影响", "warning")

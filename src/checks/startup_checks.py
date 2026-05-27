"""
启动时一次性检测模块
检测项目在服务启动前运行一次，结果记录到日志并在 Web 面板展示。
"""

import subprocess
import logging
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger("startup_checks")


@dataclass
class StartupCheckResult:
    """启动检测结果"""
    power_plan: str = "未知"
    power_plan_ok: bool = False
    display_refresh_rate: int = 0
    display_refresh_ok: bool = True
    pending_reboot: bool = False
    total_memory_gb: float = 0.0
    memory_ok: bool = True
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "power_plan": self.power_plan,
            "power_plan_ok": self.power_plan_ok,
            "display_refresh_rate": self.display_refresh_rate,
            "display_refresh_ok": self.display_refresh_ok,
            "pending_reboot": self.pending_reboot,
            "total_memory_gb": round(self.total_memory_gb, 1),
            "memory_ok": self.memory_ok,
            "warnings": self.warnings,
        }


def run_startup_checks(min_refresh_hz: int = 120, min_memory_gb: float = 8.0) -> StartupCheckResult:
    result = StartupCheckResult()
    _check_power_plan(result)
    _check_display_refresh(result, min_refresh_hz)
    _check_pending_reboot(result)
    _check_total_memory(result, min_memory_gb)
    if result.warnings:
        for w in result.warnings:
            logger.warning(f"[启动检测] {w}")
    else:
        logger.info("[启动检测] 所有项目正常")
    return result


def _check_power_plan(result: StartupCheckResult):
    try:
        output = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if output.returncode == 0:
            line = output.stdout.strip()
            if "(" in line and ")" in line:
                plan_name = line.split("(")[-1].rstrip(")")
                result.power_plan = plan_name
                high_perf_keywords = [
                    "高性能", "卓越性能", "high performance",
                    "ultimate performance", "游戏", "game",
                ]
                result.power_plan_ok = any(kw in plan_name.lower() for kw in high_perf_keywords)
                if not result.power_plan_ok:
                    result.warnings.append(
                        f"电源计划为「{plan_name}」，建议切换到「高性能」以获得最佳游戏体验"
                    )
    except Exception as e:
        logger.debug(f"电源计划检测失败: {e}")


def _check_display_refresh(result: StartupCheckResult, min_hz: int):
    try:
        ps_cmd = (
            "Get-CimInstance Win32_VideoController | "
            "Select-Object -First 1 -ExpandProperty CurrentRefreshRate"
        )
        output = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if output.returncode == 0 and output.stdout.strip():
            hz = int(output.stdout.strip())
            result.display_refresh_rate = hz
            result.display_refresh_ok = hz >= min_hz
            if not result.display_refresh_ok:
                result.warnings.append(
                    f"显示器刷新率为 {hz}Hz，低于 {min_hz}Hz，可能未开启高刷"
                )
    except Exception as e:
        logger.debug(f"刷新率检测失败: {e}")


def _check_pending_reboot(result: StartupCheckResult):
    try:
        ps_cmd = (
            "Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion"
            "\\WindowsUpdate\\Auto Update\\RebootRequired'"
        )
        output = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if output.returncode == 0:
            result.pending_reboot = output.stdout.strip().lower() == "true"
            if result.pending_reboot:
                result.warnings.append("系统有待重启的更新，可能随时弹窗打断游戏")
    except Exception as e:
        logger.debug(f"更新状态检测失败: {e}")


def _check_total_memory(result: StartupCheckResult, min_gb: float):
    try:
        import psutil
        mem = psutil.virtual_memory()
        result.total_memory_gb = mem.total / (1024 ** 3)
        result.memory_ok = result.total_memory_gb >= min_gb
        if not result.memory_ok:
            result.warnings.append(
                f"系统内存 {result.total_memory_gb:.1f}GB，低于推荐的 {min_gb}GB"
            )
    except Exception as e:
        logger.debug(f"内存检测失败: {e}")

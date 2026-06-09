"""
状态快照模块
每次采集后立即将系统状态写入磁盘，确保卡死时数据不丢失。
重启后可回溯卡死前的最后状态。
"""

import os
import json
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("snapshot")

SNAPSHOT_FILE = Path(__file__).parent.parent.parent / "logs" / "last_snapshot.json"


def save_snapshot(data: dict):
    snapshot = {"timestamp": time.time(), "data": data}
    tmp_path = str(SNAPSHOT_FILE) + ".tmp"
    try:
        SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        if SNAPSHOT_FILE.exists():
            os.replace(tmp_path, str(SNAPSHOT_FILE))
        else:
            os.rename(tmp_path, str(SNAPSHOT_FILE))
    except Exception as e:
        logger.debug(f"快照写入失败: {e}")
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def check_abnormal_exit(max_gap_seconds: float = 30.0) -> Optional[dict]:
    if not SNAPSHOT_FILE.exists():
        return None
    try:
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
        last_time = snapshot.get("timestamp", 0)
        gap = time.time() - last_time
        if gap > max_gap_seconds:
            crash_report = {
                "detected_at": time.time(),
                "last_snapshot_time": last_time,
                "gap_seconds": round(gap, 1),
                "last_state": snapshot.get("data", {}),
                "conclusion": _analyze_crash_cause(snapshot.get("data", {})),
            }
            return crash_report
    except (json.JSONDecodeError, Exception) as e:
        logger.debug(f"快照读取失败: {e}")
    return None


def clear_snapshot():
    try:
        if SNAPSHOT_FILE.exists():
            SNAPSHOT_FILE.unlink()
    except Exception:
        pass


def _analyze_crash_cause(data: dict) -> str:
    reasons = []
    gpu = data.get("gpu", {})
    if gpu.get("temperature_celsius", 0) > 90:
        reasons.append(f"GPU 过热 ({gpu['temperature_celsius']}°C)，可能导致显卡驱动崩溃")
    if gpu.get("memory_percent", 0) > 95:
        reasons.append(f"显存几乎满载 ({gpu['memory_percent']}%)，可能导致渲染崩溃")
    system = data.get("system", {})
    if system.get("memory_percent", 0) > 95:
        reasons.append(f"系统内存严重不足 ({system['memory_percent']}%)，可能触发 OOM")
    if system.get("cpu_throttled"):
        reasons.append("CPU 降频中，可能过热")
    network = data.get("network", {})
    if not network.get("is_connected", True):
        reasons.append("网络已断开")
    drivers = data.get("drivers", {})
    if not drivers.get("all_mice_ok", True):
        reasons.append("鼠标驱动异常")
    if not drivers.get("all_keyboards_ok", True):
        reasons.append("键盘驱动异常")
    if reasons:
        return "可能原因: " + "; ".join(reasons)
    else:
        return "卡死前各项指标正常，可能是游戏本身或显卡驱动问题"

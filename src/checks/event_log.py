"""
Windows 事件日志与崩溃证据回溯模块
启动时读取系统事件日志 + 检查崩溃转储文件，查找上次运行期间的崩溃证据。

关注的事件：
- Event ID 41 (Kernel-Power): 意外断电/卡死重启
- Event ID 6008 (EventLog): 上一次系统关机是意外的
- Event ID 4101 (Display): GPU TDR（显卡驱动超时恢复）
- Event ID 14 (nvlddmkm/display): GPU 驱动崩溃
- Event ID 1001 (Windows Error Reporting): 应用崩溃
- Event ID 7034 (Service Control Manager): 服务意外停止

崩溃转储检查：
- C:\Windows\LiveKernelReports\ — GPU 驱动 hang dump（不蓝屏也有）
- C:\Windows\Minidump\ — 蓝屏 minidump
"""

import subprocess
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("event_log")


@dataclass
class SystemEvent:
    """一条系统事件"""
    time: str = ""
    event_id: int = 0
    source: str = ""
    level: str = ""       # "Critical" / "Error" / "Warning"
    message: str = ""
    category: str = ""    # "crash" / "gpu_tdr" / "power" / "driver" / "service" / "app_crash"

    def to_dict(self) -> dict:
        return {
            "time": self.time,
            "event_id": self.event_id,
            "source": self.source,
            "level": self.level,
            "message": self.message,
            "category": self.category,
        }


@dataclass
class CrashDumpInfo:
    """崩溃转储文件信息"""
    file_path: str = ""
    file_time: str = ""
    dump_type: str = ""   # "minidump" / "live_kernel" / "full"
    size_kb: int = 0

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "file_time": self.file_time,
            "dump_type": self.dump_type,
            "size_kb": self.size_kb,
        }


@dataclass
class EventLogResult:
    """事件日志回溯结果"""
    events: List[SystemEvent] = field(default_factory=list)
    crash_dumps: List[CrashDumpInfo] = field(default_factory=list)
    has_unexpected_shutdown: bool = False
    has_gpu_tdr: bool = False
    has_app_crash: bool = False
    has_bsod: bool = False
    has_critical_error: bool = False
    scan_hours: int = 0

    def to_dict(self) -> dict:
        return {
            "events": [e.to_dict() for e in self.events],
            "crash_dumps": [d.to_dict() for d in self.crash_dumps],
            "has_unexpected_shutdown": self.has_unexpected_shutdown,
            "has_gpu_tdr": self.has_gpu_tdr,
            "has_app_crash": self.has_app_crash,
            "has_bsod": self.has_bsod,
            "has_critical_error": self.has_critical_error,
            "event_count": len(self.events),
            "scan_hours": self.scan_hours,
        }


# 关注的事件 ID 及其分类
_EVENT_FILTERS = {
    41: "crash",       # Kernel-Power: 意外断电/卡死
    6008: "crash",     # EventLog: 上次关机异常
    4101: "gpu_tdr",   # Display: TDR（显卡驱动超时恢复）
    14: "gpu_tdr",     # nvlddmkm: NVIDIA 驱动崩溃
    1001: "app_crash", # Windows Error Reporting: 应用崩溃
    7034: "service",   # 服务意外停止
}

# Application 日志里的应用崩溃事件
_APP_EVENT_FILTERS = {
    1000: "app_crash",  # Application Error: 程序崩溃（含模块名、异常代码）
    1001: "app_crash",  # WER: 崩溃报告详情
}

# 崩溃转储文件搜索路径
_DUMP_PATHS = [
    (Path(r"C:\Windows\LiveKernelReports"), "live_kernel"),
    (Path(r"C:\Windows\Minidump"), "minidump"),
]


def check_system_events(hours_back: int = 24) -> EventLogResult:
    """
    回溯 Windows 系统事件日志 + 检查崩溃转储文件。

    Args:
        hours_back: 回溯多少小时的日志

    Returns:
        EventLogResult 包含找到的相关事件和 dump 文件
    """
    result = EventLogResult(scan_hours=hours_back)

    try:
        events = _query_events(hours_back)
        result.events = events

        for event in events:
            if event.category == "crash":
                result.has_unexpected_shutdown = True
            elif event.category == "gpu_tdr":
                result.has_gpu_tdr = True
            elif event.category == "app_crash":
                result.has_app_crash = True
            if event.level in ("Critical", "1"):
                result.has_critical_error = True

    except Exception as e:
        logger.debug(f"事件日志查询失败: {e}")

    # 检查崩溃转储文件
    try:
        result.crash_dumps = _check_crash_dumps(hours_back)
        if any(d.dump_type == "minidump" for d in result.crash_dumps):
            result.has_bsod = True
    except Exception as e:
        logger.debug(f"崩溃转储检查失败: {e}")

    # 记录日志
    if result.has_unexpected_shutdown:
        logger.critical("[事件日志] 检测到意外关机/卡死重启记录 (Event 41/6008)")
    if result.has_gpu_tdr:
        logger.critical("[事件日志] 检测到 GPU 驱动超时/崩溃记录 (TDR)")
    if result.has_bsod:
        logger.critical("[事件日志] 发现蓝屏转储文件 (Minidump)")
    if result.crash_dumps:
        for d in result.crash_dumps:
            logger.warning(f"[崩溃转储] {d.dump_type}: {d.file_path} ({d.file_time})")
    if result.has_app_crash:
        logger.warning("[事件日志] 检测到应用崩溃记录 (WER)")
    if not result.events and not result.crash_dumps:
        logger.info(f"[事件日志] 过去 {hours_back}h 内无异常事件")

    return result


def _query_events(hours_back: int) -> List[SystemEvent]:
    """通过 PowerShell 查询 Windows 事件日志（System + Application）"""
    events = []

    # 查询 System 日志
    sys_ids = ",".join(str(eid) for eid in _EVENT_FILTERS.keys())
    events += _run_event_query("System", sys_ids, hours_back, _EVENT_FILTERS)

    # 查询 Application 日志（应用崩溃）
    app_ids = ",".join(str(eid) for eid in _APP_EVENT_FILTERS.keys())
    events += _run_event_query("Application", app_ids, hours_back, _APP_EVENT_FILTERS)

    return events


def _run_event_query(log_name: str, event_ids: str, hours_back: int, filters: dict) -> List[SystemEvent]:
    """执行单个日志源的查询"""
    ps_cmd = (
        f"Get-WinEvent -FilterHashtable @{{"
        f"LogName='{log_name}';"
        f"ID={event_ids};"
        f"StartTime=(Get-Date).AddHours(-{hours_back})"
        f"}} -MaxEvents 20 -ErrorAction SilentlyContinue | "
        f"Select-Object TimeCreated, Id, ProviderName, LevelDisplayName, Message | "
        f"ConvertTo-Json -Depth 2"
    )

    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    if proc.returncode != 0 or not proc.stdout.strip():
        return []

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []

    # PowerShell 单条结果返回 dict 而非 list
    if isinstance(data, dict):
        data = [data]

    events = []
    for item in data:
        event_id = item.get("Id", 0)
        category = filters.get(event_id, "other")

        # 截取 message 前 200 字符
        message = item.get("Message", "") or ""
        if len(message) > 200:
            message = message[:200] + "..."

        # 解析时间（PowerShell 返回 "/Date(timestamp)/" 格式）
        time_str = _parse_ps_datetime(item.get("TimeCreated"))

        events.append(SystemEvent(
            time=time_str,
            event_id=event_id,
            source=item.get("ProviderName", ""),
            level=item.get("LevelDisplayName", ""),
            message=message,
            category=category,
        ))

    return events


def _parse_ps_datetime(value) -> str:
    """解析 PowerShell JSON 中的日期格式"""
    if value is None:
        return ""

    # 格式: "/Date(1717000000000)/"
    if isinstance(value, str) and "/Date(" in value:
        try:
            ts_ms = int(value.split("(")[1].split(")")[0].split("+")[0].split("-")[0])
            dt = datetime.fromtimestamp(ts_ms / 1000)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
            return value

    # 可能已经是字符串格式
    return str(value)


def _check_crash_dumps(hours_back: int) -> List[CrashDumpInfo]:
    """检查最近的崩溃转储文件"""
    cutoff = datetime.now() - timedelta(hours=hours_back)
    dumps = []

    for dump_dir, dump_type in _DUMP_PATHS:
        if not dump_dir.exists():
            continue
        try:
            # LiveKernelReports 里有子目录
            patterns = ["*.dmp", "**/*.dmp"]
            for pattern in patterns:
                for dmp_file in dump_dir.glob(pattern):
                    try:
                        mtime = datetime.fromtimestamp(dmp_file.stat().st_mtime)
                        if mtime > cutoff:
                            dumps.append(CrashDumpInfo(
                                file_path=str(dmp_file),
                                file_time=mtime.strftime("%Y-%m-%d %H:%M:%S"),
                                dump_type=dump_type,
                                size_kb=int(dmp_file.stat().st_size / 1024),
                            ))
                    except (OSError, ValueError):
                        continue
        except PermissionError:
            # LiveKernelReports 可能需要管理员权限
            logger.debug(f"无权访问 {dump_dir}")

    return dumps

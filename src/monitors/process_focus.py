"""
进程焦点监控模块
自动发现并锁定高资源占用的前台进程（通常是游戏），
持续追踪其 CPU、内存、GPU 占用，崩溃时快速定位。

机制：
1. 排除白名单进程（浏览器、系统服务等）
2. 连续 N 次采样 CPU/GPU 高占用的进程自动成为焦点
3. 焦点进程消失（崩溃/退出）时记录事件
"""

import time
import logging
import psutil
from dataclasses import dataclass, field
from typing import Optional, Set, Dict

from config import FOCUS_WHITELIST

logger = logging.getLogger("process_focus")

# 焦点触发条件
_FOCUS_CPU_THRESHOLD = 25.0       # CPU 占用超过此值才考虑
_FOCUS_CONSECUTIVE_COUNT = 3      # 连续 N 次采样都高占用才锁定
_FOCUS_LOST_GRACE_PERIOD = 5.0    # 进程消失后等几秒再判定为崩溃（避免正常退出误报）


@dataclass
class FocusedProcess:
    """被焦点跟踪的进程"""
    pid: int = 0
    name: str = ""
    exe_path: str = ""
    start_time: float = 0.0       # 进程启动时间
    focus_since: float = 0.0      # 成为焦点的时间
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    thread_count: int = 0
    status: str = "running"       # "running" / "exited" / "crashed"
    exit_code: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "name": self.name,
            "exe_path": self.exe_path,
            "focus_since": self.focus_since,
            "cpu_percent": round(self.cpu_percent, 1),
            "memory_mb": round(self.memory_mb, 0),
            "memory_percent": round(self.memory_percent, 1),
            "thread_count": self.thread_count,
            "status": self.status,
            "exit_code": self.exit_code,
        }


@dataclass
class ProcessFocusStatus:
    """进程焦点状态"""
    focused: Optional[FocusedProcess] = None
    recent_exits: list = field(default_factory=list)  # 最近退出的焦点进程
    candidates: list = field(default_factory=list)    # 当前候选进程
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "focused": self.focused.to_dict() if self.focused else None,
            "recent_exits": self.recent_exits[-5:],  # 最多保留 5 条
            "candidates": [{"name": c[0], "cpu": round(c[1], 1)} for c in self.candidates[:3]],
            "timestamp": self.timestamp,
        }


class ProcessFocusMonitor:
    """进程焦点监控器"""

    def __init__(self, whitelist: Optional[Set[str]] = None):
        self._whitelist = whitelist or FOCUS_WHITELIST
        self._focused: Optional[FocusedProcess] = None
        self._candidate_counts: Dict[int, int] = {}  # pid -> 连续高占用次数
        self._recent_exits: list = []
        self._last_focused_seen: float = 0

    def collect(self) -> ProcessFocusStatus:
        """采集进程焦点状态"""
        status = ProcessFocusStatus(timestamp=time.time())

        # 如果有焦点进程，更新它的状态
        if self._focused:
            self._update_focused(status)
        
        # 扫描候选进程
        candidates = self._scan_candidates()
        status.candidates = candidates

        # 尝试锁定新焦点
        if not self._focused:
            self._try_acquire_focus(candidates)

        status.focused = self._focused
        status.recent_exits = self._recent_exits[-5:]
        return status

    def _update_focused(self, status: ProcessFocusStatus):
        """更新焦点进程状态"""
        try:
            proc = psutil.Process(self._focused.pid)
            if not proc.is_running():
                raise psutil.NoSuchProcess(self._focused.pid)

            self._focused.cpu_percent = proc.cpu_percent(interval=None)
            mem_info = proc.memory_info()
            self._focused.memory_mb = mem_info.rss / (1024 * 1024)
            self._focused.memory_percent = proc.memory_percent()
            self._focused.thread_count = proc.num_threads()
            self._focused.status = "running"
            self._last_focused_seen = time.time()

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # 进程消失了
            elapsed = time.time() - self._last_focused_seen
            if elapsed > _FOCUS_LOST_GRACE_PERIOD:
                self._handle_focus_lost()

    def _handle_focus_lost(self):
        """焦点进程消失处理"""
        if not self._focused:
            return

        self._focused.status = "exited"
        exit_record = {
            "name": self._focused.name,
            "pid": self._focused.pid,
            "exe_path": self._focused.exe_path,
            "exited_at": time.time(),
            "focus_duration_sec": round(time.time() - self._focused.focus_since, 0),
            "last_cpu_percent": self._focused.cpu_percent,
            "last_memory_mb": round(self._focused.memory_mb, 0),
        }
        self._recent_exits.append(exit_record)

        logger.warning(
            f"[焦点进程退出] {self._focused.name} (PID {self._focused.pid}) "
            f"已退出/崩溃，持续焦点 {exit_record['focus_duration_sec']}s"
        )

        self._focused = None

    def _scan_candidates(self) -> list:
        """扫描高占用进程作为候选"""
        candidates = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                try:
                    info = proc.info
                    name = (info.get('name') or '').lower()
                    cpu = info.get('cpu_percent', 0) or 0

                    # 排除白名单
                    if name in self._whitelist:
                        continue
                    # 排除低占用
                    if cpu < _FOCUS_CPU_THRESHOLD:
                        continue

                    candidates.append((info['name'], cpu, info['pid']))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

        # 按 CPU 排序
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates

    def _try_acquire_focus(self, candidates: list):
        """尝试锁定焦点进程"""
        if not candidates:
            self._candidate_counts.clear()
            return

        # 取 CPU 最高的候选
        top_name, top_cpu, top_pid = candidates[0]

        # 计数连续高占用
        self._candidate_counts[top_pid] = self._candidate_counts.get(top_pid, 0) + 1

        # 清理不再出现的候选
        current_pids = {c[2] for c in candidates}
        self._candidate_counts = {
            pid: count for pid, count in self._candidate_counts.items()
            if pid in current_pids
        }

        # 达到阈值，锁定焦点
        if self._candidate_counts.get(top_pid, 0) >= _FOCUS_CONSECUTIVE_COUNT:
            try:
                proc = psutil.Process(top_pid)
                self._focused = FocusedProcess(
                    pid=top_pid,
                    name=top_name,
                    exe_path=proc.exe() if proc.exe() else "",
                    start_time=proc.create_time(),
                    focus_since=time.time(),
                    cpu_percent=top_cpu,
                )
                self._last_focused_seen = time.time()
                self._candidate_counts.clear()

                logger.info(
                    f"[焦点锁定] {top_name} (PID {top_pid}, CPU {top_cpu:.0f}%)"
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    @property
    def focused_process(self) -> Optional[FocusedProcess]:
        """获取当前焦点进程"""
        return self._focused

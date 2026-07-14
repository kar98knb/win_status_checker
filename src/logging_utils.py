"""
运行时日志辅助：把 stdout/stderr 复制到文件。

场景 1（追加模式）：脚本反复跑，每次运行在一个共享 log 里追加，
                    用于离线看历史输出。POC / io_estimate 都用这个。

场景 2（覆盖模式）：每次运行独立目录 + 独立 log，main.py 用这个。
"""

import sys
from pathlib import Path


class _Tee:
    """把 write 分发到多个流的最小实现。"""
    def __init__(self, *streams):
        self._streams = streams

    def write(self, s):
        for st in self._streams:
            try:
                st.write(s)
                st.flush()
            except Exception:
                pass

    def flush(self):
        for st in self._streams:
            try:
                st.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def tee_stdout(log_path, mode: str = "a", banner: bool = True):
    """
    把 stdout + stderr 同时输出到文件和原始终端。

    Args:
        log_path: 日志文件路径，父目录会自动创建
        mode: "a" 追加（多次运行历史都保留），"w" 覆盖
        banner: 是否在开头打一条"Run at ..."横幅（追加模式下有用）

    Returns:
        底层文件对象（一般不用管，让它随进程退出关闭）
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(log_path, mode, encoding="utf-8", buffering=1)   # 行缓冲，实时刷

    sys.stdout = _Tee(sys.__stdout__, f)
    sys.stderr = _Tee(sys.__stderr__, f)

    if banner:
        import datetime
        text = f"\n{'='*70}\n  Run at {datetime.datetime.now().isoformat()}\n{'='*70}\n"
        sys.stdout.write(text)

    return f

"""
实验: 进程崩溃 vs 正常退出

核心假设：Kernel-Process 的 STOP 事件（event id=2）payload 带 ExitCode 字段，
真正的崩溃会留下明显的 NT status code：
- 0x00000000 = 正常退出
- 0x00000001 = Python 未捕获异常 (sys.exit(1))
- 0xC0000005 = STATUS_ACCESS_VIOLATION（访问违规，最典型的崩溃）
- 0xC0000094 = STATUS_INTEGER_DIVIDE_BY_ZERO
- 0xC00000FD = STATUS_STACK_OVERFLOW

本实验触发三种子进程：
1. clean_exit   -> exit(0)
2. python_error -> raise Exception  -> exit(1)
3. hard_crash   -> 访问 0 地址   -> exit(0xC0000005)

每个子进程的 PID 会写到 artifacts/process_crash/child_pids.json，
供 analyze_crash.py 精确匹配（Kernel-Process START 事件 payload 里没有 CommandLine，
只能靠 PID）。
"""

import sys
import json
import time
import subprocess
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.filter_validation.framework import run_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


# 三种子进程的一行 Python 代码
_CHILD_SCRIPTS = {
    "clean_exit":   "import sys; sys.exit(0)",
    "python_error": "raise Exception('simulated python error')",
    "hard_crash":   "import ctypes; ctypes.string_at(0)",  # 读 0 地址 -> AV -> 0xC0000005
}

PIDS_FILE = Path(__file__).parent / "artifacts" / "process_crash" / "child_pids.json"


def trigger_crash():
    """依次启动三种子进程，把 PID 和结果写到 child_pids.json"""
    records = []
    for label, code in _CHILD_SCRIPTS.items():
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        pid = proc.pid
        proc.wait(timeout=30)
        rc = proc.returncode
        rc_u32 = rc & 0xFFFFFFFF
        print(f"    {label:<12} pid={pid:<6} exit_code=0x{rc_u32:08X} ({rc})")
        records.append({
            "label": label,
            "pid": pid,
            "exit_code": rc_u32,
        })
        time.sleep(0.4)

    PIDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PIDS_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"    子进程信息写入 {PIDS_FILE}")


if __name__ == "__main__":
    run_experiment(
        scenario_name="process_crash",
        warmup_seconds=5,
        trigger_fn=trigger_crash,
        wait_after_seconds=3,
    )

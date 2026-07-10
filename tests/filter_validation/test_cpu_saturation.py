"""
实验: CPU 占满（更贴近游戏场景）

启动一批 CPU 密集线程把所有核心跑满，持续几秒后自杀。
预期 filtered session 能观察到:
- CPU-Power 频率/状态变化（负载上升）
- Kernel-Process 大量进程活动
- 进程结束时的 STOP 事件
"""

import sys
import time
import subprocess
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.filter_validation.framework import run_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


# CPU 忙循环脚本（在子进程里跑，避免污染主进程）
_CPU_BURN_SCRIPT = """
import os
import time
import multiprocessing

def burn():
    end = time.time() + 3.0  # 忙 3 秒
    x = 0
    while time.time() < end:
        for _ in range(10000):
            x = (x * x + 1) % 1000000007

if __name__ == '__main__':
    n = multiprocessing.cpu_count()
    procs = []
    for _ in range(n):
        p = multiprocessing.Process(target=burn)
        p.start()
        procs.append(p)
    for p in procs:
        p.join()
"""


def trigger_cpu_saturation():
    """启动 N 个进程占满所有 CPU 核心，跑 3 秒后自杀"""
    script_file = Path(__file__).parent / "artifacts" / "_cpu_burn.py"
    script_file.parent.mkdir(parents=True, exist_ok=True)
    script_file.write_text(_CPU_BURN_SCRIPT, encoding="utf-8")

    print("  启动 CPU 密集进程...")
    # 阻塞等待所有子进程完成
    subprocess.run(
        [sys.executable, str(script_file)],
        capture_output=True,
        timeout=30,
    )
    print("  所有 CPU 密集进程已退出")


if __name__ == "__main__":
    run_experiment(
        scenario_name="cpu_saturation",
        warmup_seconds=5,
        trigger_fn=trigger_cpu_saturation,
        wait_after_seconds=3,
    )

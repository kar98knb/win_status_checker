"""
实验: 内存压力（更贴近真实场景）

启动一个子进程尽量分配到系统 70% 内存（避免触发 OOM），
持续几秒后自杀。

预期观察到:
- Kernel-Memory MEMINFO 事件反映可用内存下降
- Kernel-Memory WS_SWAP 事件（工作集换页）
- 磁盘活动（因为内存压力可能引起 pagefile 使用）
"""

import sys
import time
import subprocess
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.filter_validation.framework import run_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


_MEM_BURN_SCRIPT = """
import os
import time
import ctypes

# 用 ctypes 读系统内存
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ('dwLength', ctypes.c_ulong),
        ('dwMemoryLoad', ctypes.c_ulong),
        ('ullTotalPhys', ctypes.c_ulonglong),
        ('ullAvailPhys', ctypes.c_ulonglong),
        ('ullTotalPageFile', ctypes.c_ulonglong),
        ('ullAvailPageFile', ctypes.c_ulonglong),
        ('ullTotalVirtual', ctypes.c_ulonglong),
        ('ullAvailVirtual', ctypes.c_ulonglong),
        ('sullAvailExtendedVirtual', ctypes.c_ulonglong),
    ]

def get_available_mb():
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(stat)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return stat.ullAvailPhys // (1024 * 1024), stat.ullTotalPhys // (1024 * 1024)

if __name__ == '__main__':
    avail, total = get_available_mb()
    # 目标: 占用到系统总内存的 70%（不到 OOM 触发线）
    # 已用 = total - avail, 需要再吃 = total * 0.7 - (total - avail) = avail - total * 0.3
    target_mb = int(avail - total * 0.3)
    # 保底至少 500MB，不超过可用的 80%
    target_mb = max(500, min(target_mb, int(avail * 0.8)))

    print(f'总内存 {total}MB, 可用 {avail}MB, 目标吃 {target_mb}MB', flush=True)

    # 分批 100MB 分配，可控
    chunks = []
    chunk_size = 100 * 1024 * 1024
    n = target_mb // 100
    for i in range(n):
        chunk = bytearray(chunk_size)
        # 触碰所有页，确保物理分配
        for j in range(0, chunk_size, 4096):
            chunk[j] = 1
        chunks.append(chunk)

    # 持续占用 4 秒
    time.sleep(4)
    # 主动释放（自杀退出会自动释放）
"""


def trigger_memory_pressure():
    """启动子进程占用大量内存，持续几秒后退出"""
    script_file = Path(__file__).parent / "artifacts" / "_mem_burn.py"
    script_file.parent.mkdir(parents=True, exist_ok=True)
    script_file.write_text(_MEM_BURN_SCRIPT, encoding="utf-8")

    print("  启动内存压力进程...")
    result = subprocess.run(
        [sys.executable, str(script_file)],
        capture_output=True, text=True,
        timeout=60,
    )
    if result.stdout:
        print("  子进程输出:", result.stdout.strip())
    print("  内存压力进程已退出，内存已释放")


if __name__ == "__main__":
    run_experiment(
        scenario_name="memory_pressure",
        warmup_seconds=5,
        trigger_fn=trigger_memory_pressure,
        wait_after_seconds=3,
    )

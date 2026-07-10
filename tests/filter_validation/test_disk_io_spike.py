"""
实验: 磁盘 IO 突发

假设: 通过大文件读写产生 IO 压力
本实验主要验证：黑名单对磁盘卡顿诊断的影响（目前 Kernel-Disk 未订阅，但可对比通过其他 provider 是否能间接看到）
"""

import sys
import time
import os
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.filter_validation.framework import run_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def trigger_disk_io():
    """写入然后读取一个大文件（100MB）"""
    tmp_file = Path(__file__).parent / "artifacts" / "disk_io_test.bin"
    tmp_file.parent.mkdir(parents=True, exist_ok=True)

    # 写 100 MB
    data = b"x" * (1024 * 1024)  # 1 MB
    with open(tmp_file, "wb") as f:
        for _ in range(100):
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

    # 读回来
    with open(tmp_file, "rb") as f:
        while f.read(1024 * 1024):
            pass

    # 清理
    tmp_file.unlink()


if __name__ == "__main__":
    run_experiment(
        scenario_name="disk_io_spike",
        warmup_seconds=5,
        trigger_fn=trigger_disk_io,
        wait_after_seconds=3,
    )

"""
ETW File Circular Session POC

用 file mode circular 记录关键事件到 .etl 文件，
测试实际 IO 速率（Level=INFORMATION 过滤，不订阅 verbose）。
"""

import sys
import time
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.etw.session import EtwFileSession
from config import ETW_LEVEL
from src.etw.providers import (
    KERNEL_PROCESS, TCPIP, DXGKRNL,
    KERNEL_PROCESSOR_POWER, KERNEL_PNP,
    Keywords,
)

LOG_FILE = PROJECT_ROOT / "log.txt"
ETL_FILE = PROJECT_ROOT / "logs" / "etl" / "keyevents.etl"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")


def main():
    print(f"\n{'='*60}")
    print(f"  ETW File Circular POC (Level={ETW_LEVEL})")
    print(f"  ETL 输出: {ETL_FILE}")
    print(f"{'='*60}\n")

    # 清空旧文件
    if ETL_FILE.exists():
        ETL_FILE.unlink()

    session = EtwFileSession(
        session_name="WinStatusCheckerFile",
        log_file=ETL_FILE,
        max_file_size_mb=500,
    )

    # 每个 provider 单独设置 keyword，过滤掉高频无用事件
    # 元组第 3 个字段：event id 白名单（None = 不做 event id 过滤）
    from config import ETW_EVENT_ID_WHITELIST
    providers = [
        (KERNEL_PROCESS, Keywords.KERNEL_PROCESS, None),
        (TCPIP, Keywords.TCPIP, None),
        (DXGKRNL, Keywords.DXGKRNL, ETW_EVENT_ID_WHITELIST.get("DxgKrnl")),  # 只保留 TDR event
        (KERNEL_PROCESSOR_POWER, Keywords.CPU_POWER, None),
        (KERNEL_PNP, Keywords.PNP, None),
    ]

    if not session.start(providers=providers, level=ETW_LEVEL):
        print("\n  ✗ session 启动失败")
        sys.exit(1)

    print(f"\n  已订阅 {len(providers)} 个 provider")
    print(f"  每 10s 打印一次 IO 统计")
    print(f"  Ctrl+C 停止\n")

    start_time = time.time()
    last_size = 0
    last_time = start_time

    try:
        while True:
            time.sleep(10)
            now = time.time()

            # 读取文件大小
            if ETL_FILE.exists():
                current_size = ETL_FILE.stat().st_size
            else:
                current_size = 0

            elapsed = now - start_time
            interval_bytes = current_size - last_size
            interval_seconds = now - last_time
            interval_kbps = (interval_bytes / 1024) / interval_seconds if interval_seconds > 0 else 0

            avg_kbps = (current_size / 1024) / elapsed if elapsed > 0 else 0

            stats = session.get_stats()

            logger.info(
                f"[T+{elapsed:.0f}s] 文件={current_size/(1024*1024):.1f}MB, "
                f"近10s写入={interval_bytes/1024:.0f}KB ({interval_kbps:.1f}KB/s), "
                f"平均={avg_kbps:.1f}KB/s, "
                f"events_lost={stats.get('events_lost', 'N/A')}"
            )

            last_size = current_size
            last_time = now

    except KeyboardInterrupt:
        pass
    finally:
        session.stop()

        elapsed = time.time() - start_time
        final_size = ETL_FILE.stat().st_size if ETL_FILE.exists() else 0

        print(f"\n{'='*60}")
        print(f"  IO 速率评估")
        print(f"{'='*60}")
        print(f"  运行时长: {elapsed:.0f}s")
        print(f"  最终文件大小: {final_size/(1024*1024):.1f} MB")
        if elapsed > 0 and final_size > 0:
            avg_kbps = (final_size / 1024) / elapsed
            print(f"  平均写入速率: {avg_kbps:.1f} KB/s")
            year_gb = (final_size / elapsed) * 86400 * 365 / (1024**3)
            print(f"  按此速率一年写入: {year_gb:.1f} GB")
            if year_gb > 0:
                years = 300 * 1024 / year_gb
                print(f"  假设 SSD TBW=300TB, 消耗年限: {years:.0f} 年")
        print(f"  ETL 文件: {ETL_FILE}\n")


if __name__ == "__main__":
    main()

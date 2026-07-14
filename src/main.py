"""
win_status_checker 主入口（双 session 架构）

架构:
  Session A (File Circular) → 长期落盘，只订阅关键低频事件（进程崩溃、GPU TDR、
                                                              设备掉线、内存告警等）
                              IO 极低（<50 KB/s），SSD 无感
                              目的：蓝屏/hang 后重启也能从盘上找到"最后发生了什么"

  Session B (Real-Time)     → 广撒网订阅，consumer 线程把事件塞进 Python 内存 deque
                              零磁盘 IO（除 Ctrl+C 时一次性 dump 几十 MB gzip）
                              目的：用户感知卡顿时立即 Ctrl+C，抓最近 30+ 分钟历史

启动后常驻，Ctrl+C 时：
  1. 停止两个 session
  2. dump Realtime consumer 的内存 deque 到 logs/runs/<ts>/snap.bin.gz
  3. File Session 的 .etl 已在 logs/runs/<ts>/keyevents.etl，无需额外操作
"""

import ctypes
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    ETW_LEVEL,
    ETL_MAX_SIZE_MB,
    ETW_KEYWORD_BLACKLIST,
    ETW_EVENT_ID_WHITELIST,
    ETW_FILE_SESSION_PROVIDERS,
    ETW_REALTIME_PROVIDERS,
)
from src.etw import (
    EtwFileSession,
    EtwRealtimeSession,
    EtwConsumer,
    resolve_provider_entries,
)
from src.logging_utils import tee_stdout


# 每次运行的产物统一放到 logs/runs/<timestamp>/ 下
#   - main.log:        运行日志
#   - keyevents.etl:   File Session 的 circular 落盘（关键事件）
#   - snap.bin.gz:     Ctrl+C 时 Realtime consumer 的内存 dump
RUNS_ROOT = PROJECT_ROOT / "logs" / "runs"


def _make_run_dir() -> Path:
    """为本次运行创建带时间戳的目录"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_ROOT / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _setup_logging(log_file: Path):
    """
    把 stdout/stderr tee 到 log 文件（覆盖模式，每次运行独立文件），
    这样 print() 的 banner / 摘要也会被记录。
    """
    tee_stdout(log_file, mode="w", banner=False)
    # logging 也走 tee 后的 stdout
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("main")


def _print_banner(run_dir, etl_file, log_file, file_entries, realtime_entries):
    print(f"\n{'='*70}")
    print(f"  win_status_checker · 双 session 架构")
    print(f"{'='*70}")
    print(f"  本次运行目录: {run_dir}")
    print()
    print(f"  File Session (长期落盘, level={ETW_LEVEL}):")
    print(f"    {etl_file.name}   max={ETL_MAX_SIZE_MB} MB circular")
    print(f"    providers ({len(file_entries)}):")
    for name in ETW_FILE_SESSION_PROVIDERS:
        print(f"      - {name}")
    print()
    print(f"  Realtime Session (Python 内存 deque):")
    print(f"    providers ({len(realtime_entries)}), Ctrl+C 时 dump 到 snap.bin.gz")
    for name in ETW_REALTIME_PROVIDERS:
        print(f"      - {name}")
    print()
    print(f"  监控日志: {log_file.name}")
    print(f"{'='*70}\n")


def _print_stats(logger, file_session, realtime_session, consumer, etl_file, elapsed):
    """定期打印两个 session 的运行统计"""
    # File session 状态
    file_stats = file_session.get_stats()
    file_size_mb = etl_file.stat().st_size / (1024*1024) if etl_file.exists() else 0
    file_lost = file_stats.get("events_lost", "?")

    # Realtime session + consumer 状态
    rt_stats = realtime_session.get_stats()
    rt_lost = rt_stats.get("realtime_buffers_lost", "?") if "error" not in rt_stats else "?"
    c_stats = consumer.snapshot_stats()

    logger.info(
        f"[T+{int(elapsed)}s] "
        f"File: {file_size_mb:.1f}MB, lost={file_lost} | "
        f"Realtime: ring={c_stats['ring_size']:,}/{c_stats['ring_capacity']:,}, "
        f"total={c_stats['total_events']:,}, "
        f"kernel_lost={rt_lost}, ring_dropped={c_stats['dropped_events']}"
    )


def _dump_snapshot(consumer, run_dir: Path, logger):
    """把 Realtime consumer 的内存 deque dump 到本次运行目录"""
    out = run_dir / "snap.bin"

    t0 = time.time()
    event_count, bytes_written = consumer.dump(out, compress=True)
    elapsed = time.time() - t0

    final_path = out.with_suffix(".bin.gz")
    logger.info(
        f"snapshot 已保存: {final_path} "
        f"({event_count:,} events → {bytes_written/(1024*1024):.1f} MB, {elapsed*1000:.0f}ms)"
    )
    return final_path


def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("\n  ✗ 需要管理员权限运行（ETW kernel provider 订阅）\n")
        sys.exit(1)

    # 每次运行独立目录，方便区分和归档
    run_dir = _make_run_dir()
    log_file = run_dir / "main.log"
    etl_file = run_dir / "keyevents.etl"
    logger = _setup_logging(log_file)

    # ---- 准备两组 provider 订阅 ----
    # File Session 需要窄——用 event id 白名单
    file_entries = resolve_provider_entries(
        ETW_FILE_SESSION_PROVIDERS,
        ETW_KEYWORD_BLACKLIST,
        ETW_EVENT_ID_WHITELIST,
    )
    # Realtime Session 广撒网——只做 keyword 过滤，不用 event id 白名单
    # （事件在内存里，白名单错杀反而丢诊断信号）
    realtime_entries = resolve_provider_entries(
        ETW_REALTIME_PROVIDERS,
        ETW_KEYWORD_BLACKLIST,
        event_id_whitelist=None,
    )

    _print_banner(run_dir, etl_file, log_file, file_entries, realtime_entries)

    # ---- Session A: File Circular ----
    file_session = EtwFileSession(
        session_name="WinStatusCheckerFile",
        log_file=etl_file,
        max_file_size_mb=ETL_MAX_SIZE_MB,
    )
    if not file_session.start(providers=file_entries, level=ETW_LEVEL):
        logger.error("File session 启动失败")
        sys.exit(1)

    # ---- Session B: Real-Time ----
    realtime_session = EtwRealtimeSession(
        session_name="WinStatusCheckerRealtime",
    )
    if not realtime_session.start(providers=realtime_entries, level=ETW_LEVEL):
        logger.error("Realtime session 启动失败")
        file_session.stop()
        sys.exit(1)

    # 起 consumer 线程消费 Realtime 事件
    consumer = EtwConsumer(
        session_name="WinStatusCheckerRealtime",
        ring_capacity=1_000_000,
    )
    consumer.start()

    print(f"\n监控已启动，Ctrl+C 停止并生成 snapshot\n")

    # ---- 主循环 ----
    start_time = time.time()
    last_stats_time = start_time
    try:
        while True:
            time.sleep(1)
            now = time.time()
            if now - last_stats_time >= 30:
                _print_stats(logger, file_session, realtime_session,
                             consumer, etl_file, now - start_time)
                last_stats_time = now
    except KeyboardInterrupt:
        print("\n\n收到 Ctrl+C，正在收尾...")

    # ---- 收尾 ----
    print("停止 Realtime session...")
    realtime_session.stop()
    consumer.stop(timeout=5.0)

    print("停止 File session...")
    file_session.stop()

    # dump 内存快照
    print("dump 内存 snapshot 到磁盘...")
    snap_path = _dump_snapshot(consumer, run_dir, logger)

    # 摘要
    elapsed = time.time() - start_time
    file_size = etl_file.stat().st_size if etl_file.exists() else 0
    c_stats = consumer.snapshot_stats()

    print(f"\n{'='*70}")
    print(f"  运行摘要")
    print(f"{'='*70}")
    print(f"  运行时长:          {elapsed/60:.1f} 分钟 ({elapsed:.0f}s)")
    print(f"  产物目录:          {run_dir}")
    print()
    print(f"  File Session (长期落盘):")
    print(f"    路径:            {etl_file.name}")
    print(f"    大小:            {file_size/(1024*1024):.1f} MB")
    if elapsed > 0:
        print(f"    平均字节率:      {file_size/1024/elapsed:.1f} KB/s")
    print()
    print(f"  Realtime Snapshot (内存 dump):")
    print(f"    路径:            {snap_path.name}")
    print(f"    事件数:          {c_stats['total_events']:,}")
    if elapsed > 0:
        print(f"    平均事件率:      {c_stats['total_events']/elapsed:.0f} events/s")
    print(f"    ring 满溢丢弃:   {c_stats['dropped_events']}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()

"""
win_status_checker 主入口（双 session 架构）

架构:
  Session A (File Circular)  → 长期落盘，只订阅关键低频事件
                                （进程崩溃/GPU TDR/设备掉线/内存告警/网络断开）
                                IO 极低（<50 KB/s），SSD 无感
                                目的：蓝屏/hang 后重启也能从盘上找到"最后发生了什么"

  Session B (Buffering Mode) → 广撒网订阅，事件只在 kernel 内存环形 buffer 里循环
                                平时零磁盘 IO
                                Ctrl+C 时 ControlTraceW(FLUSH)+LogFileNameOffset
                                一次性把 buffer 写成合法 .etl 文件 → WPA 直接可开
                                目的：用户感知卡顿时立即 Ctrl+C，拿到最近几十分钟历史

产物: logs/runs/<YYYYMMDD_HHMMSS>/
  - main.log        运行日志
  - keyevents.etl   File Session 的 circular 落盘（关键事件）
  - snap.etl        Ctrl+C 时 Buffer Session flush 的内存快照（合法 ETL）
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
    ETW_BUFFER_SIZE_MB,
    ETW_KEYWORD_BLACKLIST,
    ETW_EVENT_ID_WHITELIST,
    ETW_FILE_SESSION_PROVIDERS,
    ETW_REALTIME_PROVIDERS,
)
from src.etw import (
    EtwFileSession,
    EtwBufferSession,
    resolve_provider_entries,
)
from src.logging_utils import tee_stdout


# 每次运行的产物统一放到 logs/runs/<timestamp>/ 下
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("main")


def _print_banner(run_dir, etl_file, snap_file, log_file, file_entries, buffer_entries):
    print(f"\n{'='*70}")
    print(f"  win_status_checker · 双 session 架构")
    print(f"{'='*70}")
    print(f"  本次运行目录: {run_dir}")
    print()
    print(f"  Session A · File Circular (关键事件长期落盘, level={ETW_LEVEL}):")
    print(f"    {etl_file.name}   max={ETL_MAX_SIZE_MB} MB circular")
    print(f"    providers ({len(file_entries)}):")
    for name in ETW_FILE_SESSION_PROVIDERS:
        print(f"      - {name}")
    print()
    print(f"  Session B · Buffering (内存环形, {ETW_BUFFER_SIZE_MB} MB, 零 IO):")
    print(f"    providers ({len(buffer_entries)}), Ctrl+C 时 flush 到 {snap_file.name}")
    for name in ETW_REALTIME_PROVIDERS:
        print(f"      - {name}")
    print()
    print(f"  监控日志: {log_file.name}")
    print(f"{'='*70}\n")


def _print_stats(logger, file_session, buffer_session, etl_file, elapsed):
    """定期打印两个 session 的运行统计"""
    # File session 状态
    file_stats = file_session.get_stats()
    file_size_mb = etl_file.stat().st_size / (1024*1024) if etl_file.exists() else 0
    file_lost = file_stats.get("events_lost", "?")

    # Buffer session 状态
    buf_stats = buffer_session.get_stats()
    if "error" in buf_stats:
        buf_desc = f"query err={buf_stats['error']}"
    else:
        used = buf_stats["number_of_buffers"] - buf_stats["free_buffers"]
        buf_desc = (
            f"buffers={used}/{buf_stats['number_of_buffers']}, "
            f"lost={buf_stats['events_lost']}"
        )

    logger.info(
        f"[T+{int(elapsed)}s] "
        f"File: {file_size_mb:.1f}MB, lost={file_lost} | "
        f"Buffer: {buf_desc}"
    )


def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("\n  ✗ 需要管理员权限运行（ETW kernel provider 订阅）\n")
        sys.exit(1)

    # 每次运行独立目录，方便区分和归档
    run_dir = _make_run_dir()
    log_file = run_dir / "main.log"
    etl_file = run_dir / "keyevents.etl"
    snap_file = run_dir / "snap.etl"
    logger = _setup_logging(log_file)

    # ---- 准备两组 provider 订阅 ----
    # File Session 窄——用 event id 白名单
    file_entries = resolve_provider_entries(
        ETW_FILE_SESSION_PROVIDERS,
        ETW_KEYWORD_BLACKLIST,
        ETW_EVENT_ID_WHITELIST,
    )
    # Buffer Session 广撒网——只做 keyword 过滤，不用 event id 白名单
    # （事件在内存里，白名单错杀反而丢诊断信号）
    buffer_entries = resolve_provider_entries(
        ETW_REALTIME_PROVIDERS,
        ETW_KEYWORD_BLACKLIST,
        event_id_whitelist=None,
    )

    _print_banner(run_dir, etl_file, snap_file, log_file, file_entries, buffer_entries)

    # ---- Session A: File Circular ----
    file_session = EtwFileSession(
        session_name="WinStatusCheckerFile",
        log_file=etl_file,
        max_file_size_mb=ETL_MAX_SIZE_MB,
    )
    if not file_session.start(providers=file_entries, level=ETW_LEVEL):
        logger.error("File session 启动失败")
        sys.exit(1)

    # ---- Session B: Buffering ----
    buffer_session = EtwBufferSession(
        session_name="WinStatusCheckerBuffer",
        buffer_size_mb=ETW_BUFFER_SIZE_MB,
    )
    if not buffer_session.start(providers=buffer_entries, level=ETW_LEVEL):
        logger.error("Buffer session 启动失败")
        file_session.stop()
        sys.exit(1)

    print(f"\n监控已启动，Ctrl+C 停止并 flush 内存 buffer 到 {snap_file.name}\n")

    # ---- 主循环 ----
    start_time = time.time()
    last_stats_time = start_time
    try:
        while True:
            time.sleep(1)
            now = time.time()
            if now - last_stats_time >= 30:
                _print_stats(logger, file_session, buffer_session,
                             etl_file, now - start_time)
                last_stats_time = now
    except KeyboardInterrupt:
        print("\n\n收到 Ctrl+C，正在收尾...")

    # ---- 收尾 ----
    # 先 flush buffer session（此时 session 还在跑，内核 buffer 里的事件最全）
    print(f"flush buffer session 到 {snap_file.name}...")
    t0 = time.time()
    ok, code = buffer_session.flush_to_etl(snap_file)
    flush_ms = (time.time() - t0) * 1000
    if ok:
        size_mb = snap_file.stat().st_size / (1024*1024) if snap_file.exists() else 0
        logger.info(f"flush 成功: {snap_file.name} ({size_mb:.1f} MB, {flush_ms:.0f}ms)")
    else:
        logger.error(f"flush 失败, 错误码 {code}")

    print("停止 Buffer session...")
    buffer_session.stop()

    print("停止 File session...")
    file_session.stop()

    # 摘要
    elapsed = time.time() - start_time
    file_size = etl_file.stat().st_size if etl_file.exists() else 0
    snap_size = snap_file.stat().st_size if snap_file.exists() else 0

    print(f"\n{'='*70}")
    print(f"  运行摘要")
    print(f"{'='*70}")
    print(f"  运行时长:          {elapsed/60:.1f} 分钟 ({elapsed:.0f}s)")
    print(f"  产物目录:          {run_dir}")
    print()
    print(f"  Session A (关键事件长期落盘):")
    print(f"    路径:            {etl_file.name}")
    print(f"    大小:            {file_size/(1024*1024):.1f} MB")
    if elapsed > 0:
        print(f"    平均字节率:      {file_size/1024/elapsed:.1f} KB/s")
    print()
    print(f"  Session B (Ctrl+C flush 快照):")
    print(f"    路径:            {snap_file.name}")
    print(f"    大小:            {snap_size/(1024*1024):.1f} MB")
    print(f"    flush 耗时:      {flush_ms:.0f}ms")
    print()
    print(f"  用 WPA 打开:")
    print(f"    wpa.exe \"{snap_file}\"")
    print(f"    wpa.exe \"{etl_file}\"")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()

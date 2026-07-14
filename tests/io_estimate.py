"""
IO 速率评估工具

目标：广撒网订阅所有候选 provider，跑一段时间看：
  - 平均事件率 (events/s)
  - 平均字节率 (KB/s)
  - 给定 buffer 大小下，可覆盖的历史时间窗口

用途：决定"事后重建"场景需要多大的环形 buffer，
以及哪些 provider 事件率过高需要加过滤。

用法（需要管理员）:
    python tests/io_estimate.py               # 5 分钟
    python tests/io_estimate.py --duration 60 # 自定义时长（秒）
    python tests/io_estimate.py --level 4     # 自定义 Level (默认 3=Warning)
    python tests/io_estimate.py --no-filter   # 不套 config 里的黑名单
"""

import argparse
import ctypes
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.logging_utils import tee_stdout
from src.etw.session import EtwFileSession
from src.etw.providers import (
    # 主 config 里已有的
    KERNEL_PROCESS, TCPIP, DXGKRNL,
    KERNEL_PROCESSOR_POWER, KERNEL_PNP,
    KERNEL_DISK_NEW, KERNEL_MEMORY,
    # 新增候选
    USB_USBPORT, USB_USBHUB3, USB_USBXHCI,
    BTH_PORT, BTH_USB,
    INPUT_HIDCLASS,
    KERNEL_AUDIO, KERNEL_POWER,
)
from config import ETW_KEYWORD_BLACKLIST, ETW_EVENT_ID_WHITELIST


ALL_KEYWORDS = 0xFFFFFFFFFFFFFFFF

# 每个 provider 附带一个显示名，方便报告
CANDIDATES = [
    (KERNEL_PROCESS,         "Kernel-Process"),
    (TCPIP,                  "TCPIP"),
    (DXGKRNL,                "DxgKrnl"),
    (KERNEL_PROCESSOR_POWER, "CPU-Power"),
    (KERNEL_PNP,             "Kernel-PnP"),
    (KERNEL_DISK_NEW,        "Kernel-Disk"),
    (KERNEL_MEMORY,          "Kernel-Memory"),
    # ---- 新增 ----
    (USB_USBPORT,            "USB-USBPORT"),
    (USB_USBHUB3,            "USB-USBHUB3"),
    (USB_USBXHCI,            "USB-USBXHCI"),
    (BTH_PORT,               "BTH-BTHPORT"),
    (BTH_USB,                "BTH-BTHUSB"),
    (INPUT_HIDCLASS,         "Input-HIDCLASS"),
    (KERNEL_AUDIO,           "Kernel-Audio"),
    (KERNEL_POWER,           "Kernel-Power"),
]


def build_provider_entries(apply_filters: bool, level: int):
    """
    构造 [(guid, keyword, event_id_whitelist), ...] 供 EtwFileSession.start 使用。
    apply_filters=False 时全订阅（用来看未过滤的原始 IO）。
    """
    entries = []
    for guid, name in CANDIDATES:
        if apply_filters:
            blacklist = ETW_KEYWORD_BLACKLIST.get(name, [])
            excluded = 0
            for kw, _, _ in blacklist:
                excluded |= kw
            keyword = ALL_KEYWORDS & (~excluded) & 0xFFFFFFFFFFFFFFFF
            eid_whitelist = ETW_EVENT_ID_WHITELIST.get(name)
        else:
            keyword = ALL_KEYWORDS
            eid_whitelist = None
        entries.append((guid, keyword, eid_whitelist))
    return entries


def format_kb(n):
    return f"{n/1024:.1f}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=300,
                        help="采集时长（秒），默认 300 = 5 分钟")
    parser.add_argument("--level", type=int, default=4,
                        help="ETW Level (1=Critical .. 5=Verbose)，默认 4=Information；"
                             "正常运行事件多是 Info 级，Warning 及以上只在故障时才发")
    parser.add_argument("--no-filter", action="store_true",
                        help="不套 config 里的黑/白名单，全订阅（看原始压力）")
    parser.add_argument("--output-dir", default="logs/io_estimate",
                        help="ETL 输出目录")
    args = parser.parse_args()

    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("✗ 需要管理员权限")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 重定向 stdout + stderr 到日志文件，方便离线查看
    tee_stdout(output_dir / "io_estimate.log")

    # INFO 级别，能看到 session 启动时"订阅 X/Y 个"的日志
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        stream=sys.stdout)
    etl_path = output_dir / "io_estimate.etl"
    if etl_path.exists():
        etl_path.unlink()

    apply_filters = not args.no_filter
    entries = build_provider_entries(apply_filters=apply_filters, level=args.level)

    print(f"\n{'='*70}")
    print(f"  IO 评估")
    print(f"{'='*70}")
    print(f"  订阅 provider:  {len(entries)} 个")
    for guid, name in CANDIDATES:
        marker = "  已有 " if any(guid.Data1 == g.Data1
                                  for g, _ in CANDIDATES[:7]) else "  新增 "
        blacklist_size = len(ETW_KEYWORD_BLACKLIST.get(name, []))
        whitelist_size = len(ETW_EVENT_ID_WHITELIST.get(name, []) or [])
        info = ""
        if apply_filters:
            info = f"kw 黑名单={blacklist_size} 项, id 白名单={whitelist_size} 项"
        print(f"   {marker} {name:<20} {info}")
    print(f"  Level:          {args.level}")
    print(f"  过滤:           {'套 config 黑白名单' if apply_filters else '全订阅（无过滤）'}")
    print(f"  时长:           {args.duration}s")
    print(f"  输出:           {etl_path}")

    session = EtwFileSession(
        session_name="WinStatusCheckerIOEstimate",
        log_file=etl_path,
        max_file_size_mb=5000,   # 5GB 上限，防止 5 分钟就绕回来
    )
    if not session.start(providers=entries, level=args.level):
        print("✗ session 启动失败")
        sys.exit(1)

    # 立刻打印一次 session 统计确认订阅生效
    time.sleep(1)
    initial = session.get_stats()
    print(f"\n启动后 1s 的 session 统计: {initial}")
    if "error" in initial:
        print(f"⚠  get_stats 返回错误 {initial['error']}，可能 session 状态异常")

    # 每 30 秒打印一次
    start = time.time()
    last_size = 0
    print(f"\n{'时间':<8} {'累计':<12} {'近 30s':<14} {'平均速率':<14} {'buffers_written':<18} {'events_lost'}")
    print(f"{'-'*8} {'-'*12} {'-'*14} {'-'*14} {'-'*18} {'-'*12}")

    try:
        while True:
            elapsed = time.time() - start
            if elapsed >= args.duration:
                break
            time.sleep(min(30, args.duration - elapsed))

            elapsed = time.time() - start
            size = etl_path.stat().st_size if etl_path.exists() else 0
            delta = size - last_size
            avg_rate = size / elapsed if elapsed > 0 else 0
            stats = session.get_stats()
            lost = stats.get("events_lost", "?")
            written = stats.get("buffers_written", "?")

            print(f"T+{int(elapsed):>4}s  "
                  f"{size/(1024*1024):>7.1f} MB  "
                  f"{delta/1024:>7.0f} KB/30s  "
                  f"{avg_rate/1024:>7.0f} KB/s     "
                  f"{str(written):<18} "
                  f"{lost}")
            last_size = size
    except KeyboardInterrupt:
        print("\n中断，正在停止 session...")

    session.stop()

    # 最终统计
    total_bytes = etl_path.stat().st_size
    total_sec = time.time() - start
    avg_bytes_per_sec = total_bytes / total_sec

    print(f"\n{'='*70}")
    print(f"  评估结果")
    print(f"{'='*70}")
    print(f"  运行时长:       {total_sec:.0f}s")
    print(f"  总写入:         {total_bytes/(1024*1024):.1f} MB")
    print(f"  平均字节率:     {avg_bytes_per_sec/1024:.1f} KB/s")
    print(f"  按年估算:       {avg_bytes_per_sec * 86400 * 365 / (1024**4):.2f} TB/年")
    print(f"  典型 SSD TBW:   300 TB → 消耗年限 "
          f"{300 / max(avg_bytes_per_sec * 86400 * 365 / (1024**4), 0.001):.0f} 年")
    print()
    print(f"  【环形 buffer 可覆盖时间窗口】")
    for buf_mb in (100, 500, 1024, 2048, 5120):
        cover_sec = buf_mb * 1024 * 1024 / max(avg_bytes_per_sec, 1)
        print(f"    buffer={buf_mb:>5} MB → 可覆盖 "
              f"{cover_sec/60:6.1f} 分钟  "
              f"({cover_sec:6.0f} 秒)")

    print(f"\n  分析事件分布 (需要几秒):")
    print(f"    python tests/filter_validation/analyze.py  # 结构类似")
    print(f"  或直接:")
    print(f"    tracerpt {etl_path} -summary summary.txt -y")


if __name__ == "__main__":
    main()

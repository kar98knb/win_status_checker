"""
分析 main.py Ctrl+C 时生成的 snapshot 文件（logs/runs/<ts>/snap.bin.gz）

用法（不需要管理员）:
    python -m src.analyze_snapshot                       # 分析最新一次运行的 snapshot
    python -m src.analyze_snapshot <path/to/snap.bin.gz>
    python -m src.analyze_snapshot --list                # 列出所有 run 目录

输出:
    - 事件总数、时间跨度、平均事件率
    - Top 15 provider（按事件计数）
    - 每个 provider 的 top event id
    - 可能的异常信号（Level=Error/Critical 的事件）
"""

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.etw import read_dump, unpack_event
from src.etw.provider_registry import PROVIDER_GUIDS


PROJECT_ROOT = Path(__file__).parent.parent
RUNS_ROOT = PROJECT_ROOT / "logs" / "runs"


# GUID 字节 → 短名字
_GUID_TO_NAME = {}
for name, guid in PROVIDER_GUIDS.items():
    import ctypes
    guid_bytes = bytes(ctypes.string_at(ctypes.byref(guid), 16))
    _GUID_TO_NAME[guid_bytes] = name


LEVEL_NAMES = {
    0: "LogAlways",
    1: "Critical",
    2: "Error",
    3: "Warning",
    4: "Information",
    5: "Verbose",
}


def _list_snapshots():
    if not RUNS_ROOT.exists():
        print(f"{RUNS_ROOT} 目录不存在")
        return
    snaps = sorted(RUNS_ROOT.glob("*/snap.bin.gz"))
    if not snaps:
        print("没找到 snapshot")
        return
    print(f"共 {len(snaps)} 次运行的 snapshot:\n")
    for p in snaps:
        size_mb = p.stat().st_size / (1024*1024)
        ts = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {p.parent.name}/snap.bin.gz  {size_mb:>6.1f} MB   {ts}")


def analyze(snap_path: Path):
    print(f"\n{'='*70}")
    print(f"  分析: {snap_path.name}")
    print(f"{'='*70}")

    total = 0
    by_provider = Counter()
    by_event = defaultdict(Counter)   # {provider: Counter(event_id)}
    by_level = Counter()
    first_ts = None
    last_ts = None
    error_events = []   # [(ts, provider_name, event_id, level), ...]

    for raw in read_dump(snap_path):
        ev = unpack_event(raw)
        total += 1
        ts = ev["timestamp"]
        # 有些事件（比如 session 头）timestamp=0，跳过用于时间统计
        if ts > 0:
            if first_ts is None:
                first_ts = ts
            last_ts = ts

        # provider_guid 是 hex string，转回 bytes 找名字
        guid_hex = ev["provider_guid"]
        guid_bytes = bytes.fromhex(guid_hex)
        prov_name = _GUID_TO_NAME.get(guid_bytes, f"unknown({guid_hex[:8]}...)")

        by_provider[prov_name] += 1
        by_event[prov_name][ev["event_id"]] += 1
        by_level[ev["level"]] += 1

        # Level 1 (Critical) / 2 (Error) 收集起来单独列出
        if ev["level"] in (1, 2) and prov_name != f"unknown({guid_hex[:8]}...)":
            error_events.append((ts, prov_name, ev["event_id"], ev["level"]))

    print(f"\n事件总数: {total:,}")

    # 时间跨度（ETW timestamp 是 100ns since 1601-01-01）
    if first_ts and last_ts and first_ts != last_ts:
        span_100ns = last_ts - first_ts
        span_sec = span_100ns / 10_000_000
        print(f"时间跨度: {span_sec:.1f} 秒 ({span_sec/60:.1f} 分钟)")
        print(f"平均事件率: {total/span_sec:.0f} events/s")
        # ETW timestamp 转 datetime
        epoch_diff = 11644473600  # seconds between 1601-01-01 and 1970-01-01
        first_dt = datetime.fromtimestamp(first_ts / 10_000_000 - epoch_diff)
        last_dt = datetime.fromtimestamp(last_ts / 10_000_000 - epoch_diff)
        print(f"首个事件: {first_dt.strftime('%H:%M:%S.%f')[:-3]}")
        print(f"末个事件: {last_dt.strftime('%H:%M:%S.%f')[:-3]}")

    # ==== Level 分布 ====
    print(f"\n按 Level 分布:")
    for level in sorted(by_level):
        name = LEVEL_NAMES.get(level, f"Level {level}")
        print(f"  {name:<15} {by_level[level]:>10,}")

    # ==== Provider 分布 ====
    print(f"\nTop Provider (按事件数):")
    print(f"  {'Provider':<20} {'Count':<12} {'%'}")
    print(f"  {'-'*20} {'-'*12} {'-'*6}")
    for name, cnt in by_provider.most_common(15):
        pct = 100*cnt/total if total else 0
        print(f"  {name:<20} {cnt:<12,} {pct:5.1f}%")

    # ==== 每个 provider 的 top event id ====
    print(f"\n每个 provider 最多的 event id:")
    for name, _ in by_provider.most_common(10):
        top_events = by_event[name].most_common(3)
        events_str = ", ".join(f"id={eid}:{cnt}" for eid, cnt in top_events)
        print(f"  {name:<20} {events_str}")

    # ==== Error / Critical 事件 ====
    if error_events:
        print(f"\n⚠  Critical/Error 级别事件 (共 {len(error_events)} 个):")
        print(f"  {'Provider':<20} {'ID':<6} {'Level'}")
        print(f"  {'-'*20} {'-'*6} {'-'*8}")
        for _ts, prov, eid, level in error_events[:20]:
            print(f"  {prov:<20} {eid:<6} {LEVEL_NAMES.get(level, '?')}")
        if len(error_events) > 20:
            print(f"  ...还有 {len(error_events)-20} 个")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?",
                        help="snapshot 路径，省略则分析最新一份")
    parser.add_argument("--list", action="store_true", help="列出所有 snapshot")
    args = parser.parse_args()

    if args.list:
        _list_snapshots()
        return

    if args.path:
        target = Path(args.path)
        if not target.exists():
            print(f"✗ 文件不存在: {target}")
            sys.exit(1)
    else:
        snaps = list(RUNS_ROOT.glob("*/snap.bin.gz")) if RUNS_ROOT.exists() else []
        if not snaps:
            print(f"✗ {RUNS_ROOT} 里没找到 snapshot")
            print(f"  先跑 python run.py 采集，Ctrl+C 生成 snapshot")
            sys.exit(1)
        target = max(snaps, key=lambda p: p.stat().st_mtime)
        print(f"分析最新 snapshot: {target.parent.name}/snap.bin.gz")

    analyze(target)


if __name__ == "__main__":
    main()

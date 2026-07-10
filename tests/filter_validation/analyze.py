"""
分析 filter_validation 实验结果

用 tracerpt.exe 生成的 report XML 拿到准确的事件统计。
纯本地文件解析，不需要管理员权限。

用法:
    python tests/filter_validation/analyze.py
"""

import sys
import subprocess
from pathlib import Path
from collections import defaultdict
from xml.etree import ElementTree as ET


ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

# Provider GUID → 简短名字映射
PROVIDER_NAMES = {
    "{22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}": "Kernel-Process",
    "{2f07e2ee-15db-40f1-90ef-9d7ba282188a}": "TCPIP",
    "{802ec45a-1e99-4b83-9920-87c98277ba9d}": "DxgKrnl",
    "{0f67e49f-fe51-4e9f-b490-6f2948cc6027}": "CPU-Power",
    "{9c205a39-1250-487d-abd7-e831c6290539}": "Kernel-PnP",
    "{68fdd900-4a3e-11d1-84f4-0000f80464e3}": "EventTrace",  # 系统内部
}


def run_tracerpt(etl_file: Path) -> Path:
    """
    调 tracerpt 生成 report XML（只是统计，不是事件转储，很小）。
    返回 report XML 路径。
    """
    report_xml = etl_file.parent / (etl_file.stem + ".report.xml")
    summary_txt = etl_file.parent / (etl_file.stem + ".summary.txt")

    # tracerpt 会生成一个大 dumpfile.xml，我们不需要它，指定到临时位置
    dump_placeholder = etl_file.parent / (etl_file.stem + ".__dump__.xml")

    result = subprocess.run(
        [
            "tracerpt.exe",
            str(etl_file),
            "-summary", str(summary_txt),
            "-report", str(report_xml),
            "-o", str(dump_placeholder),
            "-y",
        ],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # 删掉不需要的大 dump 文件
    if dump_placeholder.exists():
        try:
            dump_placeholder.unlink()
        except Exception:
            pass

    if not report_xml.exists():
        print(f"    tracerpt stderr: {result.stderr[:200]}")
        print(f"    tracerpt stdout: {result.stdout[:200]}")
        return None
    return report_xml


def parse_report(report_xml: Path):
    """
    解析 tracerpt report XML，返回:
        total_events: 总事件数
        by_event: {(provider_guid, event_id): (event_name, count)}
    """
    total_events = 0
    by_event = {}

    # tracerpt XML 使用 UTF-16
    try:
        content = report_xml.read_text(encoding="utf-16")
    except (UnicodeError, UnicodeDecodeError):
        content = report_xml.read_text(encoding="utf-8", errors="replace")

    # 用 ElementTree 解析
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        print(f"  XML 解析失败: {e}")
        return 0, {}

    # 找 <Data name="events"> 拿总数
    for data in root.iter("Data"):
        if data.get("name") == "events":
            try:
                total_events = int(data.text or 0)
                break
            except (ValueError, TypeError):
                pass

    # 找 events 表里的每一项
    for section in root.iter("Section"):
        for table in section.iter("Table"):
            if table.get("name") != "events":
                continue
            for item in table.iter("Item"):
                event_data = {}
                for data in item.iter("Data"):
                    name = data.get("name")
                    text = (data.text or "").strip()
                    event_data[name] = text
                guid = event_data.get("payloadGuid", "").lower()
                event_id = event_data.get("payloadId", "")
                event_name = event_data.get("event", "")
                opcode = event_data.get("opcode", "")
                count_str = event_data.get("count", "0")
                try:
                    count = int(count_str)
                except (ValueError, TypeError):
                    count = 0
                key = (guid, event_id)
                full_name = f"{event_name}/{opcode}" if opcode else event_name
                by_event[key] = (full_name, count)

    return total_events, by_event


def format_provider(guid: str) -> str:
    """GUID → 短名字"""
    return PROVIDER_NAMES.get(guid, guid)


def compare_scenario(scenario: str):
    scenario_dir = ARTIFACTS_DIR / scenario
    full_etl = scenario_dir / "full.etl"
    filtered_etl = scenario_dir / "filtered.etl"

    if not full_etl.exists() or not filtered_etl.exists():
        print(f"[{scenario}] 缺少 .etl 文件")
        return

    print(f"\n{'='*80}")
    print(f"  场景: {scenario}")
    print(f"{'='*80}")

    # 生成 report XML
    full_report = run_tracerpt(full_etl)
    filt_report = run_tracerpt(filtered_etl)

    if not full_report or not filt_report:
        print(f"  ✗ tracerpt 失败")
        return

    full_total, full_events = parse_report(full_report)
    filt_total, filt_events = parse_report(filt_report)

    reduction = 100 * (1 - filt_total / full_total) if full_total > 0 else 0
    print(f"\n  full 总事件:     {full_total:>8}")
    print(f"  filtered 总事件: {filt_total:>8}   (减少 {reduction:.1f}%)")

    # 被过滤掉最多的事件
    filtered_out = []
    for key, (name, count) in full_events.items():
        f_count = filt_events.get(key, (name, 0))[1]
        if f_count < count:
            filtered_out.append((key, name, count - f_count, count))
    filtered_out.sort(key=lambda x: -x[2])

    if filtered_out:
        print(f"\n  被过滤掉最多的事件 (top 15):")
        print(f"  {'Provider':<20} {'ID':<6} {'Event':<40} {'Removed':<10} {'原总数'}")
        print(f"  {'-'*20} {'-'*6} {'-'*40} {'-'*10} {'-'*8}")
        for (guid, eid), name, removed, total in filtered_out[:15]:
            prov = format_provider(guid)[:20]
            print(f"  {prov:<20} {eid:<6} {name[:40]:<40} {removed:<10} {total}")

    # filtered 里保留最多的
    top_kept = sorted(filt_events.items(), key=lambda x: -x[1][1])[:10]
    if top_kept:
        print(f"\n  filtered 里最多的事件 (top 10):")
        print(f"  {'Provider':<20} {'ID':<6} {'Event':<40} {'Count'}")
        print(f"  {'-'*20} {'-'*6} {'-'*40} {'-'*8}")
        for (guid, eid), (name, count) in top_kept:
            prov = format_provider(guid)[:20]
            print(f"  {prov:<20} {eid:<6} {name[:40]:<40} {count}")


def main():
    if not ARTIFACTS_DIR.exists():
        print("artifacts/ 不存在，请先跑 filter_validation 实验")
        sys.exit(1)

    scenarios = [d.name for d in ARTIFACTS_DIR.iterdir() if d.is_dir()]
    scenarios.sort()

    for scenario in scenarios:
        compare_scenario(scenario)


if __name__ == "__main__":
    main()

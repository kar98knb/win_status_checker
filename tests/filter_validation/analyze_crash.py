"""
从 process_crash 场景的 filtered.etl 提取 Kernel-Process STOP 事件的 ExitCode，
证明"进程崩溃"事件在过滤后依然可辨识。

不需要管理员权限（纯本地解析）。

用法:
    python tests/filter_validation/analyze_crash.py
"""

import json
import sys
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET


ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
SCENARIO_DIR = ARTIFACTS_DIR / "process_crash"

# NT status → 含义（常见值）
NT_STATUS_NAMES = {
    0x00000000: "STATUS_SUCCESS",
    0x00000001: "Python uncaught exception / exit(1)",
    0xC0000005: "STATUS_ACCESS_VIOLATION",
    0xC0000094: "STATUS_INTEGER_DIVIDE_BY_ZERO",
    0xC00000FD: "STATUS_STACK_OVERFLOW",
    0xC000013A: "STATUS_CONTROL_C_EXIT",
    0xC0000135: "STATUS_DLL_NOT_FOUND",
    0xC0000142: "STATUS_DLL_INIT_FAILED",
    0xC0000409: "STATUS_STACK_BUFFER_OVERRUN",
    0xC0000374: "STATUS_HEAP_CORRUPTION",
}

# Kernel-Process provider GUID (小写)
KERNEL_PROCESS_GUID = "{22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}"


def is_crash_status(status: int) -> bool:
    """NT status 高两位 0b11 表示 SEVERITY_ERROR，即崩溃"""
    return (status & 0xC0000000) == 0xC0000000


def status_name(status: int) -> str:
    if status in NT_STATUS_NAMES:
        return NT_STATUS_NAMES[status]
    if is_crash_status(status):
        return "unknown crash (severity=ERROR)"
    if status == 0:
        return "normal exit"
    return f"exit code 0x{status:08X}"


def dump_etl_to_xml(etl: Path) -> Path:
    """
    调 tracerpt 生成完整事件 XML（含 payload）。
    """
    out_xml = etl.parent / (etl.stem + ".events.xml")
    if out_xml.exists():
        out_xml.unlink()

    proc = subprocess.run(
        [
            "tracerpt.exe",
            str(etl),
            "-o", str(out_xml),
            "-of", "XML",
            "-y",
        ],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    if not out_xml.exists():
        print(f"  tracerpt 失败:")
        print(f"    stderr: {proc.stderr[:300]}")
        print(f"    stdout: {proc.stdout[:300]}")
        return None
    return out_xml


def _parse_int(text: str):
    """解析 XML payload 里的整数字段（十进制或 0x 十六进制）"""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        if text.lower().startswith("0x"):
            return int(text, 16)
        return int(text) & 0xFFFFFFFF
    except (ValueError, TypeError):
        return None


def _iter_events(root):
    """遍历所有 Event，产出 (provider_guid_lower, event_id, event_data_dict)"""
    for event in root.iter():
        tag = event.tag.split("}", 1)[-1]
        if tag != "Event":
            continue

        provider_guid = None
        event_id = None
        event_data = {}

        for child in event:
            ctag = child.tag.split("}", 1)[-1]
            if ctag == "System":
                for sub in child:
                    stag = sub.tag.split("}", 1)[-1]
                    if stag == "Provider":
                        provider_guid = (sub.get("Guid") or "").lower()
                    elif stag == "EventID":
                        try:
                            event_id = int(sub.text or 0)
                        except (ValueError, TypeError):
                            pass
            elif ctag == "EventData":
                for data in child:
                    dtag = data.tag.split("}", 1)[-1]
                    if dtag != "Data":
                        continue
                    name = data.get("Name", "")
                    text = (data.text or "").strip()
                    event_data[name] = text

        yield provider_guid, event_id, event_data


def extract_process_lifecycle(events_xml: Path):
    """
    从 tracerpt 生成的 XML 中提取 Kernel-Process 的 START/STOP 事件。
    返回:
        starts: {pid: {"image": str, ...}}
        stops:  {pid: {"image": str, "exit_code": int}}
    """
    # tracerpt 生成的 XML 是 UTF-8（虽然文件头没标）
    content = events_xml.read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(content)

    starts = {}
    stops = {}

    for provider_guid, event_id, data in _iter_events(root):
        if provider_guid != KERNEL_PROCESS_GUID:
            continue

        if event_id == 1:  # ProcessStart
            pid = _parse_int(data.get("ProcessID", ""))
            if pid is None:
                continue
            starts[pid] = {
                "image": data.get("ImageName", ""),
                "parent_pid": _parse_int(data.get("ParentProcessID", "")),
            }
        elif event_id == 2:  # ProcessStop
            pid = _parse_int(data.get("ProcessID", ""))
            exit_code = _parse_int(data.get("ExitCode", ""))
            if pid is None or exit_code is None:
                continue
            stops[pid] = {
                "image": data.get("ImageName", ""),
                "exit_code": exit_code,
            }

    return starts, stops


def analyze():
    filtered_etl = SCENARIO_DIR / "filtered.etl"
    pids_file = SCENARIO_DIR / "child_pids.json"

    if not filtered_etl.exists():
        print(f"✗ 找不到 {filtered_etl}")
        print(f"  请先跑: python tests/filter_validation/run_all.py")
        sys.exit(1)

    print("=" * 80)
    print("  process_crash 场景 · STOP 事件 ExitCode 分析（filtered.etl）")
    print("=" * 80)

    child_records = None
    if pids_file.exists():
        child_records = json.loads(pids_file.read_text(encoding="utf-8"))
        print("\n本次实验的子进程 PID (来自 subprocess.Popen.pid):")
        for r in child_records:
            print(f"    {r['label']:<14} pid={r['pid']:<6} "
                  f"exit_code=0x{r['exit_code']:08X} ({status_name(r['exit_code'])})")
    else:
        print(f"\n⚠  没找到 {pids_file.name}（旧版 test 没写这个文件）")
        print(f"   将 fallback 显示所有 python 进程的 STOP 事件。")
        print(f"   建议重跑: python tests/filter_validation/test_process_crash.py")

    print("\n生成事件 XML（可能需要几秒）...")
    events_xml = dump_etl_to_xml(filtered_etl)
    if not events_xml:
        sys.exit(1)

    print(f"解析 {events_xml.name}...")
    starts, stops = extract_process_lifecycle(events_xml)
    print(f"共 {len(starts)} 个 START，{len(stops)} 个 STOP 事件\n")

    child_pids = {r["pid"] for r in child_records} if child_records else set()

    # ==== 按 PID 精确匹配（有 pid 文件时）====
    if child_records:
        print("\nPID 匹配结果:")
        print(f"  {'label':<14} {'pid':<7} {'image':<30} {'ETW ExitCode':<15} 含义")
        print(f"  {'-'*14} {'-'*7} {'-'*30} {'-'*15} {'-'*40}")

        label_status = {}
        for r in child_records:
            label = r["label"]
            pid = r["pid"]
            stop = stops.get(pid)
            if stop is None:
                print(f"  {label:<14} {pid:<7} {'(未找到 STOP)':<30} {'-':<15} filter 过滤过头？")
                label_status[label] = None
                continue
            etw_code = stop["exit_code"]
            image = stop["image"][:30]
            print(f"  {label:<14} {pid:<7} {image:<30} 0x{etw_code:08X}      "
                  f"{status_name(etw_code)}")
            label_status[label] = etw_code

        # ==== 结论 ====
        print(f"\n结论:")
        ok = True
        expected = {
            "clean_exit":   lambda s: s == 0,
            "python_error": lambda s: s != 0 and not is_crash_status(s),
            "hard_crash":   lambda s: is_crash_status(s),
        }
        for label, checker in expected.items():
            status = label_status.get(label)
            if status is None:
                print(f"  ✗ {label}: filtered.etl 里没找到该 PID 的 STOP 事件")
                ok = False
                continue
            if checker(status):
                print(f"  ✓ {label}: ETW 里 ExitCode=0x{status:08X}"
                      f"  → 正确归类为「{status_name(status)}」")
            else:
                print(f"  ✗ {label}: ETW 里 ExitCode=0x{status:08X}"
                      f"，与预期不符（{status_name(status)}）")
                ok = False

        if ok:
            print(
                "\n  过滤后的事件流足以区分【正常退出 / 应用错误 / 硬崩溃】。\n"
                "  main.py 只需要监听 Kernel-Process event id=2 并检查 ExitCode 高两位 == 0b11。"
            )
    else:
        # ==== Fallback：展示所有 STOP 事件（无 pid 文件时）====
        print("\n所有 STOP 事件（按 ExitCode 分组）:")
        print(f"  {'pid':<7} {'image':<40} {'exit code':<12} 含义")
        print(f"  {'-'*7} {'-'*40} {'-'*12} {'-'*40}")
        # 先按是否 crash 排序
        sorted_stops = sorted(
            stops.items(),
            key=lambda kv: (0 if is_crash_status(kv[1]["exit_code"]) else
                            (1 if kv[1]["exit_code"] != 0 else 2)),
        )
        for pid, info in sorted_stops:
            image = (info["image"] or "?")[:40]
            code = info["exit_code"]
            print(f"  {pid:<7} {image:<40} 0x{code:08X}   {status_name(code)}")

    # ==== 背景里其他以错误状态退出的进程 ====
    other_crashes = [
        (pid, info) for pid, info in stops.items()
        if is_crash_status(info["exit_code"]) and pid not in child_pids
    ]
    if other_crashes:
        print(f"\n背景里同时还有 {len(other_crashes)} 个进程以崩溃状态退出:")
        for pid, info in other_crashes[:10]:
            image = (info["image"] or "?")[:60]
            print(f"    pid={pid:<7} {image:<60} status=0x{info['exit_code']:08X}"
                  f" ({status_name(info['exit_code'])})")


if __name__ == "__main__":
    analyze()

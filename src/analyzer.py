"""
历史日志分析模块
list: 列出所有历史会话
analyze: 对比两份会话日志，找出差异和异常
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict

PROJECT_ROOT = Path(__file__).parent.parent
LOG_ROOT = PROJECT_ROOT / "logs"


def list_sessions() -> List[Dict]:
    """列出所有历史会话"""
    sessions = []
    if not LOG_ROOT.exists():
        return sessions

    for item in sorted(LOG_ROOT.iterdir(), reverse=True):
        if not item.is_dir():
            continue
        # 只处理时间戳格式的目录
        try:
            dt = datetime.strptime(item.name, "%Y%m%d_%H%M%S")
        except ValueError:
            continue

        session = {
            "name": item.name,
            "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "path": str(item),
            "has_report": (item / "report.txt").exists(),
            "has_crash_report": (item / "crash_report.json").exists(),
            "modules": [],
        }

        log_dir = item / "log"
        if log_dir.exists():
            session["modules"] = [f.stem for f in log_dir.glob("*.log")]

        sessions.append(session)

    return sessions


def print_sessions():
    """打印历史会话列表"""
    sessions = list_sessions()
    if not sessions:
        print("  无历史会话记录。")
        return

    print(f"\n{'='*60}")
    print(f"  历史会话列表 ({len(sessions)} 个)")
    print(f"{'='*60}\n")
    print(f"  {'序号':<4} {'时间':<20} {'报告':<6} {'崩溃':<6} {'模块'}")
    print(f"  {'─'*4} {'─'*20} {'─'*6} {'─'*6} {'─'*20}")

    for i, s in enumerate(sessions):
        report_mark = "✓" if s["has_report"] else "-"
        crash_mark = "⚠" if s["has_crash_report"] else "-"
        modules = ", ".join(s["modules"][:4]) if s["modules"] else "-"
        print(f"  {i:<4} {s['time']:<20} {report_mark:<6} {crash_mark:<6} {modules}")

    print(f"\n  用法: python run.py --analyze <序号1> <序号2>")
    print(f"  示例: python run.py --analyze 0 1  (对比最近两次会话)\n")


def analyze_sessions(index1: int, index2: int):
    """对比分析两个会话的日志"""
    sessions = list_sessions()

    if index1 >= len(sessions) or index2 >= len(sessions):
        print(f"  错误: 序号超出范围（共 {len(sessions)} 个会话）")
        return

    s1 = sessions[index1]
    s2 = sessions[index2]

    print(f"\n{'='*60}")
    print(f"  对比分析")
    print(f"  会话 A: {s1['time']} ({s1['name']})")
    print(f"  会话 B: {s2['time']} ({s2['name']})")
    print(f"{'='*60}")

    path1 = Path(s1["path"])
    path2 = Path(s2["path"])

    # 对比各模块日志
    _compare_network(path1, path2)
    _compare_system(path1, path2)
    _compare_gpu(path1, path2)
    _compare_drivers(path1, path2)

    # 崩溃报告
    if s1["has_crash_report"]:
        print(f"\n[⚠ 会话 A 有崩溃报告]")
        _print_crash_report(path1 / "crash_report.json")
    if s2["has_crash_report"]:
        print(f"\n[⚠ 会话 B 有崩溃报告]")
        _print_crash_report(path2 / "crash_report.json")

    print(f"\n{'='*60}")


def _parse_log_values(log_path: Path, pattern: str) -> List[float]:
    """从日志文件中提取数值"""
    values = []
    if not log_path.exists():
        return values
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                match = re.search(pattern, line)
                if match:
                    values.append(float(match.group(1)))
    except Exception:
        pass
    return values


def _stats(values: List[float]) -> Dict:
    """计算基本统计"""
    if not values:
        return {"count": 0, "avg": 0, "max": 0, "min": 0}
    return {
        "count": len(values),
        "avg": sum(values) / len(values),
        "max": max(values),
        "min": min(values),
    }


def _compare_network(path1: Path, path2: Path):
    """对比网络日志"""
    print(f"\n[网络对比]")
    log1 = path1 / "log" / "network.log"
    log2 = path2 / "log" / "network.log"

    lat1 = _parse_log_values(log1, r"延迟=([\d.]+)ms")
    lat2 = _parse_log_values(log2, r"延迟=([\d.]+)ms")
    jit1 = _parse_log_values(log1, r"抖动=([\d.]+)ms")
    jit2 = _parse_log_values(log2, r"抖动=([\d.]+)ms")

    s1 = _stats(lat1)
    s2 = _stats(lat2)

    print(f"  {'指标':<10} {'会话A':<20} {'会话B':<20}")
    print(f"  {'─'*10} {'─'*20} {'─'*20}")
    print(f"  {'延迟均值':<10} {s1['avg']:.1f}ms ({s1['count']}条) {'':<3} {s2['avg']:.1f}ms ({s2['count']}条)")
    print(f"  {'延迟最高':<10} {s1['max']:.1f}ms {'':<13} {s2['max']:.1f}ms")

    js1 = _stats(jit1)
    js2 = _stats(jit2)
    print(f"  {'抖动均值':<10} {js1['avg']:.1f}ms {'':<13} {js2['avg']:.1f}ms")
    print(f"  {'抖动最高':<10} {js1['max']:.1f}ms {'':<13} {js2['max']:.1f}ms")

    # 差异判断
    if s1["avg"] > 0 and s2["avg"] > 0:
        diff = abs(s1["avg"] - s2["avg"])
        if diff > 30:
            worse = "A" if s1["avg"] > s2["avg"] else "B"
            print(f"  → 会话 {worse} 延迟明显更高 (差 {diff:.0f}ms)")


def _compare_system(path1: Path, path2: Path):
    """对比系统资源日志"""
    print(f"\n[系统资源对比]")
    log1 = path1 / "log" / "system.log"
    log2 = path2 / "log" / "system.log"

    cpu1 = _parse_log_values(log1, r"CPU=([\d.]+)%")
    cpu2 = _parse_log_values(log2, r"CPU=([\d.]+)%")
    mem1 = _parse_log_values(log1, r"内存=([\d.]+)%")
    mem2 = _parse_log_values(log2, r"内存=([\d.]+)%")

    sc1 = _stats(cpu1)
    sc2 = _stats(cpu2)
    sm1 = _stats(mem1)
    sm2 = _stats(mem2)

    print(f"  {'指标':<10} {'会话A':<20} {'会话B':<20}")
    print(f"  {'─'*10} {'─'*20} {'─'*20}")
    print(f"  {'CPU均值':<10} {sc1['avg']:.1f}% {'':<14} {sc2['avg']:.1f}%")
    print(f"  {'CPU峰值':<10} {sc1['max']:.1f}% {'':<14} {sc2['max']:.1f}%")
    print(f"  {'内存均值':<10} {sm1['avg']:.1f}% {'':<14} {sm2['avg']:.1f}%")
    print(f"  {'内存峰值':<10} {sm1['max']:.1f}% {'':<14} {sm2['max']:.1f}%")

    if sm1["max"] > 90 or sm2["max"] > 90:
        worse = "A" if sm1["max"] > sm2["max"] else "B"
        print(f"  → 会话 {worse} 内存峰值超过 90%，可能有 OOM 风险")


def _compare_gpu(path1: Path, path2: Path):
    """对比 GPU 日志"""
    print(f"\n[GPU对比]")
    log1 = path1 / "log" / "gpu.log"
    log2 = path2 / "log" / "gpu.log"

    usage1 = _parse_log_values(log1, r"使用率=([\d.]+)%")
    usage2 = _parse_log_values(log2, r"使用率=([\d.]+)%")
    temp1 = _parse_log_values(log1, r"温度=([\d.]+)")
    temp2 = _parse_log_values(log2, r"温度=([\d.]+)")

    su1 = _stats(usage1)
    su2 = _stats(usage2)
    st1 = _stats([t for t in temp1 if t > 0])
    st2 = _stats([t for t in temp2 if t > 0])

    print(f"  {'指标':<10} {'会话A':<20} {'会话B':<20}")
    print(f"  {'─'*10} {'─'*20} {'─'*20}")
    print(f"  {'使用率均值':<10} {su1['avg']:.1f}% {'':<14} {su2['avg']:.1f}%")
    print(f"  {'使用率峰值':<10} {su1['max']:.1f}% {'':<14} {su2['max']:.1f}%")
    if st1["count"] > 0 or st2["count"] > 0:
        print(f"  {'温度均值':<10} {st1['avg']:.0f}°C {'':<14} {st2['avg']:.0f}°C")
        print(f"  {'温度峰值':<10} {st1['max']:.0f}°C {'':<14} {st2['max']:.0f}°C")

        if st1["max"] > 85 or st2["max"] > 85:
            worse = "A" if st1["max"] > st2["max"] else "B"
            print(f"  → 会话 {worse} GPU 温度峰值过高，有过热风险")


def _compare_drivers(path1: Path, path2: Path):
    """对比驱动日志"""
    log1 = path1 / "log" / "drivers.log"
    log2 = path2 / "log" / "drivers.log"

    def _count_errors(log_path: Path) -> int:
        if not log_path.exists():
            return 0
        count = 0
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "OK=False" in line:
                        count += 1
        except Exception:
            pass
        return count

    e1 = _count_errors(log1)
    e2 = _count_errors(log2)

    if e1 > 0 or e2 > 0:
        print(f"\n[驱动异常对比]")
        print(f"  会话 A 驱动异常次数: {e1}")
        print(f"  会话 B 驱动异常次数: {e2}")


def _print_crash_report(path: Path):
    """打印崩溃报告摘要"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        print(f"    结论: {data.get('conclusion', 'N/A')}")
        print(f"    间隔: {data.get('gap_seconds', 0):.0f}s")
    except Exception:
        print(f"    (无法读取)")

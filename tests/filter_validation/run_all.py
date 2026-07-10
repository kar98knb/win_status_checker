"""
运行所有过滤验证实验

用法（需要管理员权限）：
    python tests/filter_validation/run_all.py

每个实验产生两份 .etl 文件到 artifacts/<scenario>/：
- full.etl:     全订阅（对照组）
- filtered.etl: 应用黑名单+白名单过滤（实验组）

跑完后用以下命令分析（不需要管理员）：
    python tests/filter_validation/analyze.py
    python tests/filter_validation/analyze_crash.py    # 只针对 process_crash 场景
"""

import sys
import ctypes
import subprocess
from pathlib import Path

THIS_DIR = Path(__file__).parent

# 每个实验脚本 + 是否有副作用（需要用户确认）
SCENARIOS = [
    ("process_crash", "test_process_crash.py", False),
    ("disk_io_spike", "test_disk_io_spike.py", False),
    ("memory_pressure", "test_memory_pressure.py", False),
    ("cpu_saturation", "test_cpu_saturation.py", False),
    ("network_disconnect", "test_network_disconnect.py", True),  # 会短暂断网
]


def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("✗ 需要管理员权限运行")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  ETW 过滤验证实验套件")
    print(f"{'='*60}\n")

    print(f"  将运行 {len(SCENARIOS)} 个实验：")
    for i, (name, _, side_effect) in enumerate(SCENARIOS):
        mark = " ⚠️" if side_effect else ""
        print(f"    {i+1}. {name}{mark}")
    print(f"\n  ⚠️  标记的实验会有副作用（比如短暂断网）")
    print(f"\n  按回车继续，Ctrl+C 取消...")
    try:
        input()
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(0)

    for name, script, _ in SCENARIOS:
        script_path = THIS_DIR / script
        if not script_path.exists():
            print(f"  ⚠ 跳过 {name}: 脚本不存在 {script}")
            continue
        try:
            subprocess.run([sys.executable, str(script_path)], check=False)
        except Exception as e:
            print(f"  ✗ {name} 失败: {e}")

    print(f"\n{'='*60}")
    print(f"  全部完成！artifacts 目录：{THIS_DIR / 'artifacts'}")
    print(f"{'='*60}")
    print(f"\n  下一步（不需要管理员）:")
    print(f"    python tests/filter_validation/analyze.py")
    print(f"    python tests/filter_validation/analyze_crash.py")


if __name__ == "__main__":
    main()

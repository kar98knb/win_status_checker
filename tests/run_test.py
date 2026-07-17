"""压力测试统一调度入口。

直接运行:
    python tests/run_test.py

也可通过项目统一入口运行:
    python run.py --stress
"""

import ctypes
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_DIR = Path(__file__).resolve().parent / "filter_validation"

# 顺序执行。network_disconnect 放最后，避免断网影响前面的实验。
STRESS_TESTS = [
    ("process_crash", "test_process_crash.py"),
    ("disk_io_spike", "test_disk_io_spike.py"),
    ("memory_pressure", "test_memory_pressure.py"),
    ("cpu_saturation", "test_cpu_saturation.py"),
    ("network_disconnect", "test_network_disconnect.py"),
]


def is_admin() -> bool:
    return sys.platform == "win32" and bool(
        ctypes.windll.shell32.IsUserAnAdmin()
    )


def main() -> int:
    if not is_admin():
        print("\n✗ 压力测试需要管理员权限（测试期间会启动 ETW session）")
        print("  请以管理员身份运行: python run.py --stress\n")
        return 1

    print(f"\n{'=' * 70}")
    print("  win_status_checker 压力测试")
    print(f"{'=' * 70}")
    print("  将顺序执行:")
    for index, (name, _) in enumerate(STRESS_TESTS, start=1):
        print(f"    {index}. {name}")
    print("\n  注意: 测试会制造 CPU、内存、磁盘压力、子进程崩溃和短暂断网。")
    print(f"{'=' * 70}\n")

    results = []
    total_start = time.monotonic()

    for index, (name, script_name) in enumerate(STRESS_TESTS, start=1):
        script = SCENARIO_DIR / script_name
        print(f"\n{'-' * 70}")
        print(f"  [{index}/{len(STRESS_TESTS)}] {name}")
        print(f"{'-' * 70}")

        start = time.monotonic()
        if not script.exists():
            return_code = 2
            print(f"✗ 测试脚本不存在: {script}")
        else:
            try:
                completed = subprocess.run(
                    [sys.executable, "-u", str(script)],
                    cwd=PROJECT_ROOT,
                    check=False,
                )
                return_code = completed.returncode
            except KeyboardInterrupt:
                print("\n压力测试已中断。")
                return 130
            except OSError as exc:
                print(f"✗ 无法启动 {name}: {exc}")
                return_code = 1

        elapsed = time.monotonic() - start
        results.append((name, return_code, elapsed))
        state = "通过" if return_code == 0 else f"失败 (exit={return_code})"
        print(f"\n{name}: {state}, {elapsed:.1f}s")

    total_elapsed = time.monotonic() - total_start
    failed = [item for item in results if item[1] != 0]

    print(f"\n{'=' * 70}")
    print("  压力测试汇总")
    print(f"{'=' * 70}")
    for name, return_code, elapsed in results:
        state = "PASS" if return_code == 0 else f"FAIL ({return_code})"
        print(f"  {name:<24} {state:<12} {elapsed:>7.1f}s")
    print(f"  {'总耗时':<24} {'':<12} {total_elapsed:>7.1f}s")
    print(f"{'=' * 70}\n")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""
运行所有监控模块测试
用法: python tests/run_all.py
"""

import sys
import os
import time
import traceback

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import test_network_monitor
from tests import test_gpu_monitor
from tests import test_driver_monitor


def run_module_tests(module, module_name: str) -> tuple:
    """运行一个模块的所有测试函数，返回 (通过数, 失败数, 失败详情)"""
    passed = 0
    failed = 0
    failures = []

    # 找到所有 test_ 开头的函数
    test_funcs = [
        getattr(module, name)
        for name in dir(module)
        if name.startswith("test_") and callable(getattr(module, name))
    ]

    for func in test_funcs:
        try:
            func()
            passed += 1
        except Exception as e:
            failed += 1
            failures.append((func.__name__, str(e), traceback.format_exc()))

    return passed, failed, failures


def main():
    print("=" * 60)
    print("  游戏监控工具 - 测试套件")
    print("=" * 60)

    total_passed = 0
    total_failed = 0
    all_failures = []

    modules = [
        (test_network_monitor, "网络监控"),
        (test_gpu_monitor, "GPU 监控"),
        (test_driver_monitor, "驱动监控"),
    ]

    start_time = time.time()

    for module, name in modules:
        print(f"\n--- {name} ---\n")
        passed, failed, failures = run_module_tests(module, name)
        total_passed += passed
        total_failed += failed
        all_failures.extend([(name, *f) for f in failures])

    elapsed = time.time() - start_time

    # 汇总
    print("\n" + "=" * 60)
    print(f"  结果: {total_passed} 通过, {total_failed} 失败")
    print(f"  耗时: {elapsed:.1f}s")
    print("=" * 60)

    if all_failures:
        print("\n失败详情:")
        for module_name, func_name, error, tb in all_failures:
            print(f"\n  [{module_name}] {func_name}")
            print(f"  错误: {error}")
            print(f"  {tb}")
        sys.exit(1)
    else:
        print("\n全部通过 ✓")
        sys.exit(0)


if __name__ == "__main__":
    main()

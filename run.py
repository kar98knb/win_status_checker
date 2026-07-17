"""统一入口。

用法:
    python run.py           启动监控（需要管理员权限）
    python run.py --test    运行自动化测试
    python run.py --stress  运行全部压力测试（需要管理员权限）
"""

import ctypes
import site
import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).parent
VENV_DIR = ROOT_DIR / ".venv"

if sys.platform == "win32":
    VENV_SITE_PACKAGES = VENV_DIR / "Lib" / "site-packages"
else:
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    VENV_SITE_PACKAGES = VENV_DIR / "lib" / py_ver / "site-packages"


def activate_venv():
    """把 .venv 的 site-packages 注入当前进程。"""
    if not VENV_SITE_PACKAGES.exists():
        print("[错误] 虚拟环境未创建，请先运行:")
        print("  python install.py")
        sys.exit(1)
    site.addsitedir(str(VENV_SITE_PACKAGES))
    root_str = str(ROOT_DIR)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def is_admin() -> bool:
    """当前进程是否具有 Windows 管理员权限。"""
    return sys.platform == "win32" and bool(
        ctypes.windll.shell32.IsUserAnAdmin()
    )


def run_tests() -> int:
    """运行安全的自动化测试；管理员环境额外覆盖真实 ETW 数据通路。"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    unit_dir = ROOT_DIR / "tests" / "unit"
    suite.addTests(loader.discover(str(unit_dir), pattern="test_*.py"))

    elevated = is_admin()
    if elevated:
        admin_dir = ROOT_DIR / "tests" / "admin"
        suite.addTests(loader.discover(str(admin_dir), pattern="test_*.py"))
        print("管理员权限已检测到：运行单元测试 + ETW 集成测试。\n")
    else:
        print("未检测到管理员权限：运行全部无权限单元测试。")
        print("已跳过真实 ETW 集成测试；以管理员身份重跑可覆盖完整自动化测试。\n")

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    from src.compat import setup_console
    setup_console()
    activate_venv()

    if "--test" in sys.argv[1:]:
        unknown = [arg for arg in sys.argv[1:] if arg != "--test"]
        if unknown:
            print(f"[错误] 未知参数: {' '.join(unknown)}")
            return 2
        return run_tests()

    if "--stress" in sys.argv[1:]:
        unknown = [arg for arg in sys.argv[1:] if arg != "--stress"]
        if unknown:
            print(f"[错误] 未知参数: {' '.join(unknown)}")
            return 2
        from tests.run_test import main as stress_main
        return stress_main()

    if len(sys.argv) > 1:
        print("用法: python run.py [--test | --stress]")
        return 2

    if not is_admin():
        print("\n  ✗ 需要管理员权限运行（ETW kernel provider 订阅）")
        print("    请右键 → 以管理员身份运行\n")
        return 1

    from src.main import main as monitor_main
    monitor_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())

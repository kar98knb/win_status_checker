"""
运行入口

用法:
    python run.py              启动监控（双 session 常驻，Ctrl+C 停止并 dump）

需要管理员权限（ETW kernel provider 订阅）。
"""

import site
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).parent
VENV_DIR = ROOT_DIR / ".venv"

if sys.platform == "win32":
    VENV_SITE_PACKAGES = VENV_DIR / "Lib" / "site-packages"
else:
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    VENV_SITE_PACKAGES = VENV_DIR / "lib" / py_ver / "site-packages"


def activate_venv():
    """把 .venv 的 site-packages 注入当前进程"""
    if not VENV_SITE_PACKAGES.exists():
        print("[错误] 虚拟环境未创建，请先运行:")
        print("  python install.py")
        sys.exit(1)
    site.addsitedir(str(VENV_SITE_PACKAGES))
    root_str = str(ROOT_DIR)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


if __name__ == "__main__":
    from src.compat import setup_console
    setup_console()

    activate_venv()

    import ctypes
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("\n  ✗ 需要管理员权限运行（ETW kernel provider 订阅）")
        print("    请右键 → 以管理员身份运行\n")
        sys.exit(1)

    from src.main import main
    main()

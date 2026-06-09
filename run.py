"""
运行脚本（零依赖）
激活虚拟环境路径后直接运行主程序，支持调试。

用法:
    python run.py              启动监控（生成报告 + 后台常驻）
    python run.py --list       列出历史会话
    python run.py --analyze 0 1  对比两份历史日志
    python run.py --test       运行测试套件
"""

import sys
import site
from pathlib import Path


ROOT_DIR = Path(__file__).parent
VENV_DIR = ROOT_DIR / ".venv"

if sys.platform == "win32":
    VENV_SITE_PACKAGES = VENV_DIR / "Lib" / "site-packages"
else:
    # Linux/Mac: .venv/lib/python3.x/site-packages
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    VENV_SITE_PACKAGES = VENV_DIR / "lib" / py_ver / "site-packages"


def activate_venv():
    """将虚拟环境的 site-packages 注入当前进程"""
    if not VENV_SITE_PACKAGES.exists():
        print("[错误] 虚拟环境未创建，请先运行:")
        print("  python install.py")
        sys.exit(1)

    # 注入 site-packages 路径
    site.addsitedir(str(VENV_SITE_PACKAGES))

    # 确保项目根目录在 path 中
    root_str = str(ROOT_DIR)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


if __name__ == "__main__":
    from src.compat import setup_console
    setup_console()

    activate_venv()

    # 处理 --test 参数：运行测试套件
    if "--test" in sys.argv or "-t" in sys.argv:
        sys.argv = [sys.argv[0]]
        from tests.run_all import main as run_tests
        run_tests()
    elif "--list" in sys.argv or "-l" in sys.argv:
        from src.analyzer import print_sessions
        print_sessions()
    elif "--analyze" in sys.argv or "-a" in sys.argv:
        from src.analyzer import analyze_sessions
        # 解析序号参数
        args = sys.argv[1:]
        try:
            flag_idx = args.index("--analyze") if "--analyze" in args else args.index("-a")
            idx1 = int(args[flag_idx + 1])
            idx2 = int(args[flag_idx + 2])
            analyze_sessions(idx1, idx2)
        except (IndexError, ValueError):
            print("  用法: python run.py --analyze <序号1> <序号2>")
            print("  先用 python run.py --list 查看可用序号")
    else:
        from src.main import main
        main()

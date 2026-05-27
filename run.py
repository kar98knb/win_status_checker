"""
运行脚本（零依赖）
激活虚拟环境路径后直接运行主程序，支持调试。

用法:
    python run.py              完整模式（监控 + Web）
    python run.py --no-web     仅监控报警
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
    # Windows 终端 UTF-8 支持
    if sys.platform == "win32":
        try:
            import ctypes
            # 设置控制台代码页为 UTF-8
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
        # 重新配置 stdout/stderr 编码
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    activate_venv()

    # 处理 --test 参数：运行测试套件
    if "--test" in sys.argv or "-t" in sys.argv:
        sys.argv = [sys.argv[0]]  # 清理参数，避免传给测试
        from tests.run_all import main as run_tests
        run_tests()
    elif "--record" in sys.argv:
        # 录制模式：采集原始 API 数据
        sys.argv.remove("--record")
        from src.checks.recorder import Recorder, collect_raw_sample
        label = ""
        for i, arg in enumerate(sys.argv):
            if arg == "--label" and i + 1 < len(sys.argv):
                label = sys.argv[i + 1]
                break
        recorder = Recorder()
        print(f"录制模式启动，文件: {recorder.file_path}")
        print(f"标签: {label or '(无)'}")
        print("每 2 秒采集一次，Ctrl+C 停止\n")
        try:
            while True:
                sample = collect_raw_sample(label=label)
                recorder.record_sample(sample)
                print(f"  [{sample['_seq']}] 已录制", end="\r")
                import time as _t
                _t.sleep(2)
        except KeyboardInterrupt:
            print(f"\n\n录制完成，共 {sample['_seq'] + 1} 条样本")
            print(f"文件: {recorder.file_path}")
    else:
        from src.main import main
        main()

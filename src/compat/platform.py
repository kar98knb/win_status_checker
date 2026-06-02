"""
平台适配层
处理 Windows / Linux / macOS 的差异，确保跨平台行为一致。
"""

import sys


def setup_console():
    """配置控制台编码，确保 UTF-8 输出不乱码"""
    if sys.platform == "win32":
        _setup_windows_console()


def _setup_windows_console():
    """Windows 终端 UTF-8 适配"""
    # 设置控制台代码页为 UTF-8（等同于 chcp 65001）
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

    # 重新配置 Python stdout/stderr 编码
    # 避免 print 中文/emoji 时抛 UnicodeEncodeError
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

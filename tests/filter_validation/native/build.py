"""
用 tinycc 把 crash.c 编译成 crash.exe。

用作 test_process_crash.py 的 hard_crash 子进程——真正触发 access violation，
让 Windows kernel 以 0xC0000005 终止进程。

依赖: pip install tinycc
"""

import subprocess
import sys
from pathlib import Path


NATIVE_DIR = Path(__file__).parent
CRASH_SRC = NATIVE_DIR / "crash.c"
CRASH_EXE = NATIVE_DIR / "crash.exe"


def build_crash_exe(force: bool = False) -> Path:
    """
    确保 crash.exe 存在，需要就现场编译。

    Args:
        force: 强制重新编译（默认: 源文件比 exe 新才编译）

    Returns:
        crash.exe 路径

    Raises:
        RuntimeError: 编译失败或 tinycc 未安装
    """
    if CRASH_EXE.exists() and not force:
        if CRASH_EXE.stat().st_mtime >= CRASH_SRC.stat().st_mtime:
            return CRASH_EXE

    try:
        import tinycc
    except ImportError:
        raise RuntimeError(
            "tinycc 未安装。请运行: pip install tinycc"
        )

    result = subprocess.run(
        [str(tinycc.TCC), str(CRASH_SRC), "-o", str(CRASH_EXE)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not CRASH_EXE.exists():
        raise RuntimeError(
            f"tcc 编译 crash.c 失败:\n"
            f"  stdout: {result.stdout}\n"
            f"  stderr: {result.stderr}"
        )
    return CRASH_EXE


if __name__ == "__main__":
    try:
        exe = build_crash_exe(force="--force" in sys.argv)
        size = exe.stat().st_size
        print(f"✓ 已编译: {exe} ({size} 字节)")
    except RuntimeError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)

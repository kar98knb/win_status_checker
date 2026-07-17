"""
环境安装脚本（零依赖，只需 Python 标准库）
创建虚拟环境并安装项目依赖，只需运行一次。

用法:
    python install.py
"""

import sys
import subprocess
import venv
from pathlib import Path


ROOT_DIR = Path(__file__).parent
VENV_DIR = ROOT_DIR / ".venv"
REQUIREMENTS = ROOT_DIR / "requirements.txt"

if sys.platform == "win32":
    VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
    VENV_PIP = VENV_DIR / "Scripts" / "pip.exe"
else:
    VENV_PYTHON = VENV_DIR / "bin" / "python"
    VENV_PIP = VENV_DIR / "bin" / "pip"


def main():
    print("=" * 50)
    print("  win_status_checker - 环境安装")
    print("=" * 50)
    print()

    # 检查 Python 版本
    if sys.version_info < (3, 10):
        print(f"[错误] 需要 Python 3.10+，当前版本: {sys.version}")
        sys.exit(1)

    print(f"  Python: {sys.version.split()[0]}")
    print(f"  虚拟环境: {VENV_DIR}")
    print()

    # 创建虚拟环境
    if VENV_PYTHON.exists():
        print("[✓] 虚拟环境已存在，跳过创建")
    else:
        print("[1/2] 创建虚拟环境...")
        try:
            venv.create(str(VENV_DIR), with_pip=True)
            print("  ✓ 完成")
        except Exception as e:
            print(f"  ✗ 失败: {e}")
            sys.exit(1)

    # 安装依赖
    print("[2/2] 安装依赖...")
    result = subprocess.run(
        [str(VENV_PIP), "install", "-r", str(REQUIREMENTS)],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0 or "already satisfied" in result.stdout.lower():
        print("  ✓ 依赖安装完成")
    else:
        stderr = result.stderr.strip()
        # pip notice 不算错误
        if stderr and "error" in stderr.lower() and "[notice]" not in stderr:
            print(f"  ⚠ 安装可能有问题:")
            print(f"    {stderr[:300]}")
        else:
            print("  ✓ 依赖安装完成")

    # 完成提示
    print()
    print("=" * 50)
    print("  安装完成！")
    print()
    print("    python run.py                        # 启动监控（需管理员）")
    print("    Ctrl+C 停止 → 用 WPA 打开 logs\\runs\\<ts>\\snap.etl")
    print("=" * 50)


if __name__ == "__main__":
    main()

@echo off
title 游戏系统监控
echo ========================================
echo   游戏系统监控工具 - 启动中...
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 虚拟环境目录（项目根目录下的 .venv）
set VENV_DIR=%~dp0.venv
set VENV_PYTHON=%VENV_DIR%\Scripts\python.exe
set VENV_PIP=%VENV_DIR%\Scripts\pip.exe

:: 如果虚拟环境不存在，创建它
if not exist "%VENV_PYTHON%" (
    echo [首次运行] 创建虚拟环境...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo 虚拟环境创建完成: %VENV_DIR%
    echo.
    echo 安装依赖（首次需要下载，请稍候）...
    "%VENV_PIP%" install -r "%~dp0requirements.txt" >nul 2>&1
    if errorlevel 1 (
        echo [警告] 部分依赖可能安装失败，尝试继续...
    )
    echo 依赖安装完成。
)

echo.
echo 虚拟环境: %VENV_DIR%

:: 解析参数
set NO_WEB=0
for %%a in (%*) do (
    if "%%a"=="--no-web" set NO_WEB=1
    if "%%a"=="-n" set NO_WEB=1
)

if %NO_WEB%==1 (
    echo 模式: 仅监控（无 Web 服务）
    echo.
    "%VENV_PYTHON%" "%~dp0main.py" --no-web
) else (
    echo 模式: 完整（监控 + Web 服务）
    echo.
    "%VENV_PYTHON%" "%~dp0main.py"
)

pause

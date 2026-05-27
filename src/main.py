"""
游戏玩家系统监控工具 - 主入口
监控网络、GPU、鼠标/键盘驱动状态
提供 Web GUI 实时查看 + 异常报警

访问地址: http://localhost:8870
"""

import os
import sys
import time
import json
import asyncio
import logging
import threading
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Set

# 确保项目根目录在 sys.path 中（从 src/ 往上一级）
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psutil
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from config import (
    MONITOR_INTERVAL,
    WEB_PORT,
    ALERT_THRESHOLDS,
    LOG_DIR,
    LOG_MAX_SIZE_MB,
    LOG_BACKUP_COUNT,
    LOG_RETAIN_DAYS,
    WEB_REFRESH_INTERVAL,
    PROCESS_PRIORITY,
)
from src.monitors.network_monitor import NetworkMonitor
from src.monitors.gpu_monitor import GPUMonitor
from src.monitors.driver_monitor import DriverMonitor
from src.monitors.system_monitor import SystemMonitor
from src.alerts.alerter import Alerter
from src.alerts.snapshot import save_snapshot, check_abnormal_exit, clear_snapshot
from src.checks.startup_checks import run_startup_checks


# ============ 日志配置 ============

def setup_logging():
    """
    配置日志系统
    目录结构:
        logs/
        ├── last_snapshot.json      # 一次性：快照文件
        ├── crash_report.json       # 一次性：崩溃报告
        └── 20260527_143000/        # 每次启动一个时间戳文件夹
            ├── monitor.log
            └── alerts.log
    """
    from datetime import datetime

    log_root = PROJECT_ROOT / LOG_DIR
    log_root.mkdir(exist_ok=True)

    # 每次启动创建时间戳子目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = log_root / timestamp
    session_dir.mkdir(exist_ok=True)

    # 主日志
    handler = RotatingFileHandler(
        session_dir / "monitor.log",
        maxBytes=LOG_MAX_SIZE_MB * 1024 * 1024,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    # 报警专用日志
    alert_handler = RotatingFileHandler(
        session_dir / "alerts.log",
        maxBytes=LOG_MAX_SIZE_MB * 1024 * 1024,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    alert_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    ))
    alert_handler.setLevel(logging.WARNING)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    alert_logger = logging.getLogger("alerter")
    alert_logger.addHandler(alert_handler)

    # 清理过期日志目录
    _cleanup_old_logs(log_root)

    return logging.getLogger("main")


def _cleanup_old_logs(log_root: Path):
    """清理超过保留天数的旧日志目录"""
    from datetime import datetime, timedelta
    import shutil

    cutoff = datetime.now() - timedelta(days=LOG_RETAIN_DAYS)

    for item in log_root.iterdir():
        if not item.is_dir():
            continue
        # 只处理时间戳格式的目录（YYYYMMDD_HHMMSS）
        try:
            dir_time = datetime.strptime(item.name, "%Y%m%d_%H%M%S")
            if dir_time < cutoff:
                shutil.rmtree(item)
        except ValueError:
            # 不是时间戳格式的目录，跳过
            pass


# ============ 设置进程优先级 ============

def set_low_priority():
    """降低进程优先级，确保不影响游戏"""
    try:
        p = psutil.Process(os.getpid())
        if PROCESS_PRIORITY == "idle":
            p.nice(psutil.IDLE_PRIORITY_CLASS)
        elif PROCESS_PRIORITY == "below_normal":
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass


# ============ FastAPI 应用 ============

app = FastAPI(title="游戏监控面板", docs_url=None, redoc_url=None)

# 全局状态存储
latest_data = {
    "network": {},
    "gpu": {},
    "system": {},
    "drivers": {},
    "startup_checks": {},
    "timestamp": 0,
}
data_lock = threading.Lock()

# WebSocket 连接池
ws_clients: Set[WebSocket] = set()


@app.get("/", response_class=HTMLResponse)
async def index():
    """返回监控面板页面"""
    html_path = Path(__file__).parent / "web" / "static" / "index.html"
    content = html_path.read_text(encoding="utf-8")
    return HTMLResponse(
        content=content.replace("{{WEB_REFRESH_INTERVAL}}", str(WEB_REFRESH_INTERVAL))
    )


@app.get("/api/status")
async def get_status():
    """HTTP API - 获取当前状态快照"""
    with data_lock:
        return latest_data.copy()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket 端点 - 实时推送状态"""
    await ws.accept()
    ws_clients.add(ws)
    try:
        with data_lock:
            await ws.send_json(latest_data)
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


async def broadcast_to_clients(data: dict):
    """向所有 WebSocket 客户端广播数据"""
    dead_clients = set()
    for ws in ws_clients.copy():
        try:
            await ws.send_json(data)
        except Exception:
            dead_clients.add(ws)
    ws_clients -= dead_clients


# ============ 监控循环 ============

def monitor_loop(logger: logging.Logger):
    """后台监控循环（在独立线程运行）"""
    network_mon = NetworkMonitor()
    gpu_mon = GPUMonitor()
    driver_mon = DriverMonitor()
    system_mon = SystemMonitor()
    alerter = Alerter(cooldown_seconds=60)

    driver_last_check = 0
    driver_check_interval = ALERT_THRESHOLDS.get("driver_check_interval", 30)

    logger.info("监控循环已启动")

    while True:
        try:
            # 采集网络、GPU、系统资源（每次都采）
            network_status = network_mon.collect()
            gpu_status = gpu_mon.collect()
            system_status = system_mon.collect()

            # 驱动状态检查频率较低（WMI 查询较重）
            now = time.time()
            if now - driver_last_check >= driver_check_interval:
                driver_status = driver_mon.collect()
                driver_last_check = now
            else:
                driver_status = None

            # 更新全局数据
            data = {
                "network": network_status.to_dict(),
                "gpu": gpu_status.to_dict(),
                "system": system_status.to_dict(),
                "timestamp": time.time(),
            }
            if driver_status:
                data["drivers"] = driver_status.to_dict()

            with data_lock:
                latest_data["network"] = data["network"]
                latest_data["gpu"] = data["gpu"]
                latest_data["system"] = data["system"]
                latest_data["timestamp"] = data["timestamp"]
                if "drivers" in data:
                    latest_data["drivers"] = data["drivers"]

            # 检查报警
            alerter.check_and_alert(
                network_status,
                gpu_status,
                driver_status if driver_status else None,
                ALERT_THRESHOLDS,
            )

            # 系统资源报警
            if system_status.memory_percent > 90:
                alerter.alert(
                    "memory_high",
                    "内存不足",
                    f"内存使用 {system_status.memory_percent:.0f}%，"
                    f"可用 {system_status.memory_available_gb:.1f}GB",
                    "warning"
                )
            if system_status.cpu_throttled:
                alerter.alert(
                    "cpu_throttled",
                    "CPU 降频",
                    f"CPU 频率 {system_status.cpu_freq_mhz:.0f}MHz "
                    f"(最大 {system_status.cpu_freq_max_mhz:.0f}MHz)，可能过热降频",
                    "warning"
                )
            if system_status.has_resource_hog:
                hog_names = [p.name for p in system_status.top_processes
                             if p.cpu_percent > 15]
                alerter.alert(
                    "resource_hog",
                    "后台进程抢资源",
                    f"检测到高占用后台进程: {', '.join(hog_names[:3])}",
                    "info"
                )
            if network_status.jitter_ms > 30:
                alerter.alert(
                    "high_jitter",
                    "网络抖动大",
                    f"抖动 {network_status.jitter_ms:.0f}ms，可能导致游戏卡顿",
                    "warning"
                )

            # 广播给 WebSocket 客户端
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(broadcast_to_clients(latest_data.copy()))
                loop.close()
            except Exception:
                pass

            # 快照落盘（确保卡死时数据可追溯）
            save_snapshot(latest_data.copy())

        except Exception as e:
            logger.error(f"监控循环异常: {e}", exc_info=True)

        time.sleep(MONITOR_INTERVAL)


# ============ 启动 ============

def main():
    """主入口"""
    import argparse

    parser = argparse.ArgumentParser(description="游戏系统监控工具")
    parser.add_argument(
        "--no-web", "-n",
        action="store_true",
        help="仅运行监控和报警，不启动 Web 服务"
    )
    args = parser.parse_args()

    logger = setup_logging()
    set_low_priority()

    # 检查上次是否异常退出（卡死/崩溃）
    crash_report = check_abnormal_exit(max_gap_seconds=MONITOR_INTERVAL * 15)
    if crash_report:
        logger.critical("=" * 50)
        logger.critical("检测到上次异常退出（可能卡死/崩溃）")
        logger.critical(f"  上次快照时间距今: {crash_report['gap_seconds']}s")
        logger.critical(f"  {crash_report['conclusion']}")
        logger.critical("  详细报告: logs/crash_report.json")
        logger.critical("=" * 50)
        print(f"\n  ⚠ 检测到上次异常退出！")
        print(f"    {crash_report['conclusion']}")
        print(f"    详细报告: logs/crash_report.json\n")

    mode = "仅监控" if args.no_web else "完整（监控 + Web）"
    logger.info("=" * 50)
    logger.info("游戏监控工具启动")
    logger.info(f"运行模式: {mode}")
    logger.info(f"监控间隔: {MONITOR_INTERVAL}s")
    logger.info(f"Web 端口: {WEB_PORT}")
    logger.info(f"进程优先级: {PROCESS_PRIORITY}")
    logger.info("=" * 50)

    monitor_thread = threading.Thread(target=monitor_loop, args=(logger,), daemon=True)
    monitor_thread.start()

    # 启动时一次性检测
    logger.info("执行启动检测...")
    startup_result = run_startup_checks()
    with data_lock:
        latest_data["startup_checks"] = startup_result.to_dict()

    if startup_result.warnings:
        print(f"  ⚠ 启动检测发现 {len(startup_result.warnings)} 个问题:")
        for w in startup_result.warnings:
            print(f"    - {w}")
        print()

    if args.no_web:
        print(f"\n{'='*50}")
        print(f"  监控已启动（无 Web 服务）")
        print(f"  报警通知正常工作")
        print(f"  日志记录在 logs/ 目录")
        print(f"  按 Ctrl+C 停止")
        print(f"{'='*50}\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            clear_snapshot()  # 正常退出，清除快照
            print("\n监控已停止。")
    else:
        print(f"\n{'='*50}")
        print(f"  游戏监控面板已启动！")
        print(f"  打开浏览器访问: http://localhost:{WEB_PORT}")
        print(f"  按 Ctrl+C 停止")
        print(f"{'='*50}\n")

        try:
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=WEB_PORT,
                log_level="warning",
            )
        finally:
            clear_snapshot()  # 正常退出，清除快照


if __name__ == "__main__":
    main()

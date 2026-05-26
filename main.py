"""
游戏玩家系统监控工具 - 主入口
监控网络、GPU、鼠标/键盘驱动状态
提供 Web GUI 实时查看 + 异常报警

启动方式: python main.py
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
    PROCESS_PRIORITY,
)
from src.monitors.network_monitor import NetworkMonitor
from src.monitors.gpu_monitor import GPUMonitor
from src.monitors.driver_monitor import DriverMonitor
from src.alerter import Alerter


# ============ 日志配置 ============

def setup_logging():
    """配置日志系统"""
    log_path = Path(LOG_DIR)
    log_path.mkdir(exist_ok=True)

    # 主日志
    handler = RotatingFileHandler(
        log_path / "monitor.log",
        maxBytes=LOG_MAX_SIZE_MB * 1024 * 1024,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    # 报警专用日志
    alert_handler = RotatingFileHandler(
        log_path / "alerts.log",
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

    return logging.getLogger("main")


# ============ 设置进程优先级 ============

def set_low_priority():
    """降低进程优先级，确保不影响游戏"""
    try:
        p = psutil.Process(os.getpid())
        if PROCESS_PRIORITY == "idle":
            p.nice(psutil.IDLE_PRIORITY_CLASS)
        elif PROCESS_PRIORITY == "below_normal":
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        # "normal" 不需要设置
    except Exception:
        pass


# ============ FastAPI 应用 ============

app = FastAPI(title="游戏监控面板", docs_url=None, redoc_url=None)

# 全局状态存储
latest_data = {
    "network": {},
    "gpu": {},
    "drivers": {},
    "timestamp": 0,
}
data_lock = threading.Lock()

# WebSocket 连接池
ws_clients: Set[WebSocket] = set()


@app.get("/", response_class=HTMLResponse)
async def index():
    """返回监控面板页面"""
    html_path = Path(__file__).parent / "src" / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


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
        # 立即发送当前状态
        with data_lock:
            await ws.send_json(latest_data)
        # 保持连接，等待客户端断开
        while True:
            # 接收心跳或等待断开
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
    alerter = Alerter(cooldown_seconds=60)

    driver_last_check = 0
    driver_check_interval = ALERT_THRESHOLDS.get("driver_check_interval", 30)

    logger.info("监控循环已启动")

    while True:
        try:
            # 采集网络和 GPU（每次都采）
            network_status = network_mon.collect()
            gpu_status = gpu_mon.collect()

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
                "timestamp": time.time(),
            }
            if driver_status:
                data["drivers"] = driver_status.to_dict()

            with data_lock:
                latest_data["network"] = data["network"]
                latest_data["gpu"] = data["gpu"]
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

            # 广播给 WebSocket 客户端
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(broadcast_to_clients(latest_data.copy()))
                loop.close()
            except Exception:
                pass

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

    mode = "仅监控" if args.no_web else "完整（监控 + Web）"
    logger.info("=" * 50)
    logger.info("游戏监控工具启动")
    logger.info(f"运行模式: {mode}")
    logger.info(f"监控间隔: {MONITOR_INTERVAL}s")
    logger.info(f"Web 端口: {WEB_PORT}")
    logger.info(f"进程优先级: {PROCESS_PRIORITY}")
    logger.info("=" * 50)

    # 启动监控线程
    monitor_thread = threading.Thread(target=monitor_loop, args=(logger,), daemon=True)
    monitor_thread.start()

    if args.no_web:
        # 仅监控模式，主线程保持运行
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
            print("\n监控已停止。")
    else:
        # 完整模式，启动 Web 服务
        print(f"\n{'='*50}")
        print(f"  游戏监控面板已启动！")
        print(f"  打开浏览器访问: http://localhost:{WEB_PORT}")
        print(f"  按 Ctrl+C 停止")
        print(f"{'='*50}\n")

        uvicorn.run(
            app,
            host="0.0.0.0",
            port=WEB_PORT,
            log_level="warning",
        )


if __name__ == "__main__":
    main()

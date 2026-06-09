"""
游戏玩家系统监控工具 - 主入口
各监控模块独立线程运行，异常时报警通知，退出时生成报告。
"""

import os
import sys
import time
import json
import logging
import threading
from pathlib import Path
from logging.handlers import RotatingFileHandler
from concurrent.futures import ThreadPoolExecutor

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psutil

from config import (
    MONITOR_INTERVAL,
    ALERT_THRESHOLDS,
    LOG_DIR,
    LOG_MAX_SIZE_MB,
    LOG_BACKUP_COUNT,
    LOG_RETAIN_DAYS,
    PROCESS_PRIORITY,
)
from src.monitors.network_monitor import NetworkMonitor
from src.monitors.gpu_monitor import GPUMonitor
from src.monitors.driver_monitor import DriverMonitor
from src.monitors.system_monitor import SystemMonitor
from src.monitors.process_focus import ProcessFocusMonitor
from src.alerts.alerter import Alerter
from src.alerts.snapshot import save_snapshot, check_abnormal_exit, clear_snapshot
from src.checks.startup_checks import run_startup_checks
from src.checks.event_log import check_system_events


# ============ 全局状态 ============

latest_data = {
    "network": {},
    "gpu": {},
    "system": {},
    "process_focus": {},
    "drivers": {},
    "startup_checks": {},
    "event_log": {},
    "timestamp": 0,
}
data_lock = threading.Lock()

# 会话目录（每次启动唯一）
_session_dir: Path = None


# ============ 日志配置 ============

def setup_logging() -> Path:
    """配置日志系统，返回本次会话日志目录"""
    from datetime import datetime

    log_root = PROJECT_ROOT / LOG_DIR
    log_root.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = log_root / timestamp
    session_dir.mkdir(exist_ok=True)

    # 主日志（全局）
    handler = RotatingFileHandler(
        session_dir / "monitor.log",
        maxBytes=LOG_MAX_SIZE_MB * 1024 * 1024,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    _cleanup_old_logs(log_root)

    return session_dir


def _setup_module_logger(name: str, session_dir: Path) -> logging.Logger:
    """为单个监控模块创建独立日志文件"""
    log_subdir = session_dir / "log"
    log_subdir.mkdir(exist_ok=True)

    logger = logging.getLogger(f"monitor.{name}")
    handler = RotatingFileHandler(
        log_subdir / f"{name}.log",
        maxBytes=LOG_MAX_SIZE_MB * 1024 * 1024,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    ))
    logger.addHandler(handler)
    return logger


def _cleanup_old_logs(log_root: Path):
    """清理超过保留天数的旧日志目录"""
    from datetime import datetime, timedelta
    import shutil

    cutoff = datetime.now() - timedelta(days=LOG_RETAIN_DAYS)
    for item in log_root.iterdir():
        if not item.is_dir():
            continue
        try:
            dir_time = datetime.strptime(item.name, "%Y%m%d_%H%M%S")
            if dir_time < cutoff:
                shutil.rmtree(item)
        except ValueError:
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


# ============ 各模块独立监控线程 ============

def _network_loop(alerter: Alerter, logger: logging.Logger):
    """网络监控线程"""
    mon = NetworkMonitor()
    while True:
        try:
            status = mon.collect()
            with data_lock:
                latest_data["network"] = status.to_dict()

            # 报警
            if not status.is_connected:
                alerter.alert("network_down", "网络断开", "检测到网络连接已断开！", "critical")
            elif status.packet_loss_percent > ALERT_THRESHOLDS.get("packet_loss_percent", 5):
                alerter.alert("packet_loss", "网络丢包",
                              f"丢包率 {status.packet_loss_percent:.1f}%", "warning")
            if status.latency_anomaly:
                alerter.alert("latency_spike", "网络延迟突增",
                              f"延迟 {status.latency_ms:.0f}ms，基线 {status.latency_baseline:.0f}ms", "warning")
            if status.jitter_anomaly:
                alerter.alert("jitter_spike", "网络抖动突增",
                              f"抖动 {status.jitter_ms:.0f}ms", "warning")

            logger.info(
                f"延迟={status.latency_ms:.1f}ms 抖动={status.jitter_ms:.1f}ms "
                f"丢包={status.packet_loss_percent:.0f}% 闪断={status.link_down_count}"
            )
        except Exception as e:
            logger.error(f"异常: {e}")

        time.sleep(MONITOR_INTERVAL)


def _gpu_loop(alerter: Alerter, logger: logging.Logger):
    """GPU 监控线程"""
    mon = GPUMonitor()
    while True:
        try:
            status = mon.collect()
            with data_lock:
                latest_data["gpu"] = status.to_dict()

            if status.is_available:
                if status.temperature_celsius > ALERT_THRESHOLDS.get("gpu_temp_celsius", 85) and status.temperature_celsius > 0:
                    alerter.alert("gpu_temp", "GPU 过热",
                                  f"GPU 温度 {status.temperature_celsius:.0f}°C", "critical")
                if status.memory_percent > ALERT_THRESHOLDS.get("gpu_memory_percent", 95):
                    alerter.alert("gpu_memory", "显存不足",
                                  f"显存使用 {status.memory_percent:.1f}%", "warning")

                logger.info(
                    f"使用率={status.gpu_usage_percent:.1f}% 温度={status.temperature_celsius:.0f}°C "
                    f"显存={status.memory_percent:.1f}%"
                )
        except Exception as e:
            logger.error(f"异常: {e}")

        time.sleep(MONITOR_INTERVAL)


def _system_loop(alerter: Alerter, logger: logging.Logger):
    """系统资源监控线程（CPU/内存/磁盘/进程抢占）"""
    mon = SystemMonitor()
    while True:
        try:
            status = mon.collect()
            with data_lock:
                latest_data["system"] = status.to_dict()

            if status.memory_percent > 90:
                alerter.alert("memory_high", "内存不足",
                              f"内存使用 {status.memory_percent:.0f}%，可用 {status.memory_available_gb:.1f}GB", "warning")
            if status.cpu_throttled:
                alerter.alert("cpu_throttled", "CPU 降频",
                              f"频率 {status.cpu_freq_mhz:.0f}/{status.cpu_freq_max_mhz:.0f}MHz", "warning")
            if status.has_resource_hog:
                hog_names = [p.name for p in status.top_processes if p.cpu_percent > 15]
                alerter.alert("resource_hog", "后台进程抢资源",
                              f"{', '.join(hog_names[:3])}", "info")

            logger.info(
                f"CPU={status.cpu_usage_percent:.1f}% 内存={status.memory_percent:.1f}% "
                f"磁盘R={status.disk_read_mb_per_sec:.1f}MB/s W={status.disk_write_mb_per_sec:.1f}MB/s"
            )
        except Exception as e:
            logger.error(f"异常: {e}")

        time.sleep(MONITOR_INTERVAL)


def _driver_loop(alerter: Alerter, logger: logging.Logger):
    """设备驱动监控线程"""
    mon = DriverMonitor()
    interval = ALERT_THRESHOLDS.get("driver_check_interval", 30)
    while True:
        try:
            status = mon.collect()
            with data_lock:
                latest_data["drivers"] = status.to_dict()

            if not status.all_mice_ok:
                alerter.alert("mouse_driver", "鼠标驱动异常", "鼠标设备驱动异常", "critical")
            if not status.all_keyboards_ok:
                alerter.alert("keyboard_driver", "键盘驱动异常", "键盘设备驱动异常", "critical")
            if not status.all_audio_ok:
                alerter.alert("audio_driver", "音频设备异常", "耳机/音频设备驱动异常", "warning")
            if not status.all_controllers_ok:
                alerter.alert("controller_driver", "手柄驱动异常", "游戏手柄/控制器驱动异常", "warning")
            if not status.all_bluetooth_ok:
                alerter.alert("bluetooth_driver", "蓝牙异常", "蓝牙设备驱动异常", "warning")

            device_count = len(status.mice) + len(status.keyboards) + len(status.audio_devices)
            logger.info(f"设备={device_count} 鼠标OK={status.all_mice_ok} 键盘OK={status.all_keyboards_ok}")
        except Exception as e:
            logger.error(f"异常: {e}")

        time.sleep(interval)


def _focus_loop(alerter: Alerter, logger: logging.Logger):
    """进程焦点监控线程"""
    mon = ProcessFocusMonitor()
    while True:
        try:
            status = mon.collect()
            with data_lock:
                latest_data["process_focus"] = status.to_dict()

            if status.focused:
                logger.info(
                    f"焦点={status.focused.name} PID={status.focused.pid} "
                    f"CPU={status.focused.cpu_percent:.1f}% 内存={status.focused.memory_mb:.0f}MB"
                )
            # 检查最近退出
            if status.recent_exits:
                last_exit = status.recent_exits[-1]
                if last_exit.get("exited_at", 0) > time.time() - MONITOR_INTERVAL * 2:
                    alerter.alert("focus_exit", "焦点进程退出",
                                  f"{last_exit['name']} 已退出", "info")
        except Exception as e:
            logger.error(f"异常: {e}")

        time.sleep(MONITOR_INTERVAL)


def _snapshot_loop():
    """快照写入线程（独立高频率）"""
    while True:
        try:
            with data_lock:
                save_snapshot(latest_data.copy())
        except Exception:
            pass
        time.sleep(MONITOR_INTERVAL)


# ============ 报告生成 ============

def generate_report() -> str:
    """生成当前状态报告"""
    from datetime import datetime

    with data_lock:
        data = latest_data.copy()

    lines = []
    lines.append("=" * 60)
    lines.append(f"  系统状态报告 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)

    # 网络
    net = data.get("network", {})
    lines.append(f"\n[网络]")
    lines.append(f"  连接: {'正常' if net.get('is_connected') else '断开'}")
    lines.append(f"  延迟: {net.get('latency_ms', 0):.1f}ms (基线 {net.get('latency_baseline', 0):.1f}ms)")
    lines.append(f"  抖动: {net.get('jitter_ms', 0):.1f}ms")
    lines.append(f"  丢包: {net.get('packet_loss_percent', 0):.1f}%")
    lines.append(f"  闪断: {net.get('link_down_count', 0)} 次")
    lines.append(f"  适配器: {net.get('adapter_name', 'N/A')}")

    # GPU
    gpu = data.get("gpu", {})
    lines.append(f"\n[GPU]")
    lines.append(f"  型号: {gpu.get('gpu_name', 'N/A')}")
    lines.append(f"  使用率: {gpu.get('gpu_usage_percent', 0):.1f}%")
    lines.append(f"  温度: {gpu.get('temperature_celsius', -1):.0f}°C")
    lines.append(f"  显存: {gpu.get('memory_used_mb', 0):.0f}/{gpu.get('memory_total_mb', 0):.0f}MB")
    lines.append(f"  驱动: {gpu.get('driver_version', 'N/A')}")

    # 系统
    sys_data = data.get("system", {})
    lines.append(f"\n[CPU/内存/磁盘]")
    lines.append(f"  CPU: {sys_data.get('cpu_usage_percent', 0):.1f}%  频率: {sys_data.get('cpu_freq_mhz', 0):.0f}/{sys_data.get('cpu_freq_max_mhz', 0):.0f}MHz")
    lines.append(f"  降频: {'是' if sys_data.get('cpu_throttled') else '否'}")
    lines.append(f"  内存: {sys_data.get('memory_used_gb', 0):.1f}/{sys_data.get('memory_total_gb', 0):.1f}GB ({sys_data.get('memory_percent', 0):.1f}%)")
    lines.append(f"  磁盘: 读 {sys_data.get('disk_read_mb_per_sec', 0):.1f}MB/s  写 {sys_data.get('disk_write_mb_per_sec', 0):.1f}MB/s")

    # 焦点进程
    focus = data.get("process_focus", {})
    focused = focus.get("focused")
    lines.append(f"\n[焦点进程]")
    if focused:
        lines.append(f"  {focused['name']} (PID {focused['pid']})")
        lines.append(f"  CPU: {focused['cpu_percent']:.1f}%  内存: {focused['memory_mb']:.0f}MB")
    else:
        lines.append(f"  无（未检测到高占用游戏进程）")

    # 驱动
    drv = data.get("drivers", {})
    lines.append(f"\n[设备驱动]")
    lines.append(f"  鼠标: {'正常' if drv.get('all_mice_ok', True) else '异常'}")
    lines.append(f"  键盘: {'正常' if drv.get('all_keyboards_ok', True) else '异常'}")
    lines.append(f"  音频: {'正常' if drv.get('all_audio_ok', True) else '异常'}")
    lines.append(f"  蓝牙: {'正常' if drv.get('all_bluetooth_ok', True) else '异常'}")

    # 启动检测
    startup = data.get("startup_checks", {})
    if startup:
        lines.append(f"\n[启动检测]")
        lines.append(f"  电源计划: {startup.get('power_plan', 'N/A')} ({'OK' if startup.get('power_plan_ok') else '建议高性能'})")
        lines.append(f"  刷新率: {startup.get('display_refresh_rate', 0)}Hz")
        lines.append(f"  待重启更新: {'是' if startup.get('pending_reboot') else '否'}")

    # 事件日志
    evlog = data.get("event_log", {})
    if evlog.get("event_count", 0) > 0:
        lines.append(f"\n[系统事件 (过去{evlog.get('scan_hours', 24)}h)]")
        if evlog.get("has_unexpected_shutdown"):
            lines.append(f"  ⚠ 意外关机/卡死记录")
        if evlog.get("has_gpu_tdr"):
            lines.append(f"  ⚠ GPU 驱动崩溃 (TDR)")
        if evlog.get("has_app_crash"):
            lines.append(f"  ⚠ 应用崩溃记录")
        lines.append(f"  共 {evlog.get('event_count', 0)} 条相关事件")

    lines.append(f"\n{'=' * 60}")
    return "\n".join(lines)


# ============ 启动 ============

def main():
    """主入口"""
    global _session_dir

    _session_dir = setup_logging()
    logger = logging.getLogger("main")
    set_low_priority()

    # 并行执行启动检测
    with ThreadPoolExecutor(max_workers=3) as pool:
        future_crash = pool.submit(check_abnormal_exit, MONITOR_INTERVAL * 15)
        future_events = pool.submit(check_system_events, 24)
        future_startup = pool.submit(run_startup_checks)

        crash_report = future_crash.result()
        event_result = future_events.result()
        startup_result = future_startup.result()

    # 处理异常退出
    if crash_report:
        # 写入当前会话目录
        crash_path = _session_dir / "crash_report.json"
        crash_path.write_text(
            json.dumps(crash_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.critical("检测到上次异常退出")
        logger.critical(f"  {crash_report['conclusion']}")
        print(f"\n  ⚠ 检测到上次异常退出！")
        print(f"    {crash_report['conclusion']}")
        print(f"    详细报告: {crash_path}\n")

    # 处理事件日志
    with data_lock:
        latest_data["event_log"] = event_result.to_dict()
    if event_result.has_unexpected_shutdown:
        print(f"  ⚠ 事件日志发现意外关机/卡死记录！")
    if event_result.has_gpu_tdr:
        print(f"  ⚠ 事件日志发现 GPU 驱动崩溃(TDR)记录！")

    # 处理启动检测
    with data_lock:
        latest_data["startup_checks"] = startup_result.to_dict()
    if startup_result.warnings:
        print(f"  ⚠ 启动检测发现 {len(startup_result.warnings)} 个问题:")
        for w in startup_result.warnings:
            print(f"    - {w}")
        print()

    # 启动各模块监控线程（独立日志）
    alerter = Alerter(cooldown_seconds=60)
    monitor_threads = [
        ("network", _network_loop),
        ("gpu", _gpu_loop),
        ("system", _system_loop),
        ("drivers", _driver_loop),
        ("focus", _focus_loop),
    ]

    for name, loop_func in monitor_threads:
        mod_logger = _setup_module_logger(name, _session_dir)
        t = threading.Thread(target=loop_func, args=(alerter, mod_logger), daemon=True, name=name)
        t.start()

    # 快照线程
    threading.Thread(target=_snapshot_loop, daemon=True, name="snapshot").start()

    logger.info("=" * 50)
    logger.info("所有监控线程已启动")
    logger.info(f"监控间隔: {MONITOR_INTERVAL}s")
    logger.info(f"日志目录: {_session_dir}")
    logger.info("=" * 50)

    print(f"\n{'='*50}")
    print(f"  监控已启动（{len(monitor_threads)} 个模块独立运行）")
    print(f"  异常时自动报警通知")
    print(f"  日志: {_session_dir}")
    print(f"  按 Ctrl+C 停止并生成报告")
    print(f"{'='*50}\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # 正常退出：生成报告
        print("\n生成报告...")
        report = generate_report()
        report_path = _session_dir / "report.txt"
        report_path.write_text(report, encoding="utf-8")
        print(report)
        print(f"\n报告已保存: {report_path}")
        clear_snapshot()
        print("监控已停止。")


if __name__ == "__main__":
    main()

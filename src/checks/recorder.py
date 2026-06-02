"""
API 数据录制/回放模块

录制模式：运行时把系统 API 的原始返回值存到 JSON 文件
回放模式：测试时从 JSON 文件读取数据，注入到监控模块
"""

import json
import time
import os
from pathlib import Path
from typing import Optional

RECORDINGS_DIR = Path(__file__).parent.parent.parent / "tests" / "recordings"


class Recorder:
    """录制器 - 在监控循环中录制原始 API 数据"""

    def __init__(self, session_name: Optional[str] = None, output_dir: Optional[Path] = None):
        target_dir = output_dir or RECORDINGS_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        if session_name is None:
            session_name = time.strftime("%Y%m%d_%H%M%S")
        self._session_file = target_dir / f"session_{session_name}.jsonl"
        self._sample_count = 0

    def record_sample(self, sample: dict):
        sample["_seq"] = self._sample_count
        sample["_ts"] = time.time()
        with open(self._session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        self._sample_count += 1

    @property
    def file_path(self) -> Path:
        return self._session_file


def collect_raw_sample(label: str = "") -> dict:
    """采集一次原始 API 数据（用于录制）"""
    import psutil
    import socket
    import subprocess

    sample = {"label": label, "timestamp": time.time()}

    # 网络
    try:
        stats = psutil.net_if_stats()
        sample["net_if_stats"] = {
            name: {"isup": s.isup, "speed": s.speed} for name, s in stats.items()
        }
    except Exception:
        sample["net_if_stats"] = {}

    try:
        addrs = psutil.net_if_addrs()
        sample["net_if_addrs"] = {
            name: [{"family": a.family.name, "address": a.address} for a in addr_list]
            for name, addr_list in addrs.items()
        }
    except Exception:
        sample["net_if_addrs"] = {}

    try:
        io = psutil.net_io_counters()
        sample["net_io_counters"] = {
            "bytes_sent": io.bytes_sent, "bytes_recv": io.bytes_recv,
            "errin": io.errin, "errout": io.errout,
            "dropin": io.dropin, "dropout": io.dropout,
        }
    except Exception:
        sample["net_io_counters"] = {}

    tcp_targets = [("www.baidu.com", 80), ("dns.alidns.com", 53), ("8.8.8.8", 53)]
    latencies = []
    for host, port in tcp_targets:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            start = time.time()
            sock.connect((host, port))
            latency = (time.time() - start) * 1000
            sock.close()
            latencies.append(round(latency, 2))
        except Exception:
            latencies.append(-1)
    sample["tcp_latencies"] = latencies

    # CPU / 内存 / 磁盘
    try:
        sample["cpu_percent"] = psutil.cpu_percent(interval=None)
        freq = psutil.cpu_freq()
        sample["cpu_freq"] = {"current": freq.current, "max": freq.max} if freq else {}
    except Exception:
        sample["cpu_percent"] = 0
        sample["cpu_freq"] = {}

    try:
        mem = psutil.virtual_memory()
        sample["memory"] = {
            "total": mem.total, "used": mem.used,
            "available": mem.available, "percent": mem.percent,
        }
    except Exception:
        sample["memory"] = {}

    try:
        dio = psutil.disk_io_counters()
        sample["disk_io"] = {"read_bytes": dio.read_bytes, "write_bytes": dio.write_bytes} if dio else {}
    except Exception:
        sample["disk_io"] = {}

    # 驱动（WMI）
    try:
        import wmi
        import pythoncom
        pythoncom.CoInitialize()
        w = wmi.WMI()
        sample["wmi_pointing_devices"] = [
            {"Name": d.Name, "Status": d.Status, "ConfigManagerErrorCode": d.ConfigManagerErrorCode}
            for d in w.Win32_PointingDevice()
        ]
        sample["wmi_keyboards"] = [
            {"Name": d.Name, "Status": d.Status, "ConfigManagerErrorCode": d.ConfigManagerErrorCode}
            for d in w.Win32_Keyboard()
        ]
        sample["wmi_sound_devices"] = [
            {"Name": d.Name, "Status": d.Status, "ConfigManagerErrorCode": d.ConfigManagerErrorCode}
            for d in w.Win32_SoundDevice()
        ]
    except Exception:
        sample["wmi_pointing_devices"] = []
        sample["wmi_keyboards"] = []
        sample["wmi_sound_devices"] = []

    # GPU
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=gpu_name,utilization.gpu,memory.total,memory.used,temperature.gpu,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW
        )
        sample["nvidia_smi_output"] = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        sample["nvidia_smi_output"] = ""

    return sample


def load_recording(file_path: Path) -> list:
    """加载录制文件，返回样本列表"""
    samples = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples

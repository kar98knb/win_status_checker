"""
黑名单验证实验框架
每个实验：
  1. 起 full + filtered 两个 session
  2. 让调用方触发异常
  3. 停止 session，输出两份 .etl 文件供分析
"""

import sys
import time
import ctypes
import logging
from pathlib import Path
from typing import Callable, List, Tuple

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.etw.session import EtwFileSession
from src.etw.providers import (
    GUID,
    KERNEL_PROCESS, TCPIP, DXGKRNL,
    KERNEL_PROCESSOR_POWER, KERNEL_PNP,
    KERNEL_DISK_NEW, KERNEL_MEMORY,
)
from config import ETW_KEYWORD_BLACKLIST, ETW_LEVEL, ETW_EVENT_ID_WHITELIST

logger = logging.getLogger("filter_validation")

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

ALL_KEYWORDS = 0xFFFFFFFFFFFFFFFF

# provider 名称 → GUID 映射（对应 config 中黑名单 key）
PROVIDER_MAP = {
    "Kernel-Process": KERNEL_PROCESS,
    "TCPIP": TCPIP,
    "DxgKrnl": DXGKRNL,
    "CPU-Power": KERNEL_PROCESSOR_POWER,
    "Kernel-PnP": KERNEL_PNP,
    "Kernel-Disk": KERNEL_DISK_NEW,
    "Kernel-Memory": KERNEL_MEMORY,
}


def compute_filtered_keyword(provider_name: str) -> int:
    """根据黑名单计算过滤后的 keyword 掩码"""
    blacklist = ETW_KEYWORD_BLACKLIST.get(provider_name, [])
    excluded = 0
    for kw_value, _, _ in blacklist:
        excluded |= kw_value
    return ALL_KEYWORDS & (~excluded) & 0xFFFFFFFFFFFFFFFF


def get_all_provider_pairs() -> List[Tuple[GUID, str]]:
    """返回所有 (guid, provider_name) 对"""
    return [(guid, name) for name, guid in PROVIDER_MAP.items()]


class Experiment:
    """
    单个实验：同时启动 full 和 filtered session。
    """

    def __init__(self, scenario_name: str):
        self.scenario = scenario_name
        self.output_dir = ARTIFACTS_DIR / scenario_name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._full_session = None
        self._filtered_session = None

    def start(self):
        """启动两个 session"""
        full_etl = self.output_dir / "full.etl"
        filtered_etl = self.output_dir / "filtered.etl"

        # 清空旧文件
        for f in (full_etl, filtered_etl):
            if f.exists():
                f.unlink()

        # 全订阅 session
        self._full_session = EtwFileSession(
            session_name=f"FilterValidation_Full_{self.scenario}",
            log_file=full_etl,
            max_file_size_mb=500,
        )
        full_providers = [
            (guid, ALL_KEYWORDS, None) for guid, _ in get_all_provider_pairs()
        ]
        # full 用 Information 级别作为对照（收得全）
        if not self._full_session.start(providers=full_providers, level=4):
            raise RuntimeError("full session 启动失败")

        # 应用黑名单的 session
        self._filtered_session = EtwFileSession(
            session_name=f"FilterValidation_Filtered_{self.scenario}",
            log_file=filtered_etl,
            max_file_size_mb=500,
        )
        filtered_providers = [
            (guid, compute_filtered_keyword(name), ETW_EVENT_ID_WHITELIST.get(name))
            for guid, name in get_all_provider_pairs()
        ]
        if not self._filtered_session.start(providers=filtered_providers, level=ETW_LEVEL):
            self._full_session.stop()
            raise RuntimeError("filtered session 启动失败")

        logger.info(f"[{self.scenario}] 两个 session 已启动")
        for guid, name in get_all_provider_pairs():
            full_kw = ALL_KEYWORDS
            filt_kw = compute_filtered_keyword(name)
            logger.info(
                f"  {name}: full=0x{full_kw:x} filtered=0x{filt_kw:x} "
                f"(过滤掉 0x{(full_kw ^ filt_kw):x})"
            )

    def stop(self):
        """停止两个 session 并返回文件大小"""
        result = {}

        if self._full_session:
            self._full_session.stop()
            full_etl = self.output_dir / "full.etl"
            result["full_bytes"] = full_etl.stat().st_size if full_etl.exists() else 0

        if self._filtered_session:
            self._filtered_session.stop()
            filtered_etl = self.output_dir / "filtered.etl"
            result["filtered_bytes"] = filtered_etl.stat().st_size if filtered_etl.exists() else 0

        return result


def run_experiment(scenario_name: str, warmup_seconds: int,
                   trigger_fn: Callable, wait_after_seconds: int):
    """
    运行一次完整实验。

    Args:
        scenario_name: 场景名（决定输出目录）
        warmup_seconds: 触发前的预热时长
        trigger_fn: 触发异常的函数（无参数）
        wait_after_seconds: 触发后的等待时长（让事件充分产生）
    """
    # 检查管理员权限
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("  ✗ 需要管理员权限")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  场景: {scenario_name}")
    print(f"{'='*60}")

    exp = Experiment(scenario_name)
    exp.start()

    print(f"  预热 {warmup_seconds}s...")
    time.sleep(warmup_seconds)

    print(f"  触发异常...")
    trigger_fn()

    print(f"  等待 {wait_after_seconds}s 让事件产生...")
    time.sleep(wait_after_seconds)

    print(f"  停止 session...")
    result = exp.stop()

    full_mb = result.get("full_bytes", 0) / (1024 * 1024)
    filt_mb = result.get("filtered_bytes", 0) / (1024 * 1024)
    reduction = 100 * (1 - filt_mb / full_mb) if full_mb > 0 else 0

    print(f"\n  结果:")
    print(f"    full.etl:     {full_mb:.1f} MB")
    print(f"    filtered.etl: {filt_mb:.1f} MB  (缩减 {reduction:.0f}%)")
    print(f"    输出目录: {exp.output_dir}")
    print(f"\n  下一步：用 WPA 或 tracerpt 打开两个 .etl 对比事件")

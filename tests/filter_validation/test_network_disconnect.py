"""
实验: 网络断开

假设: 禁用/启用网卡 → 产生 NDIS 链路事件和 TCPIP 连接断开事件
本实验验证：TCPIP 黑名单过滤掉每包 Transfer/SendPath/ReceivePath 后，
连接断开事件（Endpoint/ClosePath）仍然可见

⚠️ 会短暂断网，如果你在下载/联机游戏请先停掉再跑
"""

import sys
import time
import subprocess
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.filter_validation.framework import run_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def _get_active_adapter():
    """获取当前活跃的网络适配器名称"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-NetAdapter -Physical | Where-Object {$_.Status -eq 'Up'} | Select-Object -First 1).Name"],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def trigger_network_disconnect():
    """禁用网卡 3 秒后重新启用"""
    adapter = _get_active_adapter()
    if not adapter:
        print("  ⚠ 找不到活跃网络适配器，跳过")
        return

    print(f"  禁用适配器: {adapter}")
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Disable-NetAdapter -Name '{adapter}' -Confirm:$false"],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    time.sleep(3)
    print(f"  重新启用适配器: {adapter}")
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Enable-NetAdapter -Name '{adapter}' -Confirm:$false"],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )


if __name__ == "__main__":
    print("\n⚠️  此实验会短暂断网 3 秒")
    print("如果你在联机游戏或重要下载中请先停掉，5 秒后开始...")
    time.sleep(5)

    run_experiment(
        scenario_name="network_disconnect",
        warmup_seconds=5,
        trigger_fn=trigger_network_disconnect,
        wait_after_seconds=5,
    )

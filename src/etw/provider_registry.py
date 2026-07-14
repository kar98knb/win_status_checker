"""
Provider 名字 → (guid, keyword, event_id_whitelist) 的解析

集中管理 config 里的过滤配置到 ETW 层的转换，
让 main.py / io_estimate / filter_validation 都能复用同一份逻辑。
"""

from typing import List, Tuple, Optional

from .providers import (
    GUID,
    KERNEL_PROCESS, TCPIP, DXGKRNL,
    KERNEL_PROCESSOR_POWER, KERNEL_PNP,
    KERNEL_DISK_NEW, KERNEL_MEMORY,
    USB_USBPORT, USB_USBHUB3, USB_USBXHCI,
    BTH_PORT, BTH_USB,
    INPUT_HIDCLASS,
    KERNEL_AUDIO, KERNEL_POWER,
)

# provider name → GUID 映射（跟 config 里过滤字典的 key 一致）
PROVIDER_GUIDS = {
    "Kernel-Process":  KERNEL_PROCESS,
    "TCPIP":           TCPIP,
    "DxgKrnl":         DXGKRNL,
    "CPU-Power":       KERNEL_PROCESSOR_POWER,
    "Kernel-PnP":      KERNEL_PNP,
    "Kernel-Disk":     KERNEL_DISK_NEW,
    "Kernel-Memory":   KERNEL_MEMORY,
    "USB-USBPORT":     USB_USBPORT,
    "USB-USBHUB3":     USB_USBHUB3,
    "USB-USBXHCI":     USB_USBXHCI,
    "BTH-BTHPORT":     BTH_PORT,
    "BTH-BTHUSB":      BTH_USB,
    "Input-HIDCLASS":  INPUT_HIDCLASS,
    "Kernel-Audio":    KERNEL_AUDIO,
    "Kernel-Power":    KERNEL_POWER,
}

ALL_KEYWORDS = 0xFFFFFFFFFFFFFFFF


def resolve_provider_entries(
    provider_names: List[str],
    keyword_blacklist: dict,
    event_id_whitelist: Optional[dict] = None,
) -> List[Tuple[GUID, int, Optional[List[int]]]]:
    """
    根据 provider name 列表 + 过滤配置，
    生成 (guid, keyword_mask, event_id_whitelist) 元组列表给 EtwSession.start 用。

    Args:
        provider_names: 要订阅的 provider 名字列表，比如 ["Kernel-Process", "DxgKrnl"]
        keyword_blacklist: config.ETW_KEYWORD_BLACKLIST
        event_id_whitelist: config.ETW_EVENT_ID_WHITELIST。传 None 表示不应用 event id 白名单
            （对 Realtime session 有用：白名单会额外过滤，Realtime 我们要保留全部事件）

    Returns:
        [(guid, keyword_mask, event_ids_or_none), ...]
    """
    entries = []
    for name in provider_names:
        if name not in PROVIDER_GUIDS:
            raise KeyError(f"未知 provider name: {name}")
        guid = PROVIDER_GUIDS[name]

        # 计算 keyword mask：从全 1 里挖掉黑名单里的 bit
        blacklist = keyword_blacklist.get(name, [])
        excluded = 0
        for kw, _, _ in blacklist:
            excluded |= kw
        keyword_mask = ALL_KEYWORDS & (~excluded) & ALL_KEYWORDS

        # event id 白名单只在传入了 dict 时才应用
        if event_id_whitelist is not None:
            eid_whitelist = event_id_whitelist.get(name)  # None 或 list
        else:
            eid_whitelist = None

        entries.append((guid, keyword_mask, eid_whitelist))
    return entries

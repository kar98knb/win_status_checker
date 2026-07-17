"""
provider_registry 单元测试（无需管理员，纯 dict/位运算）
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.etw.provider_registry import (
    PROVIDER_GUIDS,
    ALL_KEYWORDS,
    resolve_provider_entries,
)


class TestResolveProviderEntries(unittest.TestCase):

    def test_unknown_provider_raises(self):
        with self.assertRaises(KeyError):
            resolve_provider_entries(["No-Such-Provider"], {}, None)

    def test_empty_blacklist_keeps_all_keywords(self):
        entries = resolve_provider_entries(["Kernel-Process"], {}, None)
        self.assertEqual(len(entries), 1)
        guid, kw, eids = entries[0]
        self.assertEqual(kw, ALL_KEYWORDS)
        self.assertIsNone(eids)

    def test_blacklist_bits_are_cleared(self):
        blacklist = {
            "Kernel-Process": [
                (0b0000_0001, "kw1", "reason1"),
                (0b0001_0000, "kw2", "reason2"),
            ],
        }
        entries = resolve_provider_entries(["Kernel-Process"], blacklist, None)
        _, kw, _ = entries[0]
        # 黑名单 bit 0 和 bit 4 应该被 mask 掉
        self.assertEqual(kw & 0b0001_0001, 0)
        # 其他 bit 应该保留
        self.assertEqual(kw & 0b1110_1110, 0b1110_1110)

    def test_event_id_whitelist_none_ignored(self):
        entries = resolve_provider_entries(
            ["DxgKrnl"], {}, event_id_whitelist=None
        )
        _, _, eids = entries[0]
        self.assertIsNone(eids)

    def test_event_id_whitelist_applied(self):
        entries = resolve_provider_entries(
            ["DxgKrnl"],
            {},
            event_id_whitelist={"DxgKrnl": [540, 541, 547, 548]},
        )
        _, _, eids = entries[0]
        self.assertEqual(eids, [540, 541, 547, 548])

    def test_event_id_whitelist_missing_provider_gets_none(self):
        # DxgKrnl 不在白名单 dict 里 → eids 应为 None（不加过滤）
        entries = resolve_provider_entries(
            ["DxgKrnl"], {}, event_id_whitelist={"OtherProvider": [1, 2]}
        )
        _, _, eids = entries[0]
        self.assertIsNone(eids)

    def test_multiple_providers_preserve_order(self):
        names = ["Kernel-Process", "DxgKrnl", "TCPIP"]
        entries = resolve_provider_entries(names, {}, None)
        got_guids = [e[0] for e in entries]
        expected_guids = [PROVIDER_GUIDS[n] for n in names]
        # GUID 是 ctypes.Structure，用 str 比较（内容一致就相等）
        self.assertEqual(
            [str(g) for g in got_guids],
            [str(g) for g in expected_guids],
        )


if __name__ == "__main__":
    unittest.main()

"""
GUID 结构体单元测试（无需管理员）
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.etw.providers import GUID


# 用一个已知的 provider GUID 做参考: Kernel-Process
# {22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}
KP_STR = "{22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}"


class TestGUIDParsing(unittest.TestCase):

    def test_parses_with_braces(self):
        g = GUID("{22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}")
        self.assertEqual(g.Data1, 0x22FB2CD6)
        self.assertEqual(g.Data2, 0x0E7B)
        self.assertEqual(g.Data3, 0x422B)

    def test_parses_without_braces(self):
        g = GUID("22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716")
        self.assertEqual(g.Data1, 0x22FB2CD6)

    def test_parses_uppercase(self):
        g_lower = GUID("{22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}")
        g_upper = GUID("{22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}")
        self.assertEqual(str(g_lower), str(g_upper))

    def test_data4_byte_order_matches_hex_string(self):
        """
        Data4 的字节序应该保持 hex string 顺序，不是 little-endian 反转。
        这是踩过的坑：如果反了，EnableTraceEx2 找不到 provider。
        """
        g = GUID(KP_STR)
        # "a0c7-2fad1fd0e716" → 一共 16 位 hex = 8 字节
        expected = bytes.fromhex("a0c72fad1fd0e716")
        got = bytes(g.Data4)
        self.assertEqual(got, expected)

    def test_str_roundtrip(self):
        """GUID → str → GUID → str 应保持不变"""
        g1 = GUID(KP_STR)
        s1 = str(g1)
        g2 = GUID(s1)
        s2 = str(g2)
        self.assertEqual(s1, s2)
        self.assertEqual(s1, KP_STR)

    def test_str_format(self):
        g = GUID(KP_STR)
        s = str(g)
        # 格式: {8-4-4-4-12}
        self.assertTrue(s.startswith("{") and s.endswith("}"))
        core = s[1:-1]
        parts = core.split("-")
        self.assertEqual([len(p) for p in parts], [8, 4, 4, 4, 12])


if __name__ == "__main__":
    unittest.main()

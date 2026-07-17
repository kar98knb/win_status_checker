"""
_alloc_properties 单元测试（无需管理员，仅内存拼装）

_alloc_properties 是变长结构体 EVENT_TRACE_PROPERTIES 的分配器，
布局是 [PROPERTIES][LogFileName wchar_t[]][LoggerName wchar_t[]]。
如果 offset 算错，Windows 收到就报 87 (INVALID_PARAMETER)。
"""

import ctypes
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.etw.session import _alloc_properties, EVENT_TRACE_PROPERTIES


def _read_wstr(buf, offset):
    """从 ctypes buffer 的指定 offset 读一个以 \\0 结尾的 UTF-16 字符串"""
    addr = ctypes.addressof(buf) + offset
    return ctypes.wstring_at(addr)


class TestAllocProperties(unittest.TestCase):

    def test_without_file_name(self):
        """不传 file_name: LogFileNameOffset==0, LoggerName 紧跟结构体"""
        name = "MySession"
        buf, props = _alloc_properties(name)
        p = props.contents

        # LogFileNameOffset 应为 0（不用文件）
        self.assertEqual(p.LogFileNameOffset, 0)

        # LoggerNameOffset 应该正好是结构体大小
        self.assertEqual(p.LoggerNameOffset, ctypes.sizeof(EVENT_TRACE_PROPERTIES))

        # 从 buffer 里读回 session name 应该一致
        self.assertEqual(_read_wstr(buf, p.LoggerNameOffset), name)

        # BufferSize 至少要能容纳 [PROPERTIES][name + \0]
        wchar = ctypes.sizeof(ctypes.c_wchar)
        expected_min = ctypes.sizeof(EVENT_TRACE_PROPERTIES) + (len(name) + 1) * wchar
        self.assertEqual(p.Wnode.BufferSize, expected_min)

    def test_with_file_name(self):
        """传 file_name: LogFileName 紧跟结构体, LoggerName 再跟其后"""
        name = "MySession"
        fp = r"C:\tmp\test.etl"
        buf, props = _alloc_properties(name, fp)
        p = props.contents

        # LogFileNameOffset 应该是 sizeof(EVENT_TRACE_PROPERTIES)
        self.assertEqual(p.LogFileNameOffset, ctypes.sizeof(EVENT_TRACE_PROPERTIES))

        wchar = ctypes.sizeof(ctypes.c_wchar)
        expected_logger_offset = (
            ctypes.sizeof(EVENT_TRACE_PROPERTIES) + (len(fp) + 1) * wchar
        )
        self.assertEqual(p.LoggerNameOffset, expected_logger_offset)

        # 读回两个字符串验证
        self.assertEqual(_read_wstr(buf, p.LogFileNameOffset), fp)
        self.assertEqual(_read_wstr(buf, p.LoggerNameOffset), name)

    def test_buffer_is_zero_initialized(self):
        """新分配的 buffer 除了我们主动写入的字段外，应全部为 0"""
        buf, props = _alloc_properties("S", r"C:\a.etl")
        p = props.contents
        # 输出字段应为 0
        self.assertEqual(p.NumberOfBuffers, 0)
        self.assertEqual(p.EventsLost, 0)
        self.assertEqual(p.BuffersWritten, 0)
        # LogFileMode 我们没设，应为 0
        self.assertEqual(p.LogFileMode, 0)

    def test_unicode_session_name(self):
        """Session name 是 UTF-16，中文应能正确 roundtrip"""
        name = "监控会话"
        buf, props = _alloc_properties(name)
        self.assertEqual(_read_wstr(buf, props.contents.LoggerNameOffset), name)


if __name__ == "__main__":
    unittest.main()

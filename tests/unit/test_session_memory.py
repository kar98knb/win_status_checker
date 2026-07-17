"""ETW ctypes 内存布局测试；不启动 session，无需管理员。"""
import ctypes
import unittest

from src.etw.session import (
    ENABLE_TRACE_PARAMETERS_VERSION_2,
    EVENT_FILTER_EVENT_ID_HEADER,
    EVENT_FILTER_TYPE_EVENT_ID,
    EtwFileSession,
)


class TestEventIdFilterLayout(unittest.TestCase):
    def setUp(self):
        self.session = EtwFileSession()

    def test_filter_layout_and_pointer_chain(self):
        ids = [1, 2, 540]
        refs = self.session._build_event_id_filter(ids)
        header = ctypes.cast(refs["filter_buf"], ctypes.POINTER(EVENT_FILTER_EVENT_ID_HEADER)).contents
        desc, params = refs["filter_desc"], refs["params"]
        self.assertEqual((header.FilterIn, header.Reserved, header.Count), (1, 0, len(ids)))
        array_type = ctypes.c_ushort * len(ids)
        offset = ctypes.sizeof(EVENT_FILTER_EVENT_ID_HEADER)
        values = ctypes.cast(ctypes.addressof(refs["filter_buf"]) + offset, ctypes.POINTER(array_type)).contents
        self.assertEqual(list(values), ids)
        self.assertEqual(desc.Ptr, ctypes.addressof(refs["filter_buf"]))
        self.assertEqual((desc.Size, desc.Type), (offset + len(ids) * 2, EVENT_FILTER_TYPE_EVENT_ID))
        self.assertEqual((params.Version, params.FilterDescCount), (ENABLE_TRACE_PARAMETERS_VERSION_2, 1))

    def test_more_than_64_ids_rejected(self):
        with self.assertRaises(ValueError):
            self.session._build_event_id_filter(list(range(65)))

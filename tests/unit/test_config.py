"""生产配置自洽性测试；无需管理员。"""
import unittest

from config import (
    ETW_EVENT_ID_WHITELIST,
    ETW_FILE_SESSION_PROVIDERS,
    ETW_KEYWORD_BLACKLIST,
    ETW_REALTIME_PROVIDERS,
)
from src.etw.provider_registry import PROVIDER_GUIDS
from src.etw.session import EtwFileSession


class TestEtwConfig(unittest.TestCase):
    def test_all_configured_providers_are_registered(self):
        configured = (
            set(ETW_FILE_SESSION_PROVIDERS)
            | set(ETW_REALTIME_PROVIDERS)
            | set(ETW_EVENT_ID_WHITELIST)
            | set(ETW_KEYWORD_BLACKLIST)
        )
        self.assertEqual(configured - set(PROVIDER_GUIDS), set())

    def test_session_provider_groups_do_not_overlap(self):
        overlap = set(ETW_FILE_SESSION_PROVIDERS) & set(ETW_REALTIME_PROVIDERS)
        self.assertEqual(overlap, set())

    def test_event_id_whitelists_respect_windows_limit(self):
        limit = EtwFileSession.MAX_EVENT_FILTER_EVENT_ID_COUNT
        too_long = {name: len(ids) for name, ids in ETW_EVENT_ID_WHITELIST.items() if len(ids) > limit}
        self.assertEqual(too_long, {})

    def test_event_ids_are_valid_unique_ushorts(self):
        for name, ids in ETW_EVENT_ID_WHITELIST.items():
            with self.subTest(provider=name):
                self.assertEqual(len(ids), len(set(ids)))
                self.assertTrue(all(isinstance(event_id, int) and 0 <= event_id <= 0xFFFF for event_id in ids))

    def test_keyword_blacklist_entries_are_valid(self):
        for name, entries in ETW_KEYWORD_BLACKLIST.items():
            with self.subTest(provider=name):
                for keyword, label, reason in entries:
                    self.assertTrue(0 <= keyword <= 0xFFFFFFFFFFFFFFFF)
                    self.assertTrue(label)
                    self.assertTrue(reason)

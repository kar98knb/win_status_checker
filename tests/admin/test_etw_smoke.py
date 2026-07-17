"""需要管理员权限的 ETW 集成 smoke test。"""
import ctypes
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from src.etw.provider_registry import ALL_KEYWORDS
from src.etw.providers import KERNEL_PROCESS
from src.etw.session import EtwBufferSession, EtwFileSession


def _is_admin() -> bool:
    return sys.platform == "win32" and bool(ctypes.windll.shell32.IsUserAnAdmin())


@unittest.skipUnless(_is_admin(), "需要管理员权限控制 ETW session")
class TestEtwPipeline(unittest.TestCase):
    def test_dual_session_produces_valid_etl(self):
        suffix = f"{os.getpid()}_{int(time.time())}"

        with tempfile.TemporaryDirectory(prefix="wsc_test_") as temp:
            temp_dir = Path(temp)
            keyevents = temp_dir / "keyevents.etl"
            snapshot = temp_dir / "snap.etl"
            file_session = EtwFileSession(
                session_name=f"WSC_TestFile_{suffix}",
                log_file=keyevents,
                max_file_size_mb=16,
            )
            buffer_session = EtwBufferSession(
                session_name=f"WSC_TestBuffer_{suffix}", buffer_size_mb=16
            )

            file_started = buffer_started = False
            try:
                file_started = file_session.start(
                    [(KERNEL_PROCESS, ALL_KEYWORDS, [1, 2])], level=4
                )
                self.assertTrue(file_started)
                buffer_started = buffer_session.start(
                    [(KERNEL_PROCESS, ALL_KEYWORDS, None)], level=4
                )
                self.assertTrue(buffer_started)

                # 制造可预测的 ProcessStart/ProcessStop 事件。
                subprocess.run([sys.executable, "-c", "pass"], check=True)
                time.sleep(0.5)

                ok, status = buffer_session.flush_to_etl(snapshot)
                self.assertTrue(ok, f"Buffer session flush 失败: {status}")
            finally:
                if buffer_started:
                    buffer_session.stop()
                if file_started:
                    file_session.stop()

            self.assertGreater(snapshot.stat().st_size, 0)
            self.assertGreater(keyevents.stat().st_size, 0)
            self._assert_tracerpt_accepts(snapshot, temp_dir / "snap")
            self._assert_tracerpt_accepts(keyevents, temp_dir / "keyevents")

    def _assert_tracerpt_accepts(self, etl: Path, prefix: Path):
        summary = prefix.with_suffix(".summary.txt")
        dump = prefix.with_suffix(".xml")
        result = subprocess.run(
            ["tracerpt.exe", str(etl), "-summary", str(summary),
             "-o", str(dump), "-y"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertTrue(summary.exists())

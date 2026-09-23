import unittest
from audio_manager import AudioManager
from tools import dispatch_tool


class TestJarvisCore(unittest.TestCase):
    def test_audio_manager_basic(self):
        mgr = AudioManager()
        self.assertFalse(mgr.is_running)
        self.assertFalse(mgr.is_speaking())
        mgr.is_running = True
        mgr.queue_output(b"\x00" * 2048)
        self.assertTrue(mgr.is_speaking())
        mgr.flush_output()
        self.assertFalse(mgr.is_speaking())

    def test_tools_system_vitals(self):
        res = dispatch_tool("get_current_time", {})
        self.assertIn("result", res)


if __name__ == "__main__":
    unittest.main()

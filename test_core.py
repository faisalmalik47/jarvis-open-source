import unittest
from audio_manager import AudioManager
from tools import dispatch_tool
from jarvis import contains_wake_word


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

    def test_wake_word_filter(self):
        # Must return True when addressed as Jarvis
        self.assertTrue(contains_wake_word("Jarvis, what is my CPU load?"))
        self.assertTrue(contains_wake_word("hey jarvis, check system"))
        self.assertTrue(contains_wake_word("OK JARVIS, turn off dark mode"))
        self.assertTrue(contains_wake_word("Hello J.A.R.V.I.S."))

        # Must return False when talking generally or ambient noise
        self.assertFalse(contains_wake_word("What movie are we watching?"))
        self.assertFalse(contains_wake_word("Can you pass the salt please?"))
        self.assertFalse(contains_wake_word("Darvesh badhiya"))
        self.assertFalse(contains_wake_word("Come stai?"))
        self.assertFalse(contains_wake_word(""))


if __name__ == "__main__":
    unittest.main()

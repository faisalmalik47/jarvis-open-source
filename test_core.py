import unittest
import time
from jarvis import WakeWordGate, TurnState
from audio_manager import AudioManager


class TestJarvisCore(unittest.TestCase):
    def test_wakeword_gate_standby(self):
        gate = WakeWordGate(timeout_sec=1.0)
        self.assertFalse(gate.is_active())
        self.assertEqual(gate.state, "STANDBY")

        # Non-wake phrases should not trigger
        self.assertFalse(gate.check_wake_word("What is the weather today?"))
        self.assertFalse(gate.check_wake_word("Can you pass the salt please?"))
        self.assertFalse(gate.check_wake_word("Hello there"))

        # Wake phrases should trigger
        self.assertTrue(gate.check_wake_word("Jarvis, what's my CPU?"))
        self.assertTrue(gate.check_wake_word("hey jarvis"))
        self.assertTrue(gate.check_wake_word("OK JARVIS check battery"))
        self.assertTrue(gate.check_wake_word("Is J.A.R.V.I.S. online?"))

    def test_wakeword_gate_activation_and_timeout(self):
        gate = WakeWordGate(timeout_sec=0.2)
        gate.activate("test")
        self.assertTrue(gate.is_active())
        self.assertEqual(gate.state, "ACTIVE")

        # Sleep past timeout
        time.sleep(0.3)
        self.assertFalse(gate.is_active())
        self.assertEqual(gate.state, "STANDBY")

    def test_turn_state_reset(self):
        ts = TurnState()
        self.assertFalse(ts.interrupted)
        self.assertFalse(ts.suppressed)

        ts.interrupted = True
        ts.suppressed = True
        ts.reset_for_turn()

        self.assertFalse(ts.interrupted)
        self.assertFalse(ts.suppressed)

    def test_audio_manager_flush(self):
        mgr = AudioManager()
        mgr.is_running = True
        mgr.queue_output(b"\x00" * 4096)
        self.assertTrue(mgr.is_speaking())
        mgr.flush_output()
        self.assertFalse(mgr.is_playing)
        self.assertEqual(len(mgr._output_buffer), 0)


if __name__ == "__main__":
    unittest.main()

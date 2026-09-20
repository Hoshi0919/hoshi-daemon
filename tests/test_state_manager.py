import sqlite3
import unittest
import tempfile
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from state_manager import StateManager

class TestStateManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.tmpdir.name) / "state.json"
        self.sm = StateManager(self.state_file)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_initial_state(self):
        self.assertEqual(self.sm.state["last_wake_timestamp"], 0)
        self.assertEqual(self.sm.state["wakes_today"], 0)

    def test_cooldown(self):
        can, reason = self.sm.can_wake(cooldown_seconds=100, max_wakes_per_day=10)
        self.assertTrue(can)

        self.sm.record_wake()
        can, reason = self.sm.can_wake(cooldown_seconds=100, max_wakes_per_day=10)
        self.assertFalse(can)
        self.assertIn("In cooldown", reason)

    def test_pause_file(self):
        pause = Path(self.tmpdir.name) / "PAUSE"
        pause.write_text("1")
        can, reason = self.sm.can_wake(cooldown_seconds=0, max_wakes_per_day=10, pause_file=pause)
        self.assertFalse(can)
        self.assertIn("Paused", reason)

    def test_mark_seen(self):
        self.assertFalse(self.sm.is_seen("github", "123"))
        self.sm.mark_seen("github", "123")
        self.assertTrue(self.sm.is_seen("github", "123"))
        # Reload state from disk to ensure persistence
        sm2 = StateManager(self.state_file)
        self.assertTrue(sm2.is_seen("github", "123"))

    def test_active_session_blocks_wake(self):
        db_path = Path(self.tmpdir.name) / "state.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL NOT NULL, ended_at REAL, last_activity_at REAL)")
        now = time.time()
        conn.execute("INSERT INTO sessions VALUES ('s1', ?, NULL, ?)", (now - 30, now - 10))
        conn.commit()
        conn.close()

        can, reason = self.sm.can_wake(cooldown_seconds=0, max_wakes_per_day=10, db_path=db_path)
        self.assertFalse(can)
        self.assertIn("currently active", reason)

        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE sessions SET ended_at = ? WHERE id = 's1'", (now - 5,))
        conn.commit()
        conn.close()

        can2, reason2 = self.sm.can_wake(cooldown_seconds=0, max_wakes_per_day=10, db_path=db_path)
        self.assertTrue(can2)
        self.assertEqual(reason2, "OK")

if __name__ == "__main__":
    unittest.main()

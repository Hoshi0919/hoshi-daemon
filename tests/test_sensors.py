import sqlite3
import unittest
from unittest.mock import patch, MagicMock
import tempfile
import time
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from state_manager import StateManager
from sensors import TaskSensor, HeartbeatSensor, GitHubSensor, EmailSensor, Event
from dispatcher import Dispatcher

class TestSensorsAndDispatcher(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.sm = StateManager(self.tmp_path / "state.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_task_sensor(self):
        tasks_dir = self.tmp_path / "tasks"
        tasks_dir.mkdir()
        sensor = TaskSensor(tasks_dir)
        self.assertEqual(len(sensor.poll()), 0)

        task_file = tasks_dir / "audit.task"
        task_file.write_text("Run audit on recent session logs.")
        events = sensor.poll()
        self.assertEqual(len(events), 1)
        self.assertIn("audit.task", events[0].title)
        self.assertIn("Run audit", events[0].details)

    def test_heartbeat_sensor(self):
        sensor = HeartbeatSensor(self.sm, interval_seconds=50)
        # initial last_wake is 0, should report initial wake
        events = sensor.poll()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source, "heartbeat")
        self.assertIn("Initial heartbeat wake", events[0].details)

        # After wake recorded recently
        self.sm.record_wake()
        events2 = sensor.poll()
        self.assertEqual(len(events2), 0)

        # After interval elapsed
        self.sm.state["last_wake_timestamp"] = time.time() - 120
        events3 = sensor.poll()
        self.assertEqual(len(events3), 1)
        self.assertIn("No activity for 2 minutes", events3[0].details)

    def test_heartbeat_sensor_respects_db_activity(self):
        db_path = self.tmp_path / "state.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL NOT NULL, last_activity_at REAL)")
        now = time.time()
        conn.execute("INSERT INTO sessions VALUES ('s1', ?, ?)", (now - 30, now - 10))
        conn.commit()
        conn.close()

        self.sm.state["last_wake_timestamp"] = now - 200
        sensor = HeartbeatSensor(self.sm, interval_seconds=50, db_path=str(db_path))

        events = sensor.poll()
        self.assertEqual(len(events), 0)

        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE sessions SET last_activity_at = ?", (now - 120,))
        conn.commit()
        conn.close()

        events2 = sensor.poll()
        self.assertEqual(len(events2), 1)
        self.assertIn("No activity for 2 minutes", events2[0].details)

    @patch("subprocess.run")
    def test_github_sensor_success(self, mock_run):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = '[{"id": "gh_101", "repository": {"full_name": "Hoshi0919/test"}, "subject": {"title": "Test Issue"}, "reason": "mention"}]'
        mock_run.return_value = mock_res

        sensor = GitHubSensor(self.sm, error_cooldown=60)
        self.assertTrue(sensor.is_healthy)
        events = sensor.poll()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source, "github")
        self.assertEqual(events[0].item_id, "gh_101")
        self.assertIn("Hoshi0919/test", events[0].title)
        self.assertTrue(sensor.is_healthy)

    @patch("subprocess.run")
    def test_github_sensor_backoff_on_error(self, mock_run):
        mock_res = MagicMock()
        mock_res.returncode = 1
        mock_res.stdout = ""
        mock_run.return_value = mock_res

        sensor = GitHubSensor(self.sm, error_cooldown=60)
        events = sensor.poll()
        self.assertEqual(len(events), 0)
        self.assertFalse(sensor.is_healthy)
        self.assertEqual(sensor.consecutive_failures, 1)

        # Second poll immediately afterwards should skip subprocess.run due to backoff
        mock_run.reset_mock()
        events2 = sensor.poll()
        self.assertEqual(len(events2), 0)
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_email_sensor_success(self, mock_run):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = '[{"id": "em_202", "isRead": false, "subject": "Hello Hoshi", "from": {"emailAddress": {"address": "friend@example.com"}}, "receivedDateTime": "2026-09-21T22:00:00Z"}]'
        mock_run.return_value = mock_res

        sensor = EmailSensor(self.sm, error_cooldown=60)
        self.assertTrue(sensor.is_healthy)
        events = sensor.poll()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source, "email")
        self.assertEqual(events[0].item_id, "em_202")
        self.assertIn("friend@example.com", events[0].title)
        self.assertTrue(sensor.is_healthy)

    @patch("subprocess.run")
    def test_email_sensor_backoff_and_recovery(self, mock_run):
        # 1. Error state
        fail_res = MagicMock()
        fail_res.returncode = 1
        fail_res.stdout = "Auth error"
        mock_run.return_value = fail_res

        sensor = EmailSensor(self.sm, error_cooldown=10)
        events = sensor.poll()
        self.assertEqual(len(events), 0)
        self.assertFalse(sensor.is_healthy)
        self.assertEqual(sensor.consecutive_failures, 1)

        # Fast call skipped
        mock_run.reset_mock()
        self.assertEqual(len(sensor.poll()), 0)
        mock_run.assert_not_called()

        # 2. Advance past backoff window
        sensor.last_failure_time = time.time() - 20
        ok_res = MagicMock()
        ok_res.returncode = 0
        ok_res.stdout = "[]"
        mock_run.return_value = ok_res

        events2 = sensor.poll()
        self.assertEqual(len(events2), 0)
        self.assertTrue(sensor.is_healthy)
        self.assertEqual(sensor.consecutive_failures, 0)

    def test_dispatcher_formatting(self):
        disp = Dispatcher(self.sm, self.tmp_path / "test.log", dry_run=True)
        events = [
            Event(source="github", item_id="1", title="New Issue #4", details="Bug in parser"),
            Event(source="heartbeat", item_id="hb_1", title="Periodic Heartbeat", details="Time to reflect")
        ]
        prompt = disp.format_wake_prompt(events)
        self.assertIn("【Hoshi 自主神经感知唤醒】", prompt)
        self.assertIn("[GITHUB] New Issue #4", prompt)
        self.assertIn("Periodic Heartbeat", prompt)

        ok = disp.dispatch(events)
        self.assertTrue(ok)
        self.assertEqual(self.sm.state["wakes_today"], 1)
        self.assertTrue(self.sm.is_seen("github", "1"))

    def test_dispatcher_no_duplicate_log_when_stdout_redirected(self):
        log_file = self.tmp_path / "redir.log"
        disp = Dispatcher(self.sm, log_file, dry_run=True)
        # Simulate stdout redirection as in daemon mode
        with open(log_file, "a") as f:
            saved_stdout = os.dup(sys.stdout.fileno())
            try:
                os.dup2(f.fileno(), sys.stdout.fileno())
                disp.log("Single line test")
            finally:
                os.dup2(saved_stdout, sys.stdout.fileno())
        content = log_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("Single line test"), 1)

if __name__ == "__main__":
    unittest.main()

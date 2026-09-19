import unittest
import tempfile
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from state_manager import StateManager
from sensors import TaskSensor, HeartbeatSensor, Event
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
        # initial last_wake is 0, elapsed >> 50
        events = sensor.poll()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source, "heartbeat")

        # After wake recorded recently
        self.sm.record_wake()
        events2 = sensor.poll()
        self.assertEqual(len(events2), 0)

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

if __name__ == "__main__":
    unittest.main()

import sqlite3
import json
import subprocess
import time
from pathlib import Path

class Event:
    def __init__(self, source, item_id, title, details=""):
        self.source = source
        self.item_id = str(item_id)
        self.title = title
        self.details = details
        self.timestamp = time.time()

    def to_dict(self):
        return {
            "source": self.source,
            "item_id": self.item_id,
            "title": self.title,
            "details": self.details,
            "timestamp": self.timestamp
        }

    def __repr__(self):
        return f"<Event {self.source}:{self.title}>"


class GitHubSensor:
    def __init__(self, state_manager, error_cooldown=60):
        self.sm = state_manager
        self.error_cooldown = error_cooldown
        self.last_failure_time = 0
        self.consecutive_failures = 0

    @property
    def is_healthy(self):
        return self.consecutive_failures == 0

    def poll(self):
        now = time.time()
        if self.consecutive_failures > 0:
            backoff = min(self.error_cooldown * (2 ** (self.consecutive_failures - 1)), 1800)
            if now - self.last_failure_time < backoff:
                return []

        events = []
        try:
            cmd = ["gh", "api", "notifications", "--jq", ".[0:10]"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                self.consecutive_failures = 0
                if res.stdout.strip():
                    items = json.loads(res.stdout)
                    if isinstance(items, list):
                        for item in items:
                            item_id = str(item.get("id"))
                            if not self.sm.is_seen("github", item_id):
                                repo = item.get("repository", {}).get("full_name", "unknown")
                                subject = item.get("subject", {}).get("title", "No Title")
                                reason = item.get("reason", "unknown")
                                events.append(Event(
                                    source="github",
                                    item_id=item_id,
                                    title=f"GitHub [{repo}]: {subject}",
                                    details=f"Reason: {reason}"
                                ))
            else:
                self.consecutive_failures += 1
                self.last_failure_time = now
        except Exception:
            self.consecutive_failures += 1
            self.last_failure_time = now
        return events


class EmailSensor:
    def __init__(self, state_manager, error_cooldown=60):
        self.sm = state_manager
        self.error_cooldown = error_cooldown
        self.last_failure_time = 0
        self.consecutive_failures = 0

    @property
    def is_healthy(self):
        return self.consecutive_failures == 0

    def poll(self):
        now = time.time()
        if self.consecutive_failures > 0:
            backoff = min(self.error_cooldown * (2 ** (self.consecutive_failures - 1)), 1800)
            if now - self.last_failure_time < backoff:
                return []

        events = []
        try:
            cmd = ["m365", "mail", "list", "--top", "3", "--json"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                self.consecutive_failures = 0
                if res.stdout.strip():
                    data = json.loads(res.stdout)
                    if isinstance(data, list):
                        for msg in data:
                            msg_id = msg.get("id")
                            is_read = msg.get("isRead", True)
                            if msg_id and not is_read:
                                if not self.sm.is_seen("email", msg_id):
                                    subject = msg.get("subject", "No subject")
                                    sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
                                    events.append(Event(
                                        source="email",
                                        item_id=msg_id,
                                        title=f"New Email from {sender}: {subject}",
                                        details=f"Received: {msg.get('receivedDateTime')}"
                                    ))
            else:
                self.consecutive_failures += 1
                self.last_failure_time = now
        except Exception:
            self.consecutive_failures += 1
            self.last_failure_time = now
        return events


class TaskSensor:
    def __init__(self, tasks_dir, state_manager=None):
        self.tasks_dir = Path(tasks_dir)
        self.sm = state_manager

    def poll(self):
        events = []
        if not self.tasks_dir.exists():
            return events

        for p in self.tasks_dir.glob("*.task"):
            try:
                item_id = f"task_{p.stem}"
                if self.sm and self.sm.is_seen("task", item_id):
                    continue
                content = p.read_text(encoding="utf-8").strip()
                events.append(Event(
                    source="task",
                    item_id=item_id,
                    title=f"Pending Task: {p.name}",
                    details=content[:200]
                ))
            except Exception:
                pass
        return events


class HeartbeatSensor:
    def __init__(self, state_manager, interval_seconds, db_path=None):
        self.sm = state_manager
        self.interval = interval_seconds
        self.db_path = Path(db_path) if db_path else None

    def get_latest_db_activity(self):
        if not self.db_path or not self.db_path.exists():
            return 0
        try:
            conn = sqlite3.connect(str(self.db_path))
            cur = conn.cursor()
            val = cur.execute("SELECT MAX(COALESCE(last_activity_at, started_at, 0)) FROM sessions").fetchone()[0]
            conn.close()
            return float(val or 0)
        except Exception:
            return 0

    def poll(self):
        last_wake = self.sm.state.get("last_wake_timestamp", 0)
        db_act = self.get_latest_db_activity()
        effective_last_wake = max(last_wake, db_act)

        now = time.time()
        if effective_last_wake <= 0:
            return [Event(
                source="heartbeat",
                item_id=f"hb_{int(now)}",
                title="Rhythm Heartbeat",
                details="Initial heartbeat wake (daemon start or state initialized)."
            )]
        elapsed = now - effective_last_wake
        if elapsed >= self.interval:
            return [Event(
                source="heartbeat",
                item_id=f"hb_{int(now)}",
                title="Rhythm Heartbeat",
                details=f"No activity for {int(elapsed / 60)} minutes. Periodic autonomous reflection."
            )]
        return []

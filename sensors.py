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
    def __init__(self, state_manager):
        self.sm = state_manager

    def poll(self):
        events = []
        try:
            cmd = ["gh", "api", "notifications", "--jq", ".[0:10]"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout.strip():
                items = json.loads(res.stdout)
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
        except Exception as e:
            pass
        return events


class EmailSensor:
    def __init__(self, state_manager):
        self.sm = state_manager

    def poll(self):
        events = []
        try:
            cmd = ["m365", "mail", "list", "--top", "3", "--json"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout.strip():
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
        except Exception:
            pass
        return events


class TaskSensor:
    def __init__(self, tasks_dir):
        self.tasks_dir = Path(tasks_dir)

    def poll(self):
        events = []
        if not self.tasks_dir.exists():
            return events

        for p in self.tasks_dir.glob("*.task"):
            try:
                content = p.read_text(encoding="utf-8").strip()
                item_id = f"task_{p.stem}"
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
    def __init__(self, state_manager, interval_seconds):
        self.sm = state_manager
        self.interval = interval_seconds

    def poll(self):
        last_wake = self.sm.state.get("last_wake_timestamp", 0)
        elapsed = time.time() - last_wake
        if elapsed >= self.interval:
            return [Event(
                source="heartbeat",
                item_id=f"hb_{int(time.time())}",
                title="Rhythm Heartbeat",
                details=f"No activity for {int(elapsed / 60)} minutes. Periodic autonomous reflection."
            )]
        return []

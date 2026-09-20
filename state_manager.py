import sqlite3
import json
import os
import time
from pathlib import Path

class StateManager:
    def __init__(self, state_path):
        self.state_path = Path(state_path)
        self.state = {
            "last_wake_timestamp": 0,
            "seen_github_ids": [],
            "seen_email_ids": [],
            "wakes_today": 0,
            "wakes_date": "",
            "last_check_timestamp": 0
        }
        self.load()

    def load(self):
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.state.update(data)
            except Exception:
                pass

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)
        tmp_path.replace(self.state_path)

    def can_wake(self, cooldown_seconds, max_wakes_per_day, pause_file=None, db_path=None):
        if pause_file and Path(pause_file).exists():
            return False, "Paused by pause file"

        now = time.time()
        today = time.strftime("%Y-%m-%d", time.localtime(now))

        if self.state.get("wakes_date") != today:
            self.state["wakes_date"] = today
            self.state["wakes_today"] = 0

        if self.state.get("wakes_today", 0) >= max_wakes_per_day:
            return False, f"Daily wake limit ({max_wakes_per_day}) reached"

        elapsed = now - self.state.get("last_wake_timestamp", 0)
        if elapsed < cooldown_seconds:
            return False, f"In cooldown ({int(cooldown_seconds - elapsed)}s remaining)"

        if db_path and Path(db_path).exists():
            try:
                conn = sqlite3.connect(str(db_path))
                cur = conn.cursor()
                active_count = cur.execute(
                    "SELECT count(*) FROM sessions WHERE ended_at IS NULL AND (? - COALESCE(last_activity_at, started_at, 0)) < 120",
                    (now,)
                ).fetchone()[0]
                conn.close()
                if active_count > 0:
                    return False, f"Hermes session currently active ({active_count} active)"
            except Exception:
                pass

        return True, "OK"

    def record_wake(self):
        now = time.time()
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if self.state.get("wakes_date") != today:
            self.state["wakes_date"] = today
            self.state["wakes_today"] = 0
        self.state["wakes_today"] = self.state.get("wakes_today", 0) + 1
        self.state["last_wake_timestamp"] = now
        self.save()

    def is_seen(self, kind, item_id):
        key = f"seen_{kind}_ids"
        return item_id in self.state.get(key, [])

    def mark_seen(self, kind, item_id, max_keep=200):
        key = f"seen_{kind}_ids"
        ids = self.state.setdefault(key, [])
        if item_id not in ids:
            ids.append(item_id)
            if len(ids) > max_keep:
                self.state[key] = ids[-max_keep:]
            self.save()

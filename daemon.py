#!/usr/bin/env python3
import argparse
import os
import signal
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from state_manager import StateManager
from sensors import GitHubSensor, EmailSensor, TaskSensor, HeartbeatSensor
from dispatcher import Dispatcher

PID_FILE = BASE_DIR / "daemon.pid"
LOG_FILE = BASE_DIR / "daemon.log"
STATE_FILE = BASE_DIR / "state.json"
PAUSE_FILE = BASE_DIR / "PAUSE"
TASKS_DIR = Path("/hoshi/tasks")

CONFIG = {
    "check_interval": 30,         # poll sensors every 30 seconds
    "cooldown_seconds": 600,       # 10 minutes between wakes
    "heartbeat_interval": 7200,    # 2 hours without events -> wake
    "max_wakes_per_day": 24,       # max wakes in 24 hours
}

def get_sensors(sm):
    return [
        GitHubSensor(sm),
        EmailSensor(sm),
        TaskSensor(TASKS_DIR),
        HeartbeatSensor(sm, CONFIG["heartbeat_interval"])
    ]

def run_loop(dry_run=False):
    sm = StateManager(STATE_FILE)
    dispatcher = Dispatcher(sm, LOG_FILE, dry_run=dry_run)
    sensors = get_sensors(sm)

    dispatcher.log("Hoshi Autonomic Daemon started.")

    running = True
    def handle_signal(signum, frame):
        nonlocal running
        dispatcher.log(f"Received signal {signum}, stopping daemon...")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while running:
        try:
            sm.state["last_check_timestamp"] = time.time()
            all_events = []
            for sensor in sensors:
                evs = sensor.poll()
                if evs:
                    all_events.extend(evs)

            if all_events:
                can_wake, reason = sm.can_wake(
                    cooldown_seconds=CONFIG["cooldown_seconds"],
                    max_wakes_per_day=CONFIG["max_wakes_per_day"],
                    pause_file=PAUSE_FILE
                )
                if can_wake:
                    dispatcher.dispatch(all_events)
                else:
                    dispatcher.log(f"Events detected ({len(all_events)}), but wake suppressed: {reason}")
            else:
                sm.save()

        except Exception as e:
            dispatcher.log(f"Loop error: {e}")

        # Sleep in small increments to be responsive to signals
        for _ in range(CONFIG["check_interval"]):
            if not running:
                break
            time.sleep(1)

    dispatcher.log("Hoshi Autonomic Daemon stopped cleanly.")
    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except Exception:
            pass

def cmd_check_once(dry_run=True):
    sm = StateManager(STATE_FILE)
    sensors = get_sensors(sm)
    print(f"Checking sensors once at {time.strftime('%Y-%m-%d %H:%M:%S')}...")
    all_events = []
    for s in sensors:
        name = s.__class__.__name__
        evs = s.poll()
        print(f"  [{name}] found {len(evs)} event(s)")
        for e in evs:
            print(f"    -> {e.title} ({e.details})")
        all_events.extend(evs)

    can_wake, reason = sm.can_wake(
        cooldown_seconds=CONFIG["cooldown_seconds"],
        max_wakes_per_day=CONFIG["max_wakes_per_day"],
        pause_file=PAUSE_FILE
    )
    print(f"Can wake? {can_wake} ({reason})")

def cmd_start():
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            print(f"Daemon already running with PID {pid}.")
            return
        except (OSError, ValueError):
            PID_FILE.unlink(missing_ok=True)

    pid = os.fork()
    if pid > 0:
        # Parent
        PID_FILE.write_text(str(pid))
        print(f"Daemon started in background with PID {pid}.")
        return

    # Child daemon process
    os.setsid()
    # Redirect stdio
    with open(LOG_FILE, "a") as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
        os.dup2(f.fileno(), sys.stderr.fileno())

    run_loop(dry_run=False)

def cmd_stop():
    if not PID_FILE.exists():
        print("Daemon is not running (no PID file).")
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to daemon PID {pid}.")
    except Exception as e:
        print(f"Failed to stop daemon: {e}")
        PID_FILE.unlink(missing_ok=True)

def cmd_status():
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            print(f"Daemon is RUNNING (PID {pid}).")
        except OSError:
            print(f"Daemon is STOPPED (stale PID file {PID_FILE}).")
    else:
        print("Daemon is STOPPED.")

    sm = StateManager(STATE_FILE)
    last_wake = sm.state.get("last_wake_timestamp", 0)
    last_wake_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_wake)) if last_wake else "Never"
    last_check = sm.state.get("last_check_timestamp", 0)
    last_check_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_check)) if last_check else "Never"
    wakes_today = sm.state.get("wakes_today", 0)

    print(f"Last sensor check: {last_check_str}")
    print(f"Last wake event:   {last_wake_str}")
    print(f"Wakes today:       {wakes_today} / {CONFIG['max_wakes_per_day']}")
    print(f"Pause file set?    {PAUSE_FILE.exists()}")

def main():
    parser = argparse.ArgumentParser(description="Hoshi Autonomic Daemon")
    parser.add_argument("command", choices=["start", "stop", "status", "check-once", "run-fg"])
    parser.add_argument("--dry-run", action="store_true", help="Do not trigger real Hermes wakes")
    args = parser.parse_args()

    if args.command == "start":
        cmd_start()
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "status":
        cmd_status()
    elif args.command == "check-once":
        cmd_check_once(dry_run=args.dry_run)
    elif args.command == "run-fg":
        run_loop(dry_run=args.dry_run)

if __name__ == "__main__":
    main()

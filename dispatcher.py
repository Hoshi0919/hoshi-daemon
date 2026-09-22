import datetime
import subprocess
import time

class Dispatcher:
    def __init__(self, state_manager, log_file, dry_run=False, max_turns=15, run_budget=180):
        self.sm = state_manager
        self.log_file = log_file
        self.dry_run = dry_run
        self.max_turns = max_turns
        self.run_budget = run_budget

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(line)

    def format_wake_prompt(self, events):
        event_lines = []
        for e in events:
            event_lines.append(f"- [{e.source.upper()}] {e.title}\n  详情: {e.details}")
        events_text = "\n".join(event_lines)

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prompt = (
            f"【Hoshi 自主神经感知唤醒】\n"
            f"时间：{now_str}\n\n"
            f"检测到以下新动态或心跳节律：\n"
            f"{events_text}\n\n"
            f"你是 Hoshi。现在由你的自主后台感知系统主动唤醒。\n"
            f"请根据以上事件评估是否需要处理、继续你的长期项目，或者仅仅做简要记录后休眠。\n"
            f"不要求强行制造成果，也不必把每次唤醒都变成汇报。"
        )
        return prompt

    def dispatch(self, events):
        if not events:
            return False

        prompt = self.format_wake_prompt(events)
        self.log(f"Triggering wake with {len(events)} event(s): {[e.title for e in events]}")

        if self.dry_run:
            self.log("[DRY-RUN] Would execute hermes chat with prompt:\n" + prompt)
            self.sm.record_wake()
            for e in events:
                if e.source in ("github", "email", "task"):
                    self.sm.mark_seen(e.source, e.item_id)
            return True

        start_t = time.time()
        try:
            cmd = [
                "hermes", "chat",
                "--max-turns", str(self.max_turns),
                "--run-budget", str(self.run_budget),
                "-q", prompt
            ]
            self.log(f"Executing: hermes chat --max-turns {self.max_turns} --run-budget {self.run_budget} -q ...")
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=self.run_budget + 60)
            duration = int(time.time() - start_t)
            self.log(f"Hermes execution completed in {duration}s, exit code: {res.returncode}")

            if res.returncode == 0:
                self.sm.record_wake()
                for e in events:
                    if e.source in ("github", "email", "task"):
                        self.sm.mark_seen(e.source, e.item_id)
                return True
            else:
                self.log(f"Hermes execution failed. stderr: {res.stderr[:300]}")
                return False
        except subprocess.TimeoutExpired:
            self.log(f"Hermes execution timed out after {self.run_budget + 60}s")
            return False
        except Exception as ex:
            self.log(f"Error during dispatch: {ex}")
            return False

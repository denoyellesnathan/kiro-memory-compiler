"""
stop hook - captures assistant responses after each turn.
Also handles userPromptSubmit to capture user messages.

Together these build full conversation context for flush.py.

Configured in .kiro/agents/memory-capture.json and memory-compiler.json
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
STATE_FILE = SCRIPTS_DIR / "stop-hook-state.json"

FLUSH_INTERVAL_SECONDS = 300  # 5 minutes
MIN_CONTEXT_CHARS = 500


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_flush": 0, "accumulated_context": ""}


def save_state(state: dict) -> None:
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def main() -> None:
    try:
        raw = sys.stdin.read()
        hook_event = json.loads(raw)
    except (json.JSONDecodeError, ValueError, EOFError):
        return

    event_name = hook_event.get("hook_event_name", "")
    state = load_state()
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%H:%M")

    if event_name == "userPromptSubmit":
        prompt = hook_event.get("prompt", "").strip()
        if prompt:
            state["accumulated_context"] += f"\n**User ({timestamp}):** {prompt}\n"
    elif event_name == "stop":
        response = hook_event.get("assistant_response", "").strip()
        if response:
            state["accumulated_context"] += f"\n**Assistant ({timestamp}):** {response}\n"
    else:
        return

    now = time.time()
    elapsed = now - state.get("last_flush", 0)
    context_len = len(state["accumulated_context"])

    if elapsed >= FLUSH_INTERVAL_SECONDS and context_len >= MIN_CONTEXT_CHARS:
        ts = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
        context_file = SCRIPTS_DIR / f"stop-flush-{ts}.md"
        context_file.write_text(state["accumulated_context"], encoding="utf-8")

        flush_script = SCRIPTS_DIR / "flush.py"
        if flush_script.exists():
            cmd = ["uv", "run", "--directory", str(ROOT), "python", str(flush_script), str(context_file), f"stop-{ts}"]
            kwargs: dict = {"start_new_session": True} if sys.platform != "win32" else {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            }
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(ROOT), **kwargs)
            except Exception:
                pass

        state["last_flush"] = now
        state["accumulated_context"] = ""

    save_state(state)


if __name__ == "__main__":
    main()

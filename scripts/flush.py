"""
Memory flush - extracts important knowledge from conversation context.

Spawned by the stop hook as a background process. Reads conversation context,
uses kiro-cli headless to decide what's worth saving, and appends to today's daily log.

Usage:
    uv run python flush.py <context_file.md> <session_id>
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from utils import strip_ansi
DAILY_DIR = ROOT / "daily"
SCRIPTS_DIR = ROOT / "scripts"
STATE_FILE = SCRIPTS_DIR / "last-flush.json"
LOG_FILE = SCRIPTS_DIR / "flush.log"

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def load_flush_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_flush_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def append_to_daily_log(content: str, section: str = "Session") -> None:
    """Append content to today's daily log."""
    today = datetime.now(timezone.utc).astimezone()
    log_path = DAILY_DIR / f"{today.strftime('%Y-%m-%d')}.md"

    if not log_path.exists():
        DAILY_DIR.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"# Daily Log: {today.strftime('%Y-%m-%d')}\n\n## Sessions\n\n## Memory Maintenance\n\n",
            encoding="utf-8",
        )

    time_str = today.strftime("%H:%M")
    entry = f"### {section} ({time_str})\n\n{content}\n\n"

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


def run_flush(context: str) -> str:
    """Use kiro-cli headless to extract knowledge from conversation context."""
    prompt = f"""Review the conversation context below and respond with a concise summary
of important items to preserve in a daily log.

IMPORTANT: Only extract knowledge from REAL user conversations — things the user learned,
decided, built, or discussed. REJECT and respond FLUSH_OK if the context is:
- Tool operation output (file reads, directory listings, grep results, shell commands)
- Compiler/build session narration (creating articles, updating index, writing files)
- Repetitive FLUSH_OK entries or empty sessions
- Raw file contents being read or written by an automated process

Format as exactly:

**Context:** [One line about what the user was working on]

**Key Exchanges:**
- [Important Q&A or discussions]

**Decisions Made:**
- [Any decisions with rationale]

**Lessons Learned:**
- [Gotchas, patterns, or insights discovered]

**Action Items:**
- [Follow-ups or TODOs mentioned]

Only include sections with actual content. If nothing is worth saving, respond with exactly: FLUSH_OK

## Conversation Context

{context}"""

    result = subprocess.run(
        ["kiro-cli", "chat", "--no-interactive", prompt],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return f"FLUSH_ERROR: kiro-cli exit {result.returncode}: {result.stderr[:200]}"

    return strip_ansi(result.stdout.strip())


COMPILE_AFTER_HOUR = 18


def maybe_trigger_compilation() -> None:
    """If past compile hour and today's log hasn't been compiled, run compile.py."""
    now = datetime.now(timezone.utc).astimezone()
    if now.hour < COMPILE_AFTER_HOUR:
        return

    today_log = f"{now.strftime('%Y-%m-%d')}.md"
    compile_state_file = SCRIPTS_DIR / "state.json"
    if compile_state_file.exists():
        try:
            compile_state = json.loads(compile_state_file.read_text(encoding="utf-8"))
            ingested = compile_state.get("ingested", {})
            if today_log in ingested:
                from hashlib import sha256
                log_path = DAILY_DIR / today_log
                if log_path.exists():
                    current_hash = sha256(log_path.read_bytes()).hexdigest()[:16]
                    if ingested[today_log].get("hash") == current_hash:
                        return
        except (json.JSONDecodeError, OSError):
            pass

    compile_script = SCRIPTS_DIR / "compile.py"
    if not compile_script.exists():
        return

    logging.info("End-of-day compilation triggered (after %d:00)", COMPILE_AFTER_HOUR)

    cmd = ["uv", "run", "--directory", str(ROOT), "python", str(compile_script)]
    kwargs: dict = {"start_new_session": True} if sys.platform != "win32" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    }

    try:
        log_handle = open(str(SCRIPTS_DIR / "compile.log"), "a")
        subprocess.Popen(cmd, stdout=log_handle, stderr=subprocess.STDOUT, cwd=str(ROOT), **kwargs)
    except Exception as e:
        logging.error("Failed to spawn compile.py: %s", e)


def main():
    if len(sys.argv) < 3:
        logging.error("Usage: %s <context_file.md> <session_id>", sys.argv[0])
        sys.exit(1)

    context_file = Path(sys.argv[1])
    session_id = sys.argv[2]

    logging.info("flush.py started for session %s", session_id)

    if not context_file.exists():
        logging.error("Context file not found: %s", context_file)
        return

    # Deduplication
    state = load_flush_state()
    if state.get("session_id") == session_id and time.time() - state.get("timestamp", 0) < 60:
        logging.info("Skipping duplicate flush for session %s", session_id)
        context_file.unlink(missing_ok=True)
        return

    context = context_file.read_text(encoding="utf-8").strip()
    if not context:
        logging.info("Context file is empty, skipping")
        context_file.unlink(missing_ok=True)
        return

    logging.info("Flushing session %s: %d chars", session_id, len(context))

    response = run_flush(context)

    cleaned = response.strip()
    if cleaned.startswith("FLUSH_OK"):
        cleaned = cleaned[len("FLUSH_OK"):].strip()

    if not cleaned:
        logging.info("Result: FLUSH_OK")
        append_to_daily_log("FLUSH_OK - Nothing worth saving from this session", "Memory Flush")
    elif "FLUSH_ERROR" in response:
        logging.error("Result: %s", response)
        append_to_daily_log(response, "Memory Flush")
    else:
        logging.info("Result: saved to daily log (%d chars)", len(cleaned))
        append_to_daily_log(cleaned, "Session")

    save_flush_state({"session_id": session_id, "timestamp": time.time()})
    context_file.unlink(missing_ok=True)
    maybe_trigger_compilation()
    logging.info("Flush complete for session %s", session_id)


if __name__ == "__main__":
    main()

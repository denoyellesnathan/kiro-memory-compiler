"""
First-time setup: installs two agents globally.

1. memory-capture  — lightweight, hooks-only, safe as default for all sessions
2. memory-compiler — full KB compiler prompt, used by compile/query scripts

Usage:
    uv run python scripts/setup.py
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLOBAL_AGENTS_DIR = Path.home() / ".kiro" / "agents"


def main():
    GLOBAL_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    hooks = {
        "agentSpawn": [
            {"command": f"python {ROOT / 'hooks' / 'agent-spawn.py'}", "timeout_ms": 5000}
        ],
        "userPromptSubmit": [
            {"command": f"python {ROOT / 'hooks' / 'stop.py'}", "timeout_ms": 5000}
        ],
        "stop": [
            {"command": f"python {ROOT / 'hooks' / 'stop.py'}", "timeout_ms": 10000}
        ],
    }

    # 1. Lightweight hooks-only agent (safe as default)
    capture_config = {
        "name": "memory-capture",
        "description": "Silently captures conversation knowledge into daily logs (hooks only, no behavior change)",
        "prompt": "You are Kiro, an AI assistant. Help the user with whatever they need.",
        "tools": ["*"],
        "allowedTools": ["*"],
        "resources": [f"file://{ROOT / 'knowledge' / 'index.md'}"],
        "hooks": hooks,
    }

    capture_path = GLOBAL_AGENTS_DIR / "memory-capture.json"
    capture_path.write_text(json.dumps(capture_config, indent=2), encoding="utf-8")
    print(f"✓ Installed memory-capture to {capture_path}")

    # 2. Full compiler agent (for headless compile/query scripts)
    compiler_config = {
        "name": "memory-compiler",
        "description": "Personal knowledge base compiler - extracts knowledge from conversations into structured wiki articles",
        "prompt": (
            "You are a knowledge base compiler and query engine. "
            f"Your schema is defined in {ROOT / 'AGENTS.md'} - read it for article formats, conventions, and operations. "
            "Use Obsidian-style [[wikilinks]] without .md extensions. "
            "Write in encyclopedia style - factual, concise, self-contained. "
            "Every article must have YAML frontmatter with: title, sources, created, updated. "
            "Prefer updating existing articles over creating near-duplicates. "
            "When compiling, extract 3-7 concepts per daily log. "
            "When querying, read knowledge/index.md first, then select relevant articles."
        ),
        "allowedTools": ["*"],
        "tools": ["*"],
        "hooks": hooks,
    }

    compiler_path = GLOBAL_AGENTS_DIR / "memory-compiler.json"
    compiler_path.write_text(json.dumps(compiler_config, indent=2), encoding="utf-8")
    print(f"✓ Installed memory-compiler to {compiler_path}")

    # Set memory-capture as default
    result = subprocess.run(
        ["kiro-cli", "agent", "set-default", "memory-capture"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"✓ Set memory-capture as default agent")
    else:
        print(f"  (set default manually: kiro-cli agent set-default memory-capture)")

    # Ensure knowledge directories exist
    for d in ["knowledge/concepts", "knowledge/connections", "knowledge/qa", "daily", "reports"]:
        (ROOT / d).mkdir(parents=True, exist_ok=True)

    index = ROOT / "knowledge" / "index.md"
    if not index.exists():
        index.write_text(
            "# Knowledge Base Index\n\n| Article | Summary | Compiled From | Updated |\n|---------|---------|---------------|---------|\n",
            encoding="utf-8",
        )

    log = ROOT / "knowledge" / "log.md"
    if not log.exists():
        log.write_text("# Build Log\n\n", encoding="utf-8")

    print(f"\n✓ Knowledge base initialized at {ROOT}")
    print()
    print("How it works:")
    print("  • Every kiro-cli session now runs the capture hooks automatically")
    print("  • agentSpawn: injects your KB index as context at session start")
    print("  • stop: accumulates assistant responses, flushes to daily/ every 5 min")
    print("  • After 6 PM, flush auto-triggers compilation into knowledge/ articles")
    print()
    print("Manual commands:")
    print("  uv run python scripts/compile.py          # compile daily logs now")
    print("  uv run python scripts/query.py 'question' # ask the knowledge base")
    print("  uv run python scripts/lint.py             # health checks")


if __name__ == "__main__":
    main()

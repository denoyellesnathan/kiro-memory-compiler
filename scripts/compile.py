"""
Compile daily conversation logs into structured knowledge articles.

Uses kiro-cli headless mode to read daily logs and produce organized
knowledge articles with cross-references.

Usage:
    uv run python compile.py                    # compile new/changed logs only
    uv run python compile.py --all              # force recompile everything
    uv run python compile.py --file daily/2026-04-01.md
    uv run python compile.py --dry-run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from config import DAILY_DIR, KNOWLEDGE_DIR, now_iso
from utils import (
    file_hash,
    list_raw_files,
    list_wiki_articles,
    load_state,
    read_wiki_index,
    save_state,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def compile_daily_log(log_path: Path, state: dict) -> None:
    """Compile a single daily log into knowledge articles via kiro-cli headless.

    Uses byte-offset tracking so repeat compiles of the same file only process
    content appended since the last successful compilation.
    """
    full_content = log_path.read_text(encoding="utf-8")
    wiki_index = read_wiki_index()

    # Determine what's new since last compile
    ingested = state.get("ingested", {}).get(log_path.name, {})
    prev_offset = ingested.get("compiled_offset", 0)
    new_content = full_content[prev_offset:]

    if not new_content.strip():
        print("  No new content since last compile, skipping.")
        return

    if prev_offset > 0:
        print(f"  Partial compile: offset {prev_offset} → {len(full_content)} ({len(new_content)} new chars)")
    else:
        print(f"  Full compile: {len(full_content)} chars")

    # If this is a partial compile, give the LLM context about what was already compiled
    offset_note = ""
    if prev_offset > 0:
        offset_note = (
            f"\n**Note:** This daily log was partially compiled before (first {prev_offset} chars). "
            f"Only the NEW content below needs processing. The existing articles from earlier "
            f"compilations are already in the index.\n"
        )

    timestamp = now_iso()

    prompt = f"""Compile this daily log into knowledge articles.

## Current Wiki Index

{wiki_index}

## Existing Articles Location

Articles live under `{KNOWLEDGE_DIR}` in subdirectories: `concepts/`, `connections/`, `qa/`.
**Do NOT ask for the full articles upfront.** Instead, use the index above to identify which
existing articles are relevant to this daily log, then read only those files before deciding
whether to update them or create new ones.

## Daily Log to Compile

**File:** {log_path.name}
{offset_note}
{new_content}

## Your Task

1. Read the index above and identify existing articles that overlap with topics in this daily log
2. Read only those relevant articles from disk (use their file paths under `{KNOWLEDGE_DIR}/`)
3. Extract key concepts into `knowledge/concepts/` articles (update existing or create new)
4. Create connection articles in `knowledge/connections/` if non-obvious relationships exist
5. Update `knowledge/index.md` with new/modified entries
6. Append to `knowledge/log.md`:
   ## [{timestamp}] compile | {log_path.name}
   - Source: daily/{log_path.name}
   - Articles created: [[concepts/x]], [[concepts/y]]
   - Articles updated: (list if any)

Write all files now."""

    result = subprocess.run(
        ["kiro-cli", "chat", "--no-interactive", "--trust-all-tools", "--agent", "memory-compiler", prompt],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  Error (exit {result.returncode}): {result.stderr[:500]}")
        return

    # Update state with hash of full file and byte offset
    state.setdefault("ingested", {})[log_path.name] = {
        "hash": file_hash(log_path),
        "compiled_at": now_iso(),
        "compiled_offset": len(full_content),
    }
    save_state(state)


def main():
    parser = argparse.ArgumentParser(description="Compile daily logs into knowledge articles")
    parser.add_argument("--all", action="store_true", help="Force recompile all logs")
    parser.add_argument("--file", type=str, help="Compile a specific daily log file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be compiled")
    args = parser.parse_args()

    state = load_state()

    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            target = DAILY_DIR / target.name
        if not target.exists():
            target = ROOT_DIR / args.file
        if not target.exists():
            print(f"Error: {args.file} not found")
            sys.exit(1)
        to_compile = [target]
    else:
        all_logs = list_raw_files()
        if args.all:
            to_compile = all_logs
        else:
            to_compile = []
            for log_path in all_logs:
                entry = state.get("ingested", {}).get(log_path.name)
                if not entry:
                    # Never compiled
                    to_compile.append(log_path)
                elif entry.get("hash") != file_hash(log_path):
                    # File changed since last compile (new content appended)
                    to_compile.append(log_path)

    if not to_compile:
        print("Nothing to compile - all daily logs are up to date.")
        return

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Files to compile ({len(to_compile)}):")
    for f in to_compile:
        print(f"  - {f.name}")

    if args.dry_run:
        return

    for i, log_path in enumerate(to_compile, 1):
        print(f"\n[{i}/{len(to_compile)}] Compiling {log_path.name}...")
        compile_daily_log(log_path, state)
        print(f"  Done.")

    print(f"\nCompilation complete. Knowledge base: {len(list_wiki_articles())} articles")


if __name__ == "__main__":
    main()

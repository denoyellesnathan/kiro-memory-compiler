"""
agentSpawn hook - injects knowledge base index into every conversation.

Outputs the KB index so the agent knows what knowledge exists. The agent
can read full articles on demand at the absolute paths shown.

Configured in .kiro/agents/memory-capture.json and memory-compiler.json
"""

from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"
INDEX_FILE = KNOWLEDGE_DIR / "index.md"


def main():
    today = datetime.now(timezone.utc).astimezone()
    parts = [f"Today: {today.strftime('%A, %B %d, %Y')}"]

    parts.append(f"Knowledge base location: {KNOWLEDGE_DIR}")

    if INDEX_FILE.exists():
        parts.append(f"## Knowledge Base Index\n\n{INDEX_FILE.read_text(encoding='utf-8')}")
    else:
        parts.append("## Knowledge Base Index\n\n(empty - no articles compiled yet)")

    parts.append(
        "To answer questions from the knowledge base, read the relevant article files "
        f"from {KNOWLEDGE_DIR}/concepts/, {KNOWLEDGE_DIR}/connections/, or {KNOWLEDGE_DIR}/qa/."
    )

    print("\n\n".join(parts))


if __name__ == "__main__":
    main()

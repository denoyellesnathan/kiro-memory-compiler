"""
Query the knowledge base using index-guided retrieval (no RAG).

The LLM reads the index, picks relevant articles, and synthesizes an answer.

Usage:
    uv run python query.py "How should I handle auth redirects?"
    uv run python query.py "What patterns do I use for API design?" --file-back
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from config import KNOWLEDGE_DIR, QA_DIR, now_iso
from utils import load_state, read_all_wiki_content, save_state, strip_ansi

ROOT_DIR = Path(__file__).resolve().parent.parent


def run_query(question: str, file_back: bool = False) -> str:
    """Query the knowledge base via kiro-cli headless."""
    wiki_content = read_all_wiki_content()

    file_back_instructions = ""
    if file_back:
        timestamp = now_iso()
        file_back_instructions = f"""

After answering, do the following:
1. Create a Q&A article at knowledge/qa/ with a slugified filename
2. Use the Q&A article format from AGENTS.md (frontmatter with title, question, consulted, filed)
3. Update knowledge/index.md with a new row
4. Append to knowledge/log.md:
   ## [{timestamp}] query (filed) | {question[:50]}
   - Question: {question}
   - Consulted: [[list of articles read]]
   - Filed to: [[qa/article-name]]
"""

    prompt = f"""Answer this question using the knowledge base below.

1. Read the INDEX section first
2. Identify relevant articles
3. Synthesize a clear answer with [[wikilink]] citations
4. If the KB doesn't cover this, say so honestly

## Knowledge Base

{wiki_content}

## Question

{question}
{file_back_instructions}"""

    trust = "--trust-all-tools" if file_back else "--trust-tools=read,grep,glob"

    result = subprocess.run(
        ["kiro-cli", "chat", "--no-interactive", trust, "--agent", "memory-compiler", prompt],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return f"Error querying knowledge base (exit {result.returncode}): {result.stderr[:500]}"

    # Update state
    state = load_state()
    state["query_count"] = state.get("query_count", 0) + 1
    save_state(state)

    return strip_ansi(result.stdout)


def main():
    parser = argparse.ArgumentParser(description="Query the personal knowledge base")
    parser.add_argument("question", help="The question to ask")
    parser.add_argument("--file-back", action="store_true", help="File the answer back as a Q&A article")
    args = parser.parse_args()

    print(f"Question: {args.question}")
    print(f"File back: {'yes' if args.file_back else 'no'}")
    print("-" * 60)

    answer = run_query(args.question, file_back=args.file_back)
    print(answer)

    if args.file_back:
        print("\n" + "-" * 60)
        qa_count = len(list(QA_DIR.glob("*.md"))) if QA_DIR.exists() else 0
        print(f"Answer filed to knowledge/qa/ ({qa_count} Q&A articles total)")


if __name__ == "__main__":
    main()

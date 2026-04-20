"""
Lint the knowledge base for structural and semantic health.

Runs 7 checks: broken links, orphan pages, orphan sources, stale articles,
contradictions (LLM), missing backlinks, and sparse articles.

Usage:
    uv run python lint.py                    # all checks
    uv run python lint.py --structural-only  # skip LLM checks (free)
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from config import KNOWLEDGE_DIR, REPORTS_DIR, now_iso, today_iso
from utils import (
    count_inbound_links,
    extract_wikilinks,
    file_hash,
    get_article_word_count,
    list_raw_files,
    list_wiki_articles,
    load_state,
    read_all_wiki_content,
    save_state,
    strip_ansi,
    wiki_article_exists,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def check_broken_links() -> list[dict]:
    issues = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(KNOWLEDGE_DIR)
        for link in extract_wikilinks(content):
            if link.startswith("daily/"):
                continue
            if not wiki_article_exists(link):
                issues.append({
                    "severity": "error",
                    "check": "broken_link",
                    "file": str(rel),
                    "detail": f"Broken link: [[{link}]] - target does not exist",
                })
    return issues


def check_orphan_pages() -> list[dict]:
    issues = []
    for article in list_wiki_articles():
        rel = article.relative_to(KNOWLEDGE_DIR)
        link_target = str(rel).replace(".md", "").replace("\\", "/")
        if count_inbound_links(link_target) == 0:
            issues.append({
                "severity": "warning",
                "check": "orphan_page",
                "file": str(rel),
                "detail": f"Orphan page: no other articles link to [[{link_target}]]",
            })
    return issues


def check_orphan_sources() -> list[dict]:
    state = load_state()
    ingested = state.get("ingested", {})
    return [
        {"severity": "warning", "check": "orphan_source", "file": f"daily/{log_path.name}",
         "detail": f"Uncompiled daily log: {log_path.name} has not been ingested"}
        for log_path in list_raw_files() if log_path.name not in ingested
    ]


def check_stale_articles() -> list[dict]:
    state = load_state()
    ingested = state.get("ingested", {})
    issues = []
    for log_path in list_raw_files():
        rel = log_path.name
        if rel in ingested and ingested[rel].get("hash") != file_hash(log_path):
            issues.append({
                "severity": "warning",
                "check": "stale_article",
                "file": f"daily/{rel}",
                "detail": f"Stale: {rel} has changed since last compilation",
            })
    return issues


def check_missing_backlinks() -> list[dict]:
    issues = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(KNOWLEDGE_DIR)
        source_link = str(rel).replace(".md", "").replace("\\", "/")
        for link in extract_wikilinks(content):
            if link.startswith("daily/"):
                continue
            target_path = KNOWLEDGE_DIR / f"{link}.md"
            if target_path.exists():
                target_content = target_path.read_text(encoding="utf-8")
                if f"[[{source_link}]]" not in target_content:
                    issues.append({
                        "severity": "suggestion",
                        "check": "missing_backlink",
                        "file": str(rel),
                        "detail": f"[[{source_link}]] links to [[{link}]] but not vice versa",
                        "auto_fixable": True,
                    })
    return issues


def check_sparse_articles() -> list[dict]:
    issues = []
    for article in list_wiki_articles():
        word_count = get_article_word_count(article)
        if word_count < 200:
            rel = article.relative_to(KNOWLEDGE_DIR)
            issues.append({
                "severity": "suggestion",
                "check": "sparse_article",
                "file": str(rel),
                "detail": f"Sparse article: {word_count} words (minimum recommended: 200)",
            })
    return issues


def check_contradictions() -> list[dict]:
    """Use kiro-cli headless to detect contradictions across articles."""
    wiki_content = read_all_wiki_content()

    prompt = f"""Review this knowledge base for contradictions and conflicting claims.

{wiki_content}

For each issue found, output EXACTLY one line in this format:
CONTRADICTION: [file1] vs [file2] - description of the conflict
INCONSISTENCY: [file] - description of the inconsistency

If no issues found, output exactly: NO_ISSUES"""

    result = subprocess.run(
        ["kiro-cli", "chat", "--no-interactive", prompt],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return [{"severity": "error", "check": "contradiction", "file": "(system)",
                 "detail": f"LLM check failed (exit {result.returncode}): {result.stderr[:200]}"}]

    response = strip_ansi(result.stdout.strip())
    if "NO_ISSUES" in response:
        return []

    return [
        {"severity": "warning", "check": "contradiction", "file": "(cross-article)", "detail": line.strip()}
        for line in response.split("\n")
        if line.strip().startswith(("CONTRADICTION:", "INCONSISTENCY:"))
    ]


def generate_report(all_issues: list[dict]) -> str:
    errors = [i for i in all_issues if i["severity"] == "error"]
    warnings = [i for i in all_issues if i["severity"] == "warning"]
    suggestions = [i for i in all_issues if i["severity"] == "suggestion"]

    lines = [
        f"# Lint Report - {today_iso()}", "",
        f"**Total issues:** {len(all_issues)}",
        f"- Errors: {len(errors)}", f"- Warnings: {len(warnings)}", f"- Suggestions: {len(suggestions)}", "",
    ]

    for severity, issues, marker in [("Errors", errors, "x"), ("Warnings", warnings, "!"), ("Suggestions", suggestions, "?")]:
        if issues:
            lines.append(f"## {severity}")
            lines.append("")
            for issue in issues:
                fixable = " (auto-fixable)" if issue.get("auto_fixable") else ""
                lines.append(f"- **[{marker}]** `{issue['file']}` - {issue['detail']}{fixable}")
            lines.append("")

    if not all_issues:
        lines.extend(["All checks passed. Knowledge base is healthy.", ""])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Lint the knowledge base")
    parser.add_argument("--structural-only", action="store_true", help="Skip LLM-based checks")
    args = parser.parse_args()

    print("Running knowledge base lint checks...")
    all_issues: list[dict] = []

    checks = [
        ("Broken links", check_broken_links),
        ("Orphan pages", check_orphan_pages),
        ("Orphan sources", check_orphan_sources),
        ("Stale articles", check_stale_articles),
        ("Missing backlinks", check_missing_backlinks),
        ("Sparse articles", check_sparse_articles),
    ]

    for name, check_fn in checks:
        print(f"  Checking: {name}...")
        issues = check_fn()
        all_issues.extend(issues)
        print(f"    Found {len(issues)} issue(s)")

    if not args.structural_only:
        print("  Checking: Contradictions (LLM)...")
        issues = check_contradictions()
        all_issues.extend(issues)
        print(f"    Found {len(issues)} issue(s)")
    else:
        print("  Skipping: Contradictions (--structural-only)")

    report = generate_report(all_issues)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"lint-{today_iso()}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    state = load_state()
    state["last_lint"] = now_iso()
    save_state(state)

    errors = sum(1 for i in all_issues if i["severity"] == "error")
    warnings = sum(1 for i in all_issues if i["severity"] == "warning")
    suggestions = sum(1 for i in all_issues if i["severity"] == "suggestion")
    print(f"\nResults: {errors} errors, {warnings} warnings, {suggestions} suggestions")

    if errors > 0:
        print("\nErrors found - knowledge base needs attention!")
        return 1
    return 0


if __name__ == "__main__":
    exit(main())

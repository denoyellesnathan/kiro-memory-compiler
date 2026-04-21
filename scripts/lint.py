"""
Lint the knowledge base for structural and semantic health.

Runs 8 checks: broken links, orphan pages, orphan sources, stale articles,
missing backlinks, sparse articles, stale knowledge (decay), and contradictions (LLM).

Usage:
    uv run python lint.py                    # all checks
    uv run python lint.py --structural-only  # skip LLM checks (free)
    uv run python lint.py --verbose          # detailed per-article logging
    uv run python lint.py --fix              # auto-fix what we can, then LLM-fix the rest
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import time
from pathlib import Path

from config import KNOWLEDGE_DIR, REPORTS_DIR, SCRIPTS_DIR, STALE_ARTICLE_DAYS, now_iso, today_iso
from utils import (
    count_inbound_links,
    extract_wikilinks,
    file_hash,
    get_article_word_count,
    get_last_activity,
    list_raw_files,
    list_wiki_articles,
    load_state,
    read_all_wiki_content,
    read_wiki_index,
    save_state,
    strip_ansi,
    wiki_article_exists,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = SCRIPTS_DIR / "lint.log"

log = logging.getLogger("lint")


def _setup_logging(verbose: bool) -> None:
    """Configure logging to file (always) and console (if verbose)."""
    log.setLevel(logging.DEBUG)

    # Always log to file
    fh = logging.FileHandler(str(LOG_FILE), mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    log.addHandler(fh)

    # Console: DEBUG if verbose, otherwise only INFO+
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(logging.Formatter("  %(message)s"))
    log.addHandler(ch)


def check_broken_links() -> list[dict]:
    issues = []
    articles = list_wiki_articles()
    log.debug("Scanning %d articles for broken wikilinks", len(articles))
    for article in articles:
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(KNOWLEDGE_DIR)
        links = extract_wikilinks(content)
        non_daily = [l for l in links if not l.startswith("daily/")]
        log.debug("  %s: %d wikilinks (%d non-daily)", rel, len(links), len(non_daily))
        for link in non_daily:
            if not wiki_article_exists(link):
                log.debug("    BROKEN: [[%s]]", link)
                issues.append({
                    "severity": "error",
                    "check": "broken_link",
                    "file": str(rel),
                    "detail": f"Broken link: [[{link}]] - target does not exist",
                })
    return issues


def check_orphan_pages() -> list[dict]:
    issues = []
    articles = list_wiki_articles()
    log.debug("Checking %d articles for inbound links", len(articles))
    for article in articles:
        rel = article.relative_to(KNOWLEDGE_DIR)
        link_target = str(rel).replace(".md", "").replace("\\", "/")
        inbound = count_inbound_links(link_target)
        log.debug("  %s: %d inbound links", rel, inbound)
        if inbound == 0:
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
    all_logs = list_raw_files()
    log.debug("Daily logs: %d total, %d ingested in state", len(all_logs), len(ingested))
    issues = []
    for log_path in all_logs:
        if log_path.name not in ingested:
            log.debug("  UNCOMPILED: %s", log_path.name)
            issues.append({
                "severity": "warning",
                "check": "orphan_source",
                "file": f"daily/{log_path.name}",
                "detail": f"Uncompiled daily log: {log_path.name} has not been ingested",
            })
        else:
            log.debug("  OK: %s (compiled %s)", log_path.name, ingested[log_path.name].get("compiled_at", "?"))
    return issues


def check_stale_articles() -> list[dict]:
    state = load_state()
    ingested = state.get("ingested", {})
    issues = []
    for log_path in list_raw_files():
        rel = log_path.name
        if rel in ingested:
            stored_hash = ingested[rel].get("hash")
            current = file_hash(log_path)
            if stored_hash != current:
                log.debug("  STALE: %s (stored=%s current=%s)", rel, stored_hash, current)
                issues.append({
                    "severity": "warning",
                    "check": "stale_article",
                    "file": f"daily/{rel}",
                    "detail": f"Stale: {rel} has changed since last compilation",
                })
            else:
                log.debug("  OK: %s (hash=%s)", rel, current)
    return issues


def check_missing_backlinks() -> list[dict]:
    issues = []
    articles = list_wiki_articles()
    log.debug("Checking backlinks across %d articles", len(articles))
    for article in articles:
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
                    log.debug("  MISSING: %s → %s (no backlink)", source_link, link)
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
        rel = article.relative_to(KNOWLEDGE_DIR)
        log.debug("  %s: %d words", rel, word_count)
        if word_count < 200:
            issues.append({
                "severity": "suggestion",
                "check": "sparse_article",
                "file": str(rel),
                "detail": f"Sparse article: {word_count} words (minimum recommended: 200)",
            })
    return issues


def check_stale_knowledge() -> list[dict]:
    """Flag articles not accessed or updated within STALE_ARTICLE_DAYS."""
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=STALE_ARTICLE_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    log.debug("Staleness cutoff: %s (%d days)", cutoff_str, STALE_ARTICLE_DAYS)
    issues = []

    for article in list_wiki_articles():
        rel = article.relative_to(KNOWLEDGE_DIR)
        last_activity = get_last_activity(article)
        log.debug("  %s: last_activity=%s", rel, last_activity or "(none)")

        if last_activity is None:
            issues.append({
                "severity": "suggestion",
                "check": "stale_knowledge",
                "file": str(rel),
                "detail": "No access or update recorded — candidate for review or archival",
            })
        elif last_activity[:10] < cutoff_str:
            issues.append({
                "severity": "suggestion",
                "check": "stale_knowledge",
                "file": str(rel),
                "detail": f"Last activity {last_activity[:10]} ({STALE_ARTICLE_DAYS}+ days ago) — candidate for review or archival",
            })

    return issues


def check_contradictions() -> list[dict]:
    """Use kiro-cli headless to detect contradictions across articles."""
    wiki_content = read_all_wiki_content()
    log.debug("Sending %d chars to LLM for contradiction check", len(wiki_content))

    prompt = f"""Review this knowledge base for contradictions and conflicting claims.

{wiki_content}

For each issue found, output EXACTLY one line in this format:
CONTRADICTION: [file1] vs [file2] - description of the conflict
INCONSISTENCY: [file] - description of the inconsistency

If no issues found, output exactly: NO_ISSUES"""

    start = time.time()
    result = subprocess.run(
        ["kiro-cli", "chat", "--no-interactive", prompt],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - start
    log.debug("LLM contradiction check completed in %.1fs (exit %d)", elapsed, result.returncode)

    if result.returncode != 0:
        log.error("LLM check failed: %s", result.stderr[:200])
        return [{"severity": "error", "check": "contradiction", "file": "(system)",
                 "detail": f"LLM check failed (exit {result.returncode}): {result.stderr[:200]}"}]

    response = strip_ansi(result.stdout.strip())
    if "NO_ISSUES" in response:
        log.debug("LLM found no contradictions")
        return []

    findings = [
        {"severity": "warning", "check": "contradiction", "file": "(cross-article)", "detail": line.strip()}
        for line in response.split("\n")
        if line.strip().startswith(("CONTRADICTION:", "INCONSISTENCY:"))
    ]
    for f in findings:
        log.debug("  LLM: %s", f["detail"])
    return findings


# ── Fix mode ──────────────────────────────────────────────────────────

# Issues the LLM can fix when given the affected articles + index
LLM_FIXABLE_CHECKS = {"broken_link", "sparse_article", "orphan_page"}

# Issues that are resolved by running compile.py (not lint's job)
COMPILE_FIXABLE_CHECKS = {"orphan_source", "stale_article"}

# Issues that need human judgment
MANUAL_CHECKS = {"contradiction", "stale_knowledge"}


def fix_missing_backlinks(issues: list[dict]) -> int:
    """Add missing backlinks directly — no LLM needed."""
    fixed = 0
    for issue in issues:
        if issue["check"] != "missing_backlink":
            continue

        detail = issue["detail"]
        # Parse "[[source]] links to [[target]] but not vice versa"
        links = extract_wikilinks(detail)
        if len(links) < 2:
            log.warning("  Could not parse backlink issue: %s", detail)
            continue

        source_link, target_link = links[0], links[1]
        target_path = KNOWLEDGE_DIR / f"{target_link}.md"

        if not target_path.exists():
            log.warning("  Target not found: %s", target_path)
            continue

        content = target_path.read_text(encoding="utf-8")

        # Find the Related Concepts section and append there
        marker = "## Related Concepts"
        if marker in content:
            insert_pos = content.index(marker) + len(marker)
            # Find the end of the section (next ## or EOF)
            next_section = content.find("\n## ", insert_pos)
            if next_section == -1:
                next_section = len(content)
            # Insert before the next section
            backlink_line = f"\n- [[{source_link}]]"
            content = content[:next_section].rstrip() + backlink_line + "\n" + content[next_section:]
        else:
            # No Related Concepts section — append one at the end
            content = content.rstrip() + f"\n\n## Related Concepts\n\n- [[{source_link}]]\n"

        target_path.write_text(content, encoding="utf-8")
        log.info("  Fixed: added [[%s]] backlink to %s", source_link, target_link)
        fixed += 1

    return fixed


def fix_with_llm(issues: list[dict]) -> int:
    """Send LLM-fixable issues to kiro-cli with the affected articles."""
    if not issues:
        return 0

    # Collect unique affected files
    affected_files: set[str] = set()
    for issue in issues:
        affected_files.add(issue["file"])

    # Build context: index + affected article contents
    wiki_index = read_wiki_index()
    article_context_parts: list[str] = []
    for rel_file in sorted(affected_files):
        path = KNOWLEDGE_DIR / rel_file
        if path.exists():
            article_context_parts.append(
                f"### {rel_file}\n```markdown\n{path.read_text(encoding='utf-8')}\n```"
            )

    # Format issues for the prompt
    issue_lines = []
    for issue in issues:
        issue_lines.append(f"- [{issue['check']}] `{issue['file']}`: {issue['detail']}")

    articles_block = "\n\n".join(article_context_parts) if article_context_parts else "(articles listed in issues below)"
    issues_block = "\n".join(issue_lines)

    prompt = f"""Fix the following knowledge base issues. You have full tool access to read and write files.

## Current Wiki Index

{wiki_index}

## Affected Articles

{articles_block}

## Issues to Fix

{issues_block}

## Instructions

For each issue:
- **broken_link**: Read the index to find the correct article path. Update the wikilink in the source file.
  If no matching article exists, remove the broken link or note it as a TODO.
- **sparse_article**: Read the source daily logs listed in the article's frontmatter. Enrich the article
  with additional detail extracted from those logs. Aim for 200+ words.
- **orphan_page**: Find related articles via the index and add cross-references (wikilinks) in both directions.

Write all file changes now. After fixing, output a summary line for each fix:
FIXED: [file] - what you did"""

    log.info("  Sending %d issues to LLM for fixing (%d affected files)...", len(issues), len(affected_files))

    start = time.time()
    result = subprocess.run(
        ["kiro-cli", "chat", "--no-interactive", "--trust-all-tools", "--agent", "memory-compiler", prompt],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - start

    if result.returncode != 0:
        log.error("  LLM fix failed (exit %d, %.1fs): %s", result.returncode, elapsed, result.stderr[:300])
        return 0

    response = strip_ansi(result.stdout)
    fixed_lines = [l for l in response.split("\n") if l.strip().startswith("FIXED:")]
    log.info("  LLM fix completed in %.1fs — %d fixes reported", elapsed, len(fixed_lines))
    for line in fixed_lines:
        log.info("    %s", line.strip())

    return len(fixed_lines)


def run_fixes(all_issues: list[dict]) -> dict:
    """Run all applicable fixes and return a summary."""
    summary = {"auto_fixed": 0, "llm_fixed": 0, "skipped_compile": 0, "skipped_manual": 0}

    # 1. Auto-fix missing backlinks (no LLM)
    backlink_issues = [i for i in all_issues if i["check"] == "missing_backlink"]
    if backlink_issues:
        log.info("Auto-fixing %d missing backlinks...", len(backlink_issues))
        summary["auto_fixed"] = fix_missing_backlinks(backlink_issues)

    # 2. LLM-fix broken links, sparse articles, orphan pages
    llm_issues = [i for i in all_issues if i["check"] in LLM_FIXABLE_CHECKS]
    if llm_issues:
        log.info("LLM-fixing %d issues (broken links, sparse articles, orphan pages)...", len(llm_issues))
        summary["llm_fixed"] = fix_with_llm(llm_issues)

    # 3. Report what was skipped
    compile_issues = [i for i in all_issues if i["check"] in COMPILE_FIXABLE_CHECKS]
    manual_issues = [i for i in all_issues if i["check"] in MANUAL_CHECKS]
    summary["skipped_compile"] = len(compile_issues)
    summary["skipped_manual"] = len(manual_issues)

    if compile_issues:
        log.info("Skipped %d issues fixable by running compile.py (orphan sources, stale articles)", len(compile_issues))
    if manual_issues:
        log.info("Skipped %d issues requiring manual review (contradictions, stale knowledge)", len(manual_issues))

    return summary


# ── Report generation ─────────────────────────────────────────────────

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
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed per-article logging")
    parser.add_argument("--fix", action="store_true", help="Auto-fix backlinks, then LLM-fix broken links/sparse/orphans")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    articles = list_wiki_articles()
    daily_logs = list_raw_files()
    log.info("Running knowledge base lint checks...")
    log.info("KB stats: %d articles, %d daily logs", len(articles), len(daily_logs))

    total_start = time.time()
    all_issues: list[dict] = []

    checks = [
        ("Broken links", check_broken_links),
        ("Orphan pages", check_orphan_pages),
        ("Orphan sources", check_orphan_sources),
        ("Stale articles", check_stale_articles),
        ("Missing backlinks", check_missing_backlinks),
        ("Sparse articles", check_sparse_articles),
        ("Stale knowledge", check_stale_knowledge),
    ]

    for name, check_fn in checks:
        log.info("Checking: %s...", name)
        start = time.time()
        issues = check_fn()
        elapsed = time.time() - start
        all_issues.extend(issues)
        log.info("  %s: %d issue(s) (%.2fs)", name, len(issues), elapsed)

    if not args.structural_only:
        log.info("Checking: Contradictions (LLM)...")
        start = time.time()
        issues = check_contradictions()
        elapsed = time.time() - start
        all_issues.extend(issues)
        log.info("  Contradictions: %d issue(s) (%.1fs)", len(issues), elapsed)
    else:
        log.info("Skipping: Contradictions (--structural-only)")

    total_elapsed = time.time() - total_start

    report = generate_report(all_issues)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"lint-{today_iso()}.md"
    report_path.write_text(report, encoding="utf-8")
    log.info("Report saved to: %s", report_path)

    # ── Fix mode ──────────────────────────────────────────────────────
    if args.fix and all_issues:
        fixable = [i for i in all_issues if i["check"] in (LLM_FIXABLE_CHECKS | {"missing_backlink"})]
        if fixable:
            log.info("")
            log.info("Running fixes (%d fixable issues)...", len(fixable))
            fix_summary = run_fixes(all_issues)
            log.info("")
            log.info(
                "Fix summary: %d auto-fixed, %d LLM-fixed, %d need compile, %d need manual review",
                fix_summary["auto_fixed"], fix_summary["llm_fixed"],
                fix_summary["skipped_compile"], fix_summary["skipped_manual"],
            )
        else:
            log.info("No auto-fixable issues found (remaining issues need compile or manual review)")
    elif args.fix:
        log.info("No issues to fix.")

    state = load_state()
    state["last_lint"] = now_iso()
    save_state(state)

    errors = sum(1 for i in all_issues if i["severity"] == "error")
    warnings = sum(1 for i in all_issues if i["severity"] == "warning")
    suggestions = sum(1 for i in all_issues if i["severity"] == "suggestion")
    log.info("Results: %d errors, %d warnings, %d suggestions (%.2fs total)", errors, warnings, suggestions, total_elapsed)

    if errors > 0:
        log.warning("Errors found — knowledge base needs attention!")
        return 1
    return 0


if __name__ == "__main__":
    exit(main())

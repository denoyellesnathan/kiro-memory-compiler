# AGENTS.md - Personal Knowledge Base Schema

> Adapted from [Andrej Karpathy's LLM Knowledge Base](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) architecture.
> Instead of ingesting external articles, this system compiles knowledge from your own AI conversations.

## The Compiler Analogy

```
daily/          = source code    (your conversations - the raw material)
LLM             = compiler       (extracts and organizes knowledge)
knowledge/      = executable     (structured, queryable knowledge base)
lint            = test suite     (health checks for consistency)
queries         = runtime        (using the knowledge)
```

You don't manually organize your knowledge. You have conversations, and the LLM handles the synthesis, cross-referencing, and maintenance.

---

## Architecture

### Layer 1: `daily/` - Conversation Logs (Immutable Source)

Daily logs capture what happened in your AI coding sessions. These are the "raw sources" - append-only, never edited after the fact.

```
daily/
├── 2026-04-01.md
├── 2026-04-02.md
├── ...
```

Each file follows this format:

```markdown
# Daily Log: YYYY-MM-DD

## Sessions

### Session (HH:MM) - Brief Title

**Context:** What the user was working on.

**Key Exchanges:**
- User asked about X, assistant explained Y
- Decided to use Z approach because...
- Discovered that W doesn't work when...

**Decisions Made:**
- Chose library X over Y because...
- Architecture: went with pattern Z

**Lessons Learned:**
- Always do X before Y to avoid...
- The gotcha with Z is that...

**Action Items:**
- [ ] Follow up on X
- [ ] Refactor Y when time permits
```

### Layer 2: `knowledge/` - Compiled Knowledge (LLM-Owned)

The LLM owns this directory entirely. Humans read it but rarely edit it directly.

```
knowledge/
├── index.md              # Master catalog - every article with one-line summary
├── log.md                # Append-only chronological build log
├── concepts/             # Atomic knowledge articles
├── connections/          # Cross-cutting insights linking 2+ concepts
└── qa/                   # Filed query answers (compounding knowledge)
```

### Layer 3: This File (AGENTS.md)

The schema that tells the LLM how to compile and maintain the knowledge base. This is the "compiler specification."

---

## Structural Files

### `knowledge/index.md` - Master Catalog

A table listing every knowledge article. This is the primary retrieval mechanism - the LLM reads this FIRST when answering any query, then selects relevant articles to read in full.

Format:

```markdown
# Knowledge Base Index

## Authentication & Security
| Article | Tags | Summary | Compiled From | Updated |
|---------|------|---------|---------------|---------|
| [[concepts/supabase-auth]] | auth, supabase, rls | Row-level security patterns and JWT gotchas | daily/2026-04-02.md | 2026-04-02 |
| [[connections/auth-and-webhooks]] | auth, webhooks, stripe | Token verification patterns shared across Supabase auth and Stripe webhooks | daily/2026-04-02.md, daily/2026-04-04.md | 2026-04-04 |

## Infrastructure & CI/CD
| Article | Tags | Summary | Compiled From | Updated |
|---------|------|---------|---------------|---------|
| [[concepts/nextjs-project-structure]] | nextjs, project-setup | ... | daily/2026-04-01.md | 2026-04-01 |
```

Articles are grouped by domain. The compiler infers the domain from the article's tags:
- Each `## Domain Name` section contains its own full table (with header row)
- Domain names should be broad enough to hold 2-10 articles (e.g., "Logging & Debugging", "Infrastructure & CI/CD", "API Gateway")
- If an article spans domains, list it in the primary one and add `(also: Other Domain)` after the summary
- New domains are created organically as articles accumulate — don't pre-define empty sections
- Within each domain, sort articles alphabetically by path

The Tags column is populated from the article's frontmatter `tags` field (comma-separated). For connection articles that lack a `tags` field, derive tags from the connected concepts' tags. This column enables fast filtering during queries — the LLM can scan domain headers first, then tags, then summaries.

### `knowledge/log.md` - Build Log

Append-only chronological record of every compile, query, and lint operation.

Format:

```markdown
# Build Log

## [2026-04-01T14:30:00] compile | Daily Log 2026-04-01
- Source: daily/2026-04-01.md
- Articles created: [[concepts/nextjs-project-structure]], [[concepts/tailwind-setup]]
- Articles updated: (none)

## [2026-04-02T09:00:00] query | "How do I handle auth redirects?"
- Consulted: [[concepts/supabase-auth]], [[concepts/nextjs-middleware]]
- Filed to: [[qa/auth-redirect-handling]]
```

---

## Article Formats

### Concept Articles (`knowledge/concepts/`)

One article per atomic piece of knowledge. These are facts, patterns, decisions, preferences, and lessons extracted from your conversations.

```markdown
---
title: "Concept Name"
aliases: [alternate-name, abbreviation]
tags: [domain, topic]
sources:
  - "daily/2026-04-01.md"
  - "daily/2026-04-03.md"
created: 2026-04-01
updated: 2026-04-03
---

# Concept Name

[2-4 sentence core explanation]

## Key Points

- [Bullet points, each self-contained]

## Details

[Deeper explanation, encyclopedia-style paragraphs]

## Related Concepts

- [[concepts/related-concept]] - How it connects

## Sources

- [[daily/2026-04-01.md]] - Initial discovery during project setup
- [[daily/2026-04-03.md]] - Updated after debugging session
```

### Connection Articles (`knowledge/connections/`)

Cross-cutting synthesis linking 2+ concepts. Created when a conversation reveals a non-obvious relationship.

```markdown
---
title: "Connection: X and Y"
connects:
  - "concepts/concept-x"
  - "concepts/concept-y"
sources:
  - "daily/2026-04-04.md"
created: 2026-04-04
updated: 2026-04-04
---

# Connection: X and Y

## The Connection

[What links these concepts]

## Key Insight

[The non-obvious relationship discovered]

## Evidence

[Specific examples from conversations]

## Related Concepts

- [[concepts/concept-x]]
- [[concepts/concept-y]]
```

### Q&A Articles (`knowledge/qa/`)

Filed answers from queries. Every complex question answered by the system can be permanently stored, making future queries smarter.

```markdown
---
title: "Q: Original Question"
question: "The exact question asked"
consulted:
  - "concepts/article-1"
  - "concepts/article-2"
filed: 2026-04-05
---

# Q: Original Question

## Answer

[The synthesized answer with [[wikilinks]] to sources]

## Sources Consulted

- [[concepts/article-1]] - Relevant because...
- [[concepts/article-2]] - Provided context on...

## Follow-Up Questions

- What about edge case X?
- How does this change if Y?
```

---

## Core Operations

### 1. Compile (daily/ -> knowledge/)

When processing a daily log:

1. Read the daily log file
2. Read `knowledge/index.md` to understand current knowledge state
3. Read existing articles that may need updating
4. For each piece of knowledge found in the log:
   - If an existing concept article covers this topic: UPDATE it with new information, add the daily log as a source
   - If it's a new topic: CREATE a new `concepts/` article
5. If the log reveals a non-obvious connection between 2+ existing concepts: CREATE a `connections/` article
6. UPDATE `knowledge/index.md` with new/modified entries — include the Tags column populated from the article's frontmatter `tags` field. Place each article under the appropriate `## Domain` section (infer domain from tags; create new domain sections as needed)
7. APPEND to `knowledge/log.md`

**Important guidelines:**
- A single daily log may touch 3-10 knowledge articles
- Prefer updating existing articles over creating near-duplicates
- Use Obsidian-style `[[wikilinks]]` with full relative paths from knowledge/
- Write in encyclopedia style - factual, concise, self-contained
- Every article must have YAML frontmatter
- Every article must link back to its source daily logs

### 2. Query (Ask the Knowledge Base)

1. Read `knowledge/index.md` (the master catalog)
2. Based on the question, identify 3-10 relevant articles from the index
3. Read those articles in full
4. Synthesize an answer with `[[wikilink]]` citations
5. If `--file-back` is specified: create a `knowledge/qa/` article and update index.md and log.md

**Why this works without RAG:** At personal knowledge base scale (50-500 articles), the LLM reading a structured index outperforms cosine similarity. The LLM understands what the question is really asking and selects pages accordingly. Embeddings find similar words; the LLM finds relevant concepts.

### 3. Lint (Health Checks)

Seven checks, run periodically:

1. **Broken links** - `[[wikilinks]]` pointing to non-existent articles
2. **Orphan pages** - Articles with zero inbound links from other articles
3. **Orphan sources** - Daily logs that haven't been compiled yet
4. **Stale articles** - Source daily log changed since article was last compiled
5. **Contradictions** - Conflicting claims across articles (requires LLM judgment)
6. **Missing backlinks** - A links to B but B doesn't link back to A
7. **Sparse articles** - Below 200 words, likely incomplete

Output: a markdown report with severity levels (error, warning, suggestion).

---

## Conventions

- **Wikilinks:** Use Obsidian-style `[[path/to/article]]` without `.md` extension
- **Writing style:** Encyclopedia-style, factual, third-person where appropriate
- **Dates:** ISO 8601 (YYYY-MM-DD for dates, full ISO for timestamps in log.md)
- **File naming:** lowercase, hyphens for spaces (e.g., `supabase-row-level-security.md`)
- **Frontmatter:** Every article must have YAML frontmatter with at minimum: title, sources, created, updated. Q&A articles must also include `question` and `consulted` fields per the qa/ article format.
- **Sources:** Always link back to the daily log(s) that contributed to an article

---

## Full Project Structure

```
llm-personal-kb/
|-- .kiro/
|   |-- agents/
|       |-- memory-compiler.json     # Agent config with hooks (activates via --agent)
|-- .gitignore                       # Excludes runtime state, temp files, caches
|-- AGENTS.md                        # This file - schema + full technical reference
|-- README.md                        # Concise overview + quick start
|-- pyproject.toml                   # Dependencies (at root so hooks can find it)
|-- daily/                           # "Source code" - conversation logs (immutable)
|-- knowledge/                       # "Executable" - compiled knowledge (LLM-owned)
|   |-- index.md                     #   Master catalog - THE retrieval mechanism
|   |-- log.md                       #   Append-only build log
|   |-- concepts/                    #   Atomic knowledge articles
|   |-- connections/                 #   Cross-cutting insights linking 2+ concepts
|   |-- qa/                          #   Filed query answers (compounding knowledge)
|-- scripts/                         # CLI tools (invoke kiro-cli headless)
|   |-- compile.py                   #   Compile daily logs -> knowledge articles
|   |-- query.py                     #   Ask questions (index-guided, no RAG)
|   |-- lint.py                      #   7 health checks
|   |-- flush.py                     #   Extract memories from conversations (background)
|   |-- config.py                    #   Path constants
|   |-- utils.py                     #   Shared helpers
|-- hooks/                           # Kiro CLI hooks
|   |-- agent-spawn.py               #   Injects knowledge into every session
|   |-- stop.py                      #   Captures context after each turn -> flush
|-- reports/                         # Lint reports (gitignored)
```

---

## Hook System (Automatic Capture)

Hooks are configured in `.kiro/agents/memory-compiler.json` and fire automatically when you use Kiro CLI with the `--agent memory-compiler` flag.

### `.kiro/agents/memory-compiler.json` Format

```json
{
  "name": "memory-compiler",
  "description": "Personal knowledge base compiler",
  "instructions": ["..."],
  "hooks": {
    "agentSpawn": [{ "command": "python hooks/agent-spawn.py", "timeout_ms": 5000 }],
    "stop": [{ "command": "python hooks/stop.py", "timeout_ms": 10000 }]
  }
}
```

### Hook Details

**`agent-spawn.py`** (agentSpawn)
- Pure local I/O, no API calls, runs in under 1 second
- Reads `knowledge/index.md` and the most recent daily log
- Outputs plain text to STDOUT — Kiro adds this directly to agent context
- Max context: 20,000 characters

**`stop.py`** (stop)
- Fires after every assistant response (each turn)
- Reads `assistant_response` from the hook event JSON on stdin
- Accumulates context across turns in `scripts/stop-hook-state.json`
- Every 5 minutes (if enough content has accumulated), spawns `flush.py` as a background process
- This replaces both SessionEnd and PreCompact from Claude Code — incremental capture means no data loss

### Background Flush Process (`flush.py`)

Spawned by the stop hook as a fully detached background process:
- **Windows:** `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` flags
- **Mac/Linux:** `start_new_session=True`

**What flush.py does:**
1. Reads the accumulated conversation context from the temp `.md` file
2. Skips if context is empty or if same session was flushed within 60 seconds (deduplication)
3. Calls `kiro-cli chat --no-interactive` with the context as prompt (no tools needed)
4. Kiro decides what's worth saving — returns structured bullet points or `FLUSH_OK`
5. Appends result to `daily/YYYY-MM-DD.md`
6. Cleans up temp context file
7. **End-of-day auto-compilation:** If it's past 6 PM local time and today's daily log has changed since its last compilation, spawns `compile.py` as another detached background process.

### Kiro JSONL Session Format

Kiro CLI stores sessions at `~/.kiro/sessions/cli/{uuid}.jsonl`. Messages use this format:

```python
entry = json.loads(line)
kind = entry.get("kind", "")       # "Prompt", "AssistantMessage", or "ToolResults"
data = entry.get("data", {})
content = data.get("content", [])   # list of {"kind": "text", "data": "..."} blocks
```

The stop hook doesn't need to parse session files — it receives `assistant_response` directly in the hook event JSON.

---

## Script Details

### compile.py - The Compiler

Uses `kiro-cli chat --no-interactive` with full tool trust:

```bash
kiro-cli chat --no-interactive --trust-all-tools --agent memory-compiler \
  "Compile this daily log into knowledge articles..."
```

- Builds a prompt with: current index, all existing articles, and the daily log
- Kiro reads the daily log, decides what concepts to extract, and writes files directly
- `--trust-all-tools` auto-approves all file operations
- `--agent memory-compiler` loads the agent config with AGENTS.md schema in instructions
- Incremental: tracks SHA-256 hashes of daily logs in `state.json`, skips unchanged files

**CLI:**
```bash
uv run python scripts/compile.py              # compile new/changed only
uv run python scripts/compile.py --all        # force recompile everything
uv run python scripts/compile.py --file daily/2026-04-01.md
uv run python scripts/compile.py --dry-run
```

### query.py - Index-Guided Retrieval

Loads the entire knowledge base into the prompt (index + all articles). No RAG.

At personal KB scale (50-500 articles), the LLM reading a structured index outperforms vector similarity. The LLM understands what you're really asking; cosine similarity just finds similar words.

**CLI:**
```bash
uv run python scripts/query.py "What auth patterns do I use?"
uv run python scripts/query.py "What's my error handling strategy?" --file-back
```

With `--file-back`, creates a Q&A article in `knowledge/qa/` and updates the index and log. This is the compounding loop - every question makes the KB smarter.

### lint.py - Health Checks

Seven checks:

| Check | Type | Catches |
|-------|------|---------|
| Broken links | Structural | `[[wikilinks]]` to non-existent articles |
| Orphan pages | Structural | Articles with zero inbound links |
| Orphan sources | Structural | Daily logs not yet compiled |
| Stale articles | Structural | Source logs changed since compilation |
| Missing backlinks | Structural | A links to B but B doesn't link back |
| Sparse articles | Structural | Under 200 words |
| Contradictions | LLM | Conflicting claims across articles |

The contradiction check uses `kiro-cli chat --no-interactive` (no tools needed).

**CLI:**
```bash
uv run python scripts/lint.py                    # all checks
uv run python scripts/lint.py --structural-only  # skip LLM check (free)
```

Reports saved to `reports/lint-YYYY-MM-DD.md`.

---

## State Tracking

`scripts/state.json` tracks:
- `ingested` - map of daily log filenames to SHA-256 hashes and compilation timestamps
- `query_count` - total queries run
- `last_lint` - timestamp of most recent lint

`scripts/last-flush.json` tracks flush deduplication (session_id + timestamp).

`scripts/stop-hook-state.json` tracks accumulated context between stop hook invocations.

All are gitignored and regenerated automatically.

---

## Dependencies

`pyproject.toml` (at project root):
- `python-dotenv>=1.0.0` - Environment variable management
- `tzdata>=2024.1` - Timezone data
- Python 3.12+, managed by [uv](https://docs.astral.sh/uv/)

**External requirement:** [Kiro CLI](https://kiro.dev/cli/) must be installed and authenticated (`KIRO_API_KEY` env var for headless mode, or interactive login for manual use).

---

## Costs

All operations use Kiro CLI headless mode, which requires a Kiro Pro, Pro+, or Power subscription with an API key. Operations consume credits from your subscription:

| Operation | Approximate Credits |
|-----------|-------------------|
| Compile one daily log | ~0.5-1.0 |
| Query (no file-back) | ~0.2-0.4 |
| Query (with file-back) | ~0.3-0.5 |
| Full lint (with contradictions) | ~0.2-0.3 |
| Structural lint only | 0 (no LLM) |
| Memory flush (per trigger) | ~0.1-0.2 |

---

## Customization

### Additional Article Types

Add directories like `people/`, `projects/`, `tools/` to `knowledge/`. Define the article format in this file (AGENTS.md) and update `utils.py`'s `list_wiki_articles()` to include them.

### Obsidian Integration

The knowledge base is pure markdown with `[[wikilinks]]` - works natively in Obsidian. Point a vault at `knowledge/` for graph view, backlinks, and search.

### Scaling Beyond Index-Guided Retrieval

At ~2,000+ articles / ~2M+ tokens, the index becomes too large for the context window. At that point, add hybrid RAG (keyword + semantic search) as a retrieval layer before the LLM. See Karpathy's recommendation of `qmd` by Tobi Lutke for search at scale.

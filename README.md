# LLM Personal Knowledge Base (Kiro Edition)

**Your AI conversations compile themselves into a searchable knowledge base.**

This project is a [Kiro](https://kiro.dev/) adaptation of [cole-medin/claude-memory-compiler](https://github.com/coleam00/claude-memory-compiler) by [Cole Medin](https://github.com/coleam00), which was originally built for Claude Code. The core architecture — daily logs, an LLM compiler, and index-guided retrieval — comes from [Andrej Karpathy's LLM Knowledge Base](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) design.

Instead of Claude Code hooks and the Claude Agent SDK, this version uses Kiro CLI's agent system (`kiro-cli chat --agent memory-compiler`) with `agentSpawn` and `stop` hooks to capture conversation context after each turn and periodically flush it to daily logs. The compilation, querying, and linting scripts have been adapted to use `kiro-cli chat --no-interactive` in place of the Claude Agent SDK.

## Quick Start

```bash
# 1. Clone and install
git clone <your-repo-url>
cd kiro-memory-compiler
uv sync

# 2. Set your Kiro API key (for headless mode)
export KIRO_API_KEY="your-key-here"

# 3. Run first-time setup (installs agent globally to ~/.kiro/agents/)
uv run python scripts/setup.py

# 4. Use from any directory — hooks activate automatically
kiro-cli chat --agent memory-compiler
```

The hooks activate automatically when using the `memory-compiler` agent:
- `agentSpawn` injects your knowledge base index into every session
- `stop` captures context after each turn and periodically flushes to daily logs
- After 6 PM, the next flush automatically triggers compilation

## How It Works

```
Conversation -> stop hook captures each turn -> flush.py extracts knowledge
    -> daily/YYYY-MM-DD.md -> compile.py -> knowledge/concepts/, connections/, qa/
        -> agentSpawn hook injects index into next session -> cycle repeats
```

- **Hooks** capture conversations automatically (stop hook fires after every assistant turn)
- **flush.py** calls `kiro-cli chat --no-interactive` to decide what's worth saving, and after 6 PM triggers end-of-day compilation
- **compile.py** turns daily logs into organized concept articles with cross-references
- **query.py** answers questions using index-guided retrieval (no RAG needed at personal scale)
- **lint.py** runs 7 health checks (broken links, orphans, contradictions, staleness)

## Key Commands

```bash
uv run python scripts/compile.py                    # compile new daily logs
uv run python scripts/query.py "question"            # ask the knowledge base
uv run python scripts/query.py "question" --file-back # ask + save answer back
uv run python scripts/lint.py                        # run health checks
uv run python scripts/lint.py --structural-only      # free structural checks only
```

## Requirements

- [Kiro CLI](https://kiro.dev/cli/) installed and authenticated
- `KIRO_API_KEY` environment variable set (for headless operations)
- Kiro Pro, Pro+, or Power subscription
- Python 3.12+ with [uv](https://docs.astral.sh/uv/)

## Why No RAG?

Karpathy's insight: at personal scale (50-500 articles), the LLM reading a structured `index.md` outperforms vector similarity. The LLM understands what you're really asking; cosine similarity just finds similar words. RAG becomes necessary at ~2,000+ articles when the index exceeds the context window.

## Credits

- Original project: [claude-memory-compiler](https://github.com/coleam00/claude-memory-compiler) by [Cole Medin](https://github.com/coleam00)
- Architecture: [Andrej Karpathy's LLM Knowledge Base](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

## Technical Reference

See **[AGENTS.md](AGENTS.md)** for the complete technical reference: article formats, hook architecture, script internals, and customization options.

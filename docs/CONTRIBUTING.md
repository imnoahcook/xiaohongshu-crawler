# Contributing Guide

## Development Setup

### Prerequisites

- Python 3.10+
- The [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
# Clone the repository
git clone https://github.com/imnoahcook/xiaohongshu-crawler.git && cd xiaohongshu-crawler

# Install dependencies
uv sync

# Install Chromium
uv run playwright install chromium
```

By default the crawler targets https://www.rednote.com. To point it at another origin that serves the same web app (e.g. https://www.xiaohongshu.com), set the `REDNOTE_BASE_URL` environment variable (see `src/site.py`).

<!-- AUTO-GENERATED: commands-reference -->
## Available Commands

| Command | Description |
|------|------|
| `uv sync` | Install/sync dependencies |
| `uv run playwright install chromium` | Install the Chromium browser |
| `uv run python main.py` | Run the full crawl pipeline |
| `uv run python mcp_server.py` | Start the MCP server (stdio mode) |
| `uv run python mcp_server.py --transport sse` | Start the MCP server (SSE mode) |
| `uv run python mcp_server.py --transport streamable-http` | Start the MCP server (HTTP mode) |
| `uv run python scripts/verify_stealth.py` | Anti-detection check |
| `uv run python scripts/verify_login.py` | Login check |
| `uv run python scripts/verify_search.py` | Search collection check |
| `uv run python scripts/verify_note.py` | Note detail + comments check |
| `uv run python scripts/verify_e2e.py` | End-to-end integration check |
| `uv run python scripts/verify_mcp_tools.py` | MCP tools check |
| `uv run pytest --cov` | Run tests with coverage |
| `uv add <package>` | Add a new dependency |
<!-- /AUTO-GENERATED: commands-reference -->

## Verification

The project is tested with the verification scripts under `scripts/`. After adding a feature, run the relevant scripts to confirm it works.

```bash
# Verify anti-detection
uv run python scripts/verify_stealth.py

# Verify login
uv run python scripts/verify_login.py

# Verify search collection
uv run python scripts/verify_search.py

# Verify note detail + comments
uv run python scripts/verify_note.py

# End-to-end integration check
uv run python scripts/verify_e2e.py
```

Login is manual: on first run a headed browser opens rednote and you either scan the QR code with the rednote app or sign in with phone number + SMS code. The session is then saved to `auth_state/state.json` and reused.

### Writing verification scripts

When a new module is finished, add a matching verification script under `scripts/`:

- File name format: `verify_<module>.py`
- Must cover: the happy path, edge cases, and error recovery
- Use `asyncio.run()` as the entry point
- Report results through `logging`

## Code Style

- Follow PEP 8
- Use type hints
- Module-level docstrings + English inline comments
- Use `pathlib.Path` for paths
- Use the `logging` module for logs
- Catch specific exceptions and degrade gracefully
- Use `TYPE_CHECKING` guards to avoid runtime circular imports

## Git Workflow

### Commit format

```
<type>(<scope>): description in English
```

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`

Examples:
- `feat(search): deduplicate search results`
- `fix(parser): handle missing element when parsing comments`

### Branching

- Main branch: `master`
- Feature branches: `feat/<feature-name>`

## PR Checklist

- [ ] Code follows the project's coding conventions
- [ ] New features have a matching verification script
- [ ] Verification scripts pass
- [ ] Commit messages follow the Conventional Commits format
- [ ] No hard-coded secrets or sensitive information

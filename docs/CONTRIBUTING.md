# Contributing Guide

## Development Setup

### Prerequisites

- Python 3.10+
- The [uv](https://docs.astral.sh/uv/) package manager
- Google Chrome, running, with remote debugging allowed (see below)

### Installation

```bash
# Clone the repository
git clone https://github.com/imnoahcook/xiaohongshu-crawler.git && cd xiaohongshu-crawler

# Install dependencies
uv sync
```

### Connecting to Chrome

The crawler does not launch a browser. It attaches over CDP to the Chrome you already have open and works in new tabs there, using your existing rednote login. It closes only its own tabs and leaves Chrome open.

One-time setup: open `chrome://inspect/#remote-debugging` in Chrome and enable "Allow remote debugging for this browser instance". Chrome then shows an "Allow" prompt on every new connection.

If your Chrome user data directory is not in the default location for your OS, set `REDNOTE_CHROME_USER_DATA_DIR` (see `src/chrome.py`).

To get only one prompt, use the background daemon: `uv run python rednote.py start` attaches once and stays attached, and the other `rednote.py` commands talk to it. `main.py` and the `scripts/verify_*.py` scripts attach directly, so each run prompts once.

By default the crawler targets https://www.rednote.com. To point it at another origin that serves the same web app (e.g. https://www.xiaohongshu.com), set the `REDNOTE_BASE_URL` environment variable (see `src/site.py`).

<!-- AUTO-GENERATED: commands-reference -->
## Available Commands

| Command | Description |
|------|------|
| `uv sync` | Install/sync dependencies |
| `uv run python rednote.py start` | Start the background daemon (MCP server on 127.0.0.1:8765) and attach to Chrome |
| `uv run python rednote.py status` | Check the daemon and the rednote login |
| `uv run python rednote.py search <kw> -n N` | Search notes by keyword |
| `uv run python rednote.py note <url>` | Collect one note's details + comments |
| `uv run python rednote.py crawl <kw>` | Search, collect details + comments, save |
| `uv run python rednote.py saved [kw]` | List saved data files |
| `uv run python rednote.py stop` | Detach and stop the daemon |
| `uv run python main.py` | Run the full crawl pipeline from `config/settings.yaml` |
| `uv run python mcp_server.py` | Start the MCP server (stdio mode) |
| `uv run python mcp_server.py --transport sse` | Start the MCP server (SSE mode) |
| `uv run python mcp_server.py --transport streamable-http` | Start the MCP server (HTTP mode) |
| `uv run python scripts/verify_guest_feed.py` | Home feed smoke test (works logged out) |
| `uv run python scripts/verify_login.py` | Login check |
| `uv run python scripts/verify_search.py` | Search collection check |
| `uv run python scripts/verify_note.py` | Note detail + comments check |
| `uv run python scripts/verify_e2e.py` | End-to-end integration check |
| `uv run python scripts/verify_mcp_tools.py` | MCP tools check |
| `uv run pytest --cov` | Run tests with coverage |
| `uv add <package>` | Add a new dependency |
<!-- /AUTO-GENERATED: commands-reference -->

## Verification

Unit tests run with `uv run pytest`. Behaviour against the live site is checked with the verification scripts under `scripts/`, which attach to your Chrome. After adding a feature, run the relevant scripts to confirm it works.

```bash
# Smoke test: browser connection, card selectors, parser (no login needed)
uv run python scripts/verify_guest_feed.py

# Verify login
uv run python scripts/verify_login.py

# Verify search collection
uv run python scripts/verify_search.py

# Verify note detail + comments
uv run python scripts/verify_note.py

# End-to-end integration check
uv run python scripts/verify_e2e.py
```

Login lives in Chrome itself: if you are already logged in to rednote there, there is nothing to do. Otherwise the crawler opens the login page in a tab and waits for you to scan the QR code with the rednote app or sign in with phone number + SMS code. The crawler stores no login state of its own.

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

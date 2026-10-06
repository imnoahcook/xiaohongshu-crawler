# CLAUDE.md — rednote-crawler

## Project Overview

A data collection framework for rednote (https://www.rednote.com). It does not launch a browser: Playwright attaches over CDP to the Google Chrome the user already has open ("everyday Chrome") and works in new tabs there, using the user's existing rednote login.

Current status: **Phase 4 complete** (integration & polish). All phases are done.

## Tech Stack

- **Language:** Python 3.10+
- **Package manager:** uv (not pip)
- **Browser automation:** Playwright (async API), attached to the user's Chrome over CDP
- **MCP server / daemon:** mcp (FastMCP) over stdio, SSE, or streamable HTTP
- **Configuration:** PyYAML

## Common Commands

```bash
# Install dependencies (no browser download; the crawler uses your own Chrome)
uv sync

# CLI + background daemon (attaches to Chrome once, so only one "Allow" prompt)
uv run python rednote.py start               # start the daemon; click "Allow" in Chrome
uv run python rednote.py status              # daemon up and logged in?
uv run python rednote.py search coffee -n 10 # search notes
uv run python rednote.py note "<note url>"   # one note's details + comments
uv run python rednote.py crawl coffee -n 5   # search → details → comments → save
uv run python rednote.py saved [keyword]     # list saved data files
uv run python rednote.py stop                # detach and stop the daemon

# Full pipeline from config/settings.yaml (attaches directly; one prompt per run)
uv run python main.py

# Verification scripts (each attaches directly; one prompt per run)
uv run python scripts/verify_guest_feed.py   # home feed smoke test (works logged out)
uv run python scripts/verify_login.py        # login check
uv run python scripts/verify_search.py       # search collection check
uv run python scripts/verify_note.py         # note detail + comments check
uv run python scripts/verify_e2e.py          # end-to-end check
uv run python scripts/verify_mcp_tools.py    # MCP tools check

# Unit tests
uv run pytest

# Add a dependency
uv add <package-name>
```

## Project Structure

```
src/
├── site.py        # Target site config (BASE_URL, overridable via REDNOTE_BASE_URL)
├── chrome.py      # Finds the running Chrome's DevTools WebSocket URL (DevToolsActivePort)
├── browser.py     # Attaches Playwright to that Chrome over CDP (BrowserManager)
├── auth.py        # Login detection (user/me response) & manual login wait
├── session.py     # CrawlerSession: long-lived browser session behind the MCP tools
├── errors.py      # Structured error codes returned by the MCP tools
├── search.py      # Search result collection (infinite-scroll feed)
├── note.py        # Note detail collection (with retry logic)
├── comment.py     # Comment collection (top N)
├── parser.py      # Page data parsing (search cards / details / comments)
└── storage.py     # Data storage (JSON + Excel/xlsx)
scripts/           # Verification scripts (run against the live Chrome)
tests/             # pytest unit tests
config/settings.yaml  # Crawl config (keywords, limits, delays, storage)
main.py            # Full pipeline entry point (attaches directly)
mcp_server.py      # MCP server exposing the crawler as tools
rednote.py         # CLI client + background daemon launcher
```

## Architecture Notes

- **Async first:** all I/O uses async/await
- **Everyday Chrome over CDP:** `src/chrome.py` reads the DevTools port from Chrome's `DevToolsActivePort` file (user data dir overridable via `REDNOTE_CHROME_USER_DATA_DIR`); `BrowserManager` connects with `connect_over_cdp` and uses Chrome's default context
- **One-time setup:** open `chrome://inspect/#remote-debugging` in Chrome and enable "Allow remote debugging for this browser instance". Chrome shows an "Allow" prompt on every new connection
- **BrowserManager:** async context manager taking no arguments; `new_page()` opens a tab, `__aexit__` closes only the tabs it opened and leaves Chrome open
- **Daemon:** `rednote.py start` launches `mcp_server.py` over streamable HTTP on `127.0.0.1:8765` (port overridable via `REDNOTE_DAEMON_PORT`) in the background; the other `rednote.py` commands call its MCP tools. Over the HTTP transports the server stays attached to Chrome for the process lifetime, so there is only one "Allow" prompt
- **Target site:** `src/site.py` defines `BASE_URL` (default `https://www.rednote.com`); set the `REDNOTE_BASE_URL` env var to point at another origin such as `https://www.xiaohongshu.com`, which serves the same web app
- **Login:** lives in Chrome itself; nothing is saved by the crawler. If Chrome is not logged in to rednote, the crawler opens the login page in a tab and waits for a manual login (QR code with the rednote app, or phone number + SMS code)
- **Login detection:** `src/auth.py` reads the web app's own `/api/sns/web/v2/user/me` response (`guest` field), not the DOM
- **Externalized config:** YAML config file, so parameters can be tuned without code changes

## Workflow

### Complex tasks (multiple files, new features, architecture changes)

1. **Understand the requirements** — read the relevant code and docs first, find similar existing implementations, confirm the technical approach
2. **Plan** — design the approach with EnterPlanMode; start only after the user approves
3. **Implement step by step** — track progress with TodoWrite; make small changes, each one verifiable
4. **Verify and deliver** — run the verification scripts to confirm correctness and report the results

### Simple tasks (single-file changes, bug fixes)

Read the code → change it → verify. No planning step needed.

### General principles

- Always read the relevant code before implementing; never make suggestions about code you have not read
- For complex tasks, explore the codebase in parallel with the Task tool instead of slow serial searches
- After the same error occurs 3 times in a row, stop and reassess the approach
- No assumptions or guesses; conclusions must be backed by code or documentation

## Coding Strategy

- Prefer official SDKs and mainstream ecosystem libraries; avoid unnecessary in-house implementations
- Fix defects before adding new features
- Make small changes; keep the code runnable and verifiable after every change
- No placeholders or skeleton implementations; commit complete, working code
- Delete outdated content and redundant implementations promptly; do not keep useless backward compatibility
- Follow SOLID; each function/class has a single responsibility
- No premature abstraction; generalize only after 3 or more repetitions
- No "clever" tricks; readability comes first

## Code Style

- Follow PEP 8 and use type hints
- Module-level docstrings + English inline comments (describing intent, constraints, and usage)
- Use `pathlib.Path` for paths
- Use the `logging` module (format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`)
- Exception handling: catch specific exceptions and degrade gracefully
- Use `TYPE_CHECKING` guards to avoid runtime circular imports
- Follow the existing code style, including import order, naming, and formatting

## Testing & Verification

- Unit tests: `uv run pytest` (under `tests/`)
- Live verification: the scripts under `scripts/` (`verify_*.py`); they attach to the user's Chrome, so each run triggers an "Allow" prompt
- When a new module is finished, write a matching verification script and put it in `scripts/`
- Verification scripts must cover: the happy path, edge cases, and error recovery
- When a test fails, report the symptom, reproduction steps, and an initial analysis

## Git Conventions

- **Conventional Commits:** `type(scope): description in English`
- Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`
- Main branch: `master`; feature branches: `feat/<feature-name>`
- Do not commit proactively; commit only when the user asks
- Do not push proactively; push only when the user asks

## Roadmap

- **Phase 1** ✅ Foundation (browser + auth)
- **Phase 2** ✅ Search collection (search.py, parser.py, storage.py)
- **Phase 3** ✅ Details & comments (note.py, comment.py)
- **Phase 4** ✅ Integration & polish (full pipeline, logging, end-to-end tests)

## Important Paths

- Plan document: `.plan/rednote-crawler-plan.md` (technical blueprint; read before implementing)
- Config file: `config/settings.yaml`
- Data output: `data/` (gitignored)
- Daemon pid and logs: `logs/daemon.pid`, `logs/daemon.log`, `logs/mcp_server.log` (gitignored)
- Chrome's DevTools port file: `<Chrome user data dir>/DevToolsActivePort` (read-only input)

## Communication Language

Use English for all communication, code comments, documentation, and commit messages.

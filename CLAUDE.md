# CLAUDE.md — rednote-crawler

## Project Overview

A data collection framework for rednote (https://www.rednote.com). It drives a real browser with Playwright and uses two layers of anti-detection (playwright-stealth + browserforge).

Current status: **Phase 4 complete** (integration & polish). All phases are done.

## Tech Stack

- **Language:** Python 3.10+
- **Package manager:** uv (not pip)
- **Browser automation:** Playwright (async API)
- **Anti-detection:** playwright-stealth + browserforge
- **Configuration:** PyYAML

## Common Commands

```bash
# Install dependencies
uv sync
uv run playwright install chromium

# Run the main program
uv run python main.py

# Verification scripts
uv run python scripts/verify_stealth.py    # anti-detection check
uv run python scripts/verify_login.py      # login check
uv run python scripts/verify_search.py     # search collection check
uv run python scripts/verify_note.py       # note detail + comments check

# Add a dependency
uv add <package-name>
```

## Project Structure

```
src/
├── site.py        # Target site config (BASE_URL, overridable via REDNOTE_BASE_URL)
├── stealth.py     # Anti-detection config (fingerprint generation + stealth injection)
├── browser.py     # Playwright browser lifecycle management (BrowserManager)
├── auth.py        # Login & session management
├── search.py      # Search result collection (infinite-scroll feed)
├── note.py        # Note detail collection (with retry logic)
├── comment.py     # Comment collection (top N)
├── parser.py      # Page data parsing (search cards / details / comments)
└── storage.py     # Data storage (JSON + Excel/xlsx)
scripts/           # Verification scripts
config/settings.yaml  # Crawl config (keywords, delays, browser options)
main.py            # Entry point
```

## Architecture Notes

- **Async first:** all I/O uses async/await
- **BrowserManager:** async context manager that owns the browser lifecycle
- **Target site:** `src/site.py` defines `BASE_URL` (default `https://www.rednote.com`); set the `REDNOTE_BASE_URL` env var to point at another origin such as `https://www.xiaohongshu.com`, which serves the same web app
- **Session persistence:** login state is saved to `auth_state/state.json` and restored automatically on the next start
- **Login:** manual, in a headed browser — scan the QR code with the rednote app, or use phone number + SMS code
- **Two-layer anti-detection:** environment level (removing navigator.webdriver) + fingerprint level (WebGL/Canvas)
- **Browser context:** no pinned timezone; locale comes from the generated fingerprint and falls back to `en-US`
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

- Current verification method: the scripts under `scripts/` (verify_stealth.py, verify_login.py)
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

- **Phase 1** ✅ Foundation (browser + anti-detection + auth)
- **Phase 2** ✅ Search collection (search.py, parser.py, storage.py)
- **Phase 3** ✅ Details & comments (note.py, comment.py)
- **Phase 4** ✅ Integration & polish (full pipeline, logging, end-to-end tests)

## Important Paths

- Plan document: `.plan/rednote-crawler-plan.md` (technical blueprint; read before implementing)
- Config file: `config/settings.yaml`
- Login state: `auth_state/state.json` (gitignored)
- Data output: `data/` (gitignored)

## Communication Language

Use English for all communication, code comments, documentation, and commit messages.

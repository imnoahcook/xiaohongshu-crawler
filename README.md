# rednote-crawler

A data collection framework and MCP server for [rednote.com](https://www.rednote.com), the international web frontend of Xiaohongshu (RED).

It drives a real browser with Playwright, keeps you logged in between runs, and exposes search, note detail and comment collection both as a CLI pipeline and as MCP tools that AI assistants (Claude Desktop / Claude Code / Cursor) can call directly.

This is an English-language fork of [yangsijie666/xiaohongshu-crawler](https://github.com/yangsijie666/xiaohongshu-crawler), retargeted from xiaohongshu.com to rednote.com.

## Features

- **MCP server**: AI assistants can search rednote and collect note details and comments
- **Multiple transports**: stdio (local) / SSE (remote) / Streamable HTTP
- Keyword search with infinite-scroll loading
- Note details: title, body, engagement counts, tags, images / video
- Comments: top N comments with user info and IP location
- Browser fingerprinting via playwright-stealth + browserforge
- Persistent login state: log in once, later runs reuse the saved session
- Output: raw JSON plus a 3-sheet Excel workbook
- Timeouts, automatic browser crash recovery, and login-expiry detection

## What needs a login

rednote.com only shows the home explore feed to logged-out visitors. Search results, note detail pages and comments all redirect to the login page, so everything except `scripts/verify_guest_feed.py` needs a logged-in session.

Login is done by you, in the browser window the crawler opens: scan the QR code with the rednote app, or use a phone number and SMS code. The session is saved to `auth_state/state.json` (gitignored).

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)

## Quick start

```bash
# 1. Clone
git clone https://github.com/imnoahcook/xiaohongshu-crawler.git && cd xiaohongshu-crawler

# 2. Install dependencies
uv sync

# 3. Install the browser
uv run playwright install chromium

# 4. Smoke test against the live site (no login needed)
uv run python scripts/verify_guest_feed.py

# 5. Log in once (QR code or phone number)
uv run python scripts/verify_login.py

# 6. Run the full pipeline
uv run python main.py
```

## MCP server

### Option A: stdio (recommended for local use)

Add to the Claude Desktop config (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "rednote-crawler": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/xiaohongshu-crawler", "python", "mcp_server.py"],
      "env": {}
    }
  }
}
```

### Option B: SSE (remote deployment)

```bash
uv run python mcp_server.py --transport sse --host 0.0.0.0 --port 8000
```

Client config:

```json
{
  "mcpServers": {
    "rednote-crawler": {
      "url": "http://your-server:8000/sse"
    }
  }
}
```

### Option C: Streamable HTTP

```bash
uv run python mcp_server.py --transport streamable-http --host 0.0.0.0 --port 8000
```

### Tools

| Tool | Description | Latency |
|------|-------------|---------|
| `check_login_status` | Check whether the saved session is logged in | 5-10s |
| `search_notes` | Search notes by keyword (`max_count` 1-50) | 30-90s |
| `get_note_detail` | Collect one note's details and comments | 15-60s |
| `crawl_keyword` | Full pipeline: search → details → comments → save | 2-15min |
| `get_saved_data` | Query locally saved data files | <1s |

## Commands

| Command | Description |
|---------|-------------|
| `uv sync` | Install / sync dependencies |
| `uv run playwright install chromium` | Install Chromium |
| `uv run python main.py` | Run the full collection pipeline |
| `uv run python mcp_server.py` | Start the MCP server (stdio) |
| `uv run python mcp_server.py --transport sse` | Start the MCP server (SSE) |
| `uv run python scripts/verify_guest_feed.py` | Live smoke test, no login needed |
| `uv run python scripts/verify_login.py` | Log in and save the session |
| `uv run python scripts/verify_stealth.py` | Check the browser fingerprint |
| `uv run python scripts/verify_search.py` | Verify search collection |
| `uv run python scripts/verify_note.py` | Verify note detail + comment collection |
| `uv run pytest --cov` | Run tests with coverage |

## Configuration

Edit `config/settings.yaml`:

| Key | Default | Description |
|-----|---------|-------------|
| `crawler.keywords` | `["coffee"]` | Search keywords |
| `crawler.max_notes_per_keyword` | `20` | Max notes collected per keyword |
| `crawler.max_comments_per_note` | `20` | Max comments collected per note |
| `crawler.scroll_pause` | `1.5` | Wait after each scroll (seconds) |
| `crawler.page_load_timeout` | `30` | Page load timeout (seconds) |
| `delay.between_notes` | `[2, 5]` | Random delay range between notes (seconds) |
| `delay.between_searches` | `[3, 8]` | Random delay range between searches (seconds) |
| `browser.headless` | `false` | Headless mode |
| `storage.output_dir` | `"data"` | Output directory |
| `storage.save_raw_json` | `true` | Save raw JSON |
| `storage.save_xlsx` | `true` | Save Excel |

### Target site

The crawler targets `https://www.rednote.com` by default. xiaohongshu.com serves the same web app, so you can point the crawler at it with an environment variable:

```bash
REDNOTE_BASE_URL=https://www.xiaohongshu.com uv run python main.py
```

Sessions are per-site: log in again after switching.

## Output

```
data/
├── raw/
│   ├── {keyword}_{timestamp}.json          # Search results
│   └── notes_{keyword}_{timestamp}.json    # Note details + comments
└── processed/
    └── {keyword}_{timestamp}.xlsx          # Excel workbook
        ├── Sheet 1: Search Results
        ├── Sheet 2: Note Details
        └── Sheet 3: Comments
```

Engagement counts are normalised to integers whatever format the site renders them in (`3.4万`, `1.2K`, `10万+`).

## Project structure

```
mcp_server.py          # MCP server entry point (stdio / SSE / HTTP)
main.py                # CLI pipeline entry point
src/
├── site.py            # Target site URLs (REDNOTE_BASE_URL)
├── session.py         # MCP session (browser lifecycle + concurrency lock)
├── errors.py          # Unified error format
├── stealth.py         # Fingerprint generation + stealth patches
├── browser.py         # Playwright browser lifecycle
├── auth.py            # Login & session persistence
├── search.py          # Search collection (infinite scroll)
├── note.py            # Note detail collection (with retries)
├── comment.py         # Comment collection (top N)
├── parser.py          # Page data parsing
└── storage.py         # Storage (JSON + Excel)
scripts/               # Verification scripts
config/                # YAML configuration
tests/                 # Test suite
```

## Dependencies

| Package | Purpose |
|---------|---------|
| playwright | Browser automation (async API) |
| playwright-stealth | Stealth patches |
| browserforge | Browser fingerprint generation |
| mcp[cli] | MCP protocol SDK |
| uvicorn | ASGI server (SSE / HTTP transports) |
| starlette | ASGI framework (SSE / HTTP transports) |
| pyyaml | YAML configuration |
| openpyxl | Excel workbook generation |

## Responsible use

Use this with your own account, keep the default delays and modest volumes, and respect rednote's terms of service and the privacy of the people whose posts and comments you collect.

## License

MIT

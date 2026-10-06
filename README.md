# rednote-crawler

A data collection framework and MCP server for [rednote.com](https://www.rednote.com), the international web frontend of Xiaohongshu (RED).

It works inside the Chrome you already have open, in new tabs, using your existing rednote login, and exposes search, note detail and comment collection both as a CLI pipeline and as MCP tools that AI assistants (Claude Desktop / Claude Code / Cursor) can call directly.

This is an English-language fork of [yangsijie666/xiaohongshu-crawler](https://github.com/yangsijie666/xiaohongshu-crawler), retargeted from xiaohongshu.com to rednote.com.

## Features

- **MCP server**: AI assistants can search rednote and collect note details and comments
- **Multiple transports**: stdio (local) / SSE (remote) / Streamable HTTP
- Keyword search with infinite-scroll loading
- Note details: title, body, engagement counts, tags, images / video
- Comments: top N comments with user info and IP location
- Uses your everyday Chrome: no separate browser, no separate login, nothing to keep in sync
- Background daemon that stays attached to Chrome, with a small CLI (`rednote.py`)
- Output: raw JSON plus a 3-sheet Excel workbook
- Timeouts, automatic reconnection, and login-expiry detection

## How it connects to Chrome

The crawler never launches a browser. It attaches to your running Google Chrome over the DevTools protocol, opens its own tabs there, and closes only those tabs when it is done.

One-time setup: open `chrome://inspect/#remote-debugging` in Chrome and turn on **Allow remote debugging for this browser instance**.

Chrome asks you to **Allow** each new debugging connection. To see that prompt only once, use the daemon: `rednote.py start` attaches once and stays attached in the background, and every later command goes through it.

## What needs a login

rednote.com only shows the home explore feed to logged-out visitors. Search results, note detail pages and comments all redirect to the login page.

If you are already logged in to rednote.com in Chrome, there is nothing to do. Otherwise `scripts/verify_login.py` opens the login page in a tab and waits while you scan the QR code with the rednote app or use a phone number and SMS code.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- Google Chrome, running, with remote debugging allowed (see above)

## Quick start

```bash
# 1. Clone
git clone https://github.com/imnoahcook/xiaohongshu-crawler.git && cd xiaohongshu-crawler

# 2. Install dependencies
uv sync

# 3. Start the background daemon (click "Allow" in Chrome once)
uv run python rednote.py start

# 4. Check the daemon and your rednote login
uv run python rednote.py status

# 5. Use it
uv run python rednote.py search coffee -n 10
uv run python rednote.py note "https://www.rednote.com/explore/<id>?xsec_token=..."
uv run python rednote.py crawl coffee -n 5      # search → details → comments → data/
uv run python rednote.py saved

# 6. Detach when you are done
uv run python rednote.py stop
```

The daemon is the MCP server below running over HTTP on `127.0.0.1:8765` (change the port with `REDNOTE_DAEMON_PORT`); its log is `logs/daemon.log`.

`uv run python main.py` runs the keywords in `config/settings.yaml` without the daemon; it attaches to Chrome directly, so it prompts once per run.

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
| `uv run python rednote.py start` / `stop` | Start / stop the background daemon |
| `uv run python rednote.py status` | Check the daemon and the rednote login |
| `uv run python rednote.py search <keyword>` | Search notes |
| `uv run python rednote.py note <url>` | One note's details and comments |
| `uv run python rednote.py crawl <keyword>` | Full pipeline, saved to `data/` |
| `uv run python main.py` | Run the pipeline for the configured keywords |
| `uv run python mcp_server.py` | Start the MCP server (stdio) |
| `uv run python scripts/verify_guest_feed.py` | Live smoke test of the home feed |
| `uv run python scripts/verify_login.py` | Check the login, or wait for you to log in |
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
| `storage.output_dir` | `"data"` | Output directory |
| `storage.save_raw_json` | `true` | Save raw JSON |
| `storage.save_xlsx` | `true` | Save Excel |

### Target site

The crawler targets `https://www.rednote.com` by default. xiaohongshu.com serves the same web app, so you can point the crawler at it with an environment variable:

```bash
REDNOTE_BASE_URL=https://www.xiaohongshu.com uv run python main.py
```

Logins are per-site: you need to be logged in to that site in Chrome.

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
rednote.py             # CLI client + background daemon control
mcp_server.py          # MCP server entry point (stdio / SSE / HTTP)
main.py                # CLI pipeline entry point
src/
├── site.py            # Target site URLs (REDNOTE_BASE_URL)
├── chrome.py          # Finds the running Chrome's DevTools endpoint
├── session.py         # MCP session (Chrome connection + concurrency lock)
├── errors.py          # Unified error format
├── browser.py         # Attaches Playwright to Chrome, manages the crawler's tabs
├── auth.py            # Login detection & guided login
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
| playwright | Drives Chrome over CDP (async API) |
| mcp[cli] | MCP protocol SDK |
| uvicorn | ASGI server (SSE / HTTP transports) |
| starlette | ASGI framework (SSE / HTTP transports) |
| pyyaml | YAML configuration |
| openpyxl | Excel workbook generation |

## Responsible use

This runs in your own browser with your own account, so what it does is attributable to you. Use it keep the default delays and modest volumes, and respect rednote's terms of service and the privacy of the people whose posts and comments you collect.

## License

MIT

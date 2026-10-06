<!-- Generated: 2026-10-06 | Files scanned: 20 | Token estimate: ~700 -->

# Architecture — rednote-crawler

## System Type
Python CLI + MCP server — rednote (https://www.rednote.com) data crawler that works inside the user's own running Chrome

## Browser Connection

```
Everyday Chrome (already open, logged in to rednote)
  one-time setup: chrome://inspect/#remote-debugging
                  → "Allow remote debugging for this browser instance"
        ↓ writes <user data dir>/DevToolsActivePort
src/chrome.py   devtools_ws_url()          (dir override: REDNOTE_CHROME_USER_DATA_DIR)
        ↓ ws://127.0.0.1:<port><path>
src/browser.py  BrowserManager             (Playwright connect_over_cdp, default context)
        ↓ Chrome shows an "Allow" prompt per connection
new tabs in the user's Chrome; on exit only those tabs are closed, Chrome stays open
```

The crawler never launches a browser and stores no login state.

## Entry Points

```
rednote.py (CLI)  ── start ──→ spawns mcp_server.py --transport streamable-http
      │                        on 127.0.0.1:8765 as a background daemon
      │                        (attaches once, stays attached → one "Allow" prompt)
      └─ status / search / note / crawl / saved ──→ MCP tool calls over HTTP
         stop ──→ SIGTERM to the daemon

mcp_server.py     FastMCP tools → CrawlerSession (src/session.py)
                  stdio: attached for the client's lifetime
                  sse / streamable-http: attached for the process lifetime

main.py           config-driven pipeline; attaches directly (one prompt per run)
scripts/verify_*  live checks; attach directly (one prompt per run)
```

## Pipeline Flow

```
config/settings.yaml
        ↓
BrowserManager (tabs in the user's Chrome)
        ↓
ensure_logged_in()            # user/me "guest" field; manual login if needed
        ↓
For each keyword:
  search_notes() → [summaries]
        ↓
  fetch_note_details() → [details]
        ├── parse_note_detail()
        └── fetch_comments() → [comments]
        ↓
  Storage.save_all()
        ├── raw/*.json
        └── processed/*.xlsx (3 sheets)
```

## Module Dependency Graph

```
rednote.py        → mcp client → mcp_server.py (daemon, over HTTP)
mcp_server.py     ← src/session.py, src/errors.py
main.py           ← src/auth.py, src/browser.py, src/search.py, src/note.py, src/storage.py

src/session.py    ← src/auth.py, src/browser.py, src/search.py, src/note.py,
                    src/storage.py, src/errors.py
src/auth.py       ← src/browser.py, src/site.py
src/browser.py    ← src/chrome.py
src/search.py     ← src/browser.py, src/parser.py, src/site.py
src/note.py       ← src/browser.py, src/parser.py, src/comment.py
src/comment.py    ← src/parser.py
src/parser.py     ← src/site.py
src/chrome.py     (leaf — DevToolsActivePort lookup)
src/site.py       (leaf — BASE_URL, default https://www.rednote.com,
                   overridable via REDNOTE_BASE_URL)
src/storage.py    (leaf)
src/errors.py     (leaf)
```

## Key Directories

```
src/            11 modules, 2475 lines — core crawler logic
scripts/        6 scripts, 906 lines   — live verification scripts
tests/          16 test files, 4651 lines — pytest unit tests
config/         settings.yaml          — runtime configuration
data/raw/       *.json                 — raw collection output
data/processed/ *.xlsx                 — formatted Excel output
logs/           daemon.pid, daemon.log, mcp_server.log
```

## Total Codebase: ~4,250 lines Python (plus ~4,650 lines of tests)

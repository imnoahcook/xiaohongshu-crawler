<!-- Generated: 2026-10-06 | Files scanned: 20 | Token estimate: ~1200 -->

# Backend (Module Pipeline) — rednote-crawler

## Entry Points

```
rednote.py    → MCP client → daemon (mcp_server.py over streamable HTTP, 127.0.0.1:8765)
mcp_server.py → FastMCP tools → CrawlerSession
main.py       → load_config() → BrowserManager → ensure_logged_in → crawl_keyword() loop
```

### rednote.py (197 lines) — CLI client + daemon launcher
```python
start() → int      # spawn mcp_server.py --transport streamable-http, wait for attach
stop() → int       # SIGTERM the daemon, remove the pid file
_call(tool, arguments) → dict   # one MCP tool call over streamable HTTP
main() → int       # argparse dispatch
```
Commands → tools: `status` → check_login_status, `search <kw> -n N` → search_notes, `note <url> [-c N]` → get_note_detail, `crawl <kw> [-n N] [-c N]` → crawl_keyword, `saved [kw]` → get_saved_data
Constants: `HOST = "127.0.0.1"`, `PORT` (env `REDNOTE_DAEMON_PORT`, default 8765), `PID_FILE = logs/daemon.pid`, `LOG_FILE = logs/daemon.log`
`start` makes exactly one tool call so the daemon attaches to Chrome once (one "Allow" prompt).

### mcp_server.py (467 lines) — MCP server
```python
check_login_status() → dict
search_notes(keyword, max_count=20) → dict
get_note_detail(note_url, max_comments=20) → dict
crawl_keyword(keyword, max_notes=10, max_comments=20) → dict
get_saved_data(keyword="") → dict
parse_args(argv=None) → Namespace   # --transport stdio|sse|streamable-http, --host, --port
main() → None
```
Lifespan: starts the global `CrawlerSession`. On stdio it stops the session at shutdown; on the HTTP transports (`_stay_attached = True`) the session stays attached to Chrome until the process exits, because the lifespan runs per client connection there.
Constants: `TOOL_TIMEOUTS` (search 120s, note 90s, crawl 600s); logs to stderr + `logs/mcp_server.log`

### main.py (203 lines) — Config-driven pipeline
```python
load_config(path="config/settings.yaml") → dict
crawl_keyword(bm, keyword, crawler_cfg, delay_cfg, storage) → None
main() → None  # asyncio entry
```
Attaches to Chrome directly (one "Allow" prompt per run).

## Core Modules

### src/site.py (20 lines) — Target site configuration
```python
BASE_URL     # os.environ["REDNOTE_BASE_URL"], default "https://www.rednote.com"
HOME_URL     # BASE_URL
EXPLORE_URL  # f"{BASE_URL}/explore"
SEARCH_URL   # BASE_URL + "/search_result?keyword={keyword}&type=51"
```
Override example: `REDNOTE_BASE_URL=https://www.xiaohongshu.com` (serves the same web app)

### src/chrome.py (60 lines) — Everyday Chrome discovery
```python
class ChromeNotAvailableError(RuntimeError)
user_data_dir() → Path                     # env REDNOTE_CHROME_USER_DATA_DIR, else OS default
devtools_ws_url() → str                    # reads <user data dir>/DevToolsActivePort
```
Requires "Allow remote debugging for this browser instance" at `chrome://inspect/#remote-debugging`.

### src/browser.py (86 lines) — Chrome connection
```python
class BrowserManager:
    __init__()                              # no arguments
    __aenter__() → BrowserManager           # connect_over_cdp + default context
    __aexit__(*_args)                        # close own tabs only; Chrome stays open
    new_page() → Page                       # new tab in the user's Chrome
    context → BrowserContext | None
```
Constants: `_CONNECT_TIMEOUT_MS = 60_000` (time to click Chrome's "Allow" prompt)
Raises `ChromeNotAvailableError` when Chrome is not reachable.

### src/auth.py (141 lines) — Login management
```python
is_logged_in(page) → bool                  # loads home, reads user/me "guest" field
wait_for_manual_login(page) → bool          # 300s timeout
ensure_logged_in(bm) → bool                # already logged in, or wait for manual login
_watch_login_state(page) → dict             # response listener; {"logged_in": None|True|False}
```
Constants: `REDNOTE_HOME`, `REDNOTE_LOGIN` (from `src/site.py`), `_USER_ME_PATH = "/api/sns/web/v2/user/me"`, `LOGIN_WAIT_TIMEOUT = 300`, `_USER_ME_WAIT_SECONDS = 15`
Login lives in Chrome; nothing is persisted. Manual login: QR-code scan with the rednote app, or phone number + SMS code

### src/session.py (491 lines) — Long-lived session behind the MCP tools
```python
class CrawlerSession:
    __init__()                              # no arguments
    start() / stop()                        # idempotent start, serialized by _start_lock
    is_running() → bool
    browser_lock() → BrowserManager | None  # async context manager; serializes browser use
    check_login_status() → dict
    search_notes(keyword, max_count=20) → dict
    get_note_detail(note_url, max_comments=20) → dict
    crawl_keyword(keyword, ...) → dict      # max_notes capped at _MAX_NOTES_LIMIT = 20
    get_saved_data(...) → dict
```
Recovers once from a lost browser connection; reports login expiry via `src/errors.py`.

### src/errors.py (128 lines) — Structured tool errors
```python
class CrawlerError
browser_not_running_error() / browser_crashed_error() / login_expired_error()
timeout_error(tool_name, timeout_seconds) / invalid_input_error(field, reason)
crawl_failed_error(detail)
```

### src/search.py (202 lines) — Search collection
```python
search_notes(bm, keyword, max_count=20, ...) → list[dict]
_detect_card_selector(page) → str | None
_scroll_to_load(page, card_selector, target_count, ...) → None
```
Flow: `navigate → detect cards → scroll → parse each card`

### src/note.py (268 lines) — Note detail collection
```python
fetch_single_note(...) → dict | None       # one note by URL (used by CrawlerSession)
fetch_note_details(bm, search_results, max_comments=20, ...) → list[dict]
_fetch_single_note(bm, note_id, note_url, ...) → dict | None
_wait_for_content(page) → None
```
Flow: `for each note → goto URL → wait render → parse detail → fetch comments`
Retry: up to `_MAX_RETRIES = 2`
Accepted note URLs: `/explore/{id}`, `/discovery/item/{id}`, `/search_result/{id}`

### src/comment.py (185 lines) — Comment collection
```python
fetch_comments(page, note_id, max_count=20, ...) → list[dict]
_detect_comment_selector(page) → str | None
_scroll_comments(page, item_selector, target_count, ...) → None
```
Flow: `detect selector → scroll container → parse each comment`

### src/parser.py (596 lines) — DOM extraction (largest module)
```python
normalize_count(text: str) → int             # "1.2万" → 12000
parse_search_card(card) → dict | None        # 9 fields
parse_note_detail(page, note_id) → dict | None  # 14 fields
parse_comment(comment_el, note_id) → dict | None  # 8 fields
_query_text(page, selectors) → str
_parse_interact_count(page, selectors) → int
```
Pattern: Multi-selector fallback — tries selectors in priority order

### src/storage.py (298 lines) — Data persistence
```python
class Storage:
    __init__(config: dict)
    save_all(keyword, search_results, note_details) → None
```
Output: JSON (raw/) + Excel 3-sheet workbook (processed/) — sheets "Search Results", "Note Details", "Comments"

## Pipeline Chain

```
search_notes(bm, kw)
    → parse_search_card(card)         [per card]
    → list[dict] (9 fields)

fetch_note_details(bm, results)
    → _fetch_single_note(bm, id, url)
        → parse_note_detail(page, id)  [14 fields]
        → fetch_comments(page, id)
            → parse_comment(el, id)    [8 fields per comment]
    → list[dict]

Storage.save_all(kw, search, details)
    → JSON files + XLSX workbook
```

## Verification Scripts

```
scripts/verify_guest_feed.py (52 lines)  — home feed smoke test (works logged out)
scripts/verify_login.py      (54 lines)  — login state test
scripts/verify_search.py     (134 lines) — search pipeline test
scripts/verify_note.py       (171 lines) — detail+comment test
scripts/verify_e2e.py        (271 lines) — full integration test
scripts/verify_mcp_tools.py  (224 lines) — MCP tools test
```
All attach directly to the user's Chrome (one "Allow" prompt per run).

<!-- Generated: 2026-10-06 | Files scanned: 2 | Token estimate: ~400 -->

# Dependencies — rednote-crawler

## Python Runtime
- **Python** 3.10+ (required)
- **Package manager:** uv (not pip)

## Direct Dependencies (pyproject.toml)

| Package | Version | Purpose | Used in |
|---------|---------|---------|---------|
| playwright | ≥1.58.0 | Browser automation (async API), CDP attach | browser.py, auth.py, search.py, note.py, comment.py |
| mcp[cli] | ≥1.26.0 | MCP server (FastMCP) and streamable HTTP client | mcp_server.py, rednote.py |
| starlette | ≥0.52.1 | HTTP transports of the MCP server | mcp_server.py (via mcp) |
| uvicorn | ≥0.41.0 | ASGI server for the HTTP transports | mcp_server.py (via mcp) |
| pyyaml | ≥6.0.3 | YAML config loading | main.py |
| openpyxl | ≥3.1.5 | Excel workbook generation | storage.py |

Dev group: pytest ≥9.0.2, pytest-asyncio ≥1.3.0, pytest-cov ≥7.0.0

## System Requirements
- Google Chrome, already running, with "Allow remote debugging for this browser instance" enabled at `chrome://inspect/#remote-debugging`. The crawler attaches to it over CDP; no Playwright browser download is needed.

## Standard Library Usage

| Module | Used in | Purpose |
|--------|---------|---------|
| asyncio | main.py, mcp_server.py, rednote.py, session.py, auth.py | Event loop, locks |
| logging | all modules | Structured logging |
| pathlib | chrome.py, storage.py, session.py, main.py, rednote.py | Path management |
| json | storage.py, rednote.py | JSON serialization |
| subprocess, signal, socket | rednote.py | Daemon start / stop / port probe |
| argparse | rednote.py, mcp_server.py | CLI parsing |
| re | parser.py | Regex extraction |
| random | main.py, search.py, note.py, comment.py | Human-like delays |
| datetime | storage.py | Timestamps |
| urllib.parse | search.py | URL encoding |
| os | site.py, chrome.py, rednote.py | Env overrides (below) |

## Environment Variables

| Variable | Read in | Purpose |
|----------|---------|---------|
| `REDNOTE_BASE_URL` | site.py | Target origin (default `https://www.rednote.com`) |
| `REDNOTE_CHROME_USER_DATA_DIR` | chrome.py | Chrome user data dir, if not the OS default |
| `REDNOTE_DAEMON_PORT` | rednote.py | Daemon port (default 8765) |

## External Services

| Service | URL | Purpose |
|---------|-----|---------|
| rednote | https://www.rednote.com | Target crawl site (override with `REDNOTE_BASE_URL`) |
| Local Chrome DevTools | ws://127.0.0.1:<port> (from `DevToolsActivePort`) | CDP connection to the user's Chrome |

## No Database / No Message Queue
Output is file-based only. The only server is the local MCP daemon (`rednote.py start` → `mcp_server.py` on 127.0.0.1:8765).

"""
rednote command line client

Chrome asks you to allow every new remote debugging connection. To avoid that
prompt on each run, this CLI keeps one crawler daemon running in the background.
The daemon (the MCP server over HTTP) attaches to your Chrome once and stays
attached; every command below is sent to it.

Usage:
    uv run python rednote.py start                    # attach to Chrome once (click "Allow")
    uv run python rednote.py status                   # is the daemon up and logged in?
    uv run python rednote.py search coffee -n 10      # search notes
    uv run python rednote.py note "<note url>"        # one note's details + comments
    uv run python rednote.py crawl coffee -n 5        # search → details → comments → save
    uv run python rednote.py saved [keyword]          # list saved data files
    uv run python rednote.py stop                     # detach and stop the daemon
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = int(os.environ.get("REDNOTE_DAEMON_PORT", "8765"))
URL = f"http://{HOST}:{PORT}/mcp"
PID_FILE = ROOT / "logs" / "daemon.pid"
LOG_FILE = ROOT / "logs" / "daemon.log"

# Starting the daemon waits for you to click "Allow" in Chrome (seconds)
_START_TIMEOUT = 90
# crawl_keyword can legitimately run for many minutes (seconds)
_CALL_TIMEOUT = 20 * 60


async def _call(tool: str, arguments: dict) -> dict:
    """Call one tool on the daemon and return its result."""
    async with streamablehttp_client(URL, sse_read_timeout=_CALL_TIMEOUT) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            if result.structuredContent is not None:
                return result.structuredContent
            return json.loads(result.content[0].text)


def _daemon_pid() -> int | None:
    """Return the daemon's pid if it is alive, otherwise None."""
    try:
        pid = int(PID_FILE.read_text())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def _port_open() -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


async def _wait_until_ready(process: subprocess.Popen) -> bool:
    """Wait until the daemon is listening, then make it attach to Chrome.

    The daemon attaches on its first client connection, so exactly one call is
    made here: retrying would open more connections to Chrome and more prompts.
    """
    deadline = time.monotonic() + _START_TIMEOUT
    while not _port_open():
        if process.poll() is not None or time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.25)
    try:
        await asyncio.wait_for(_call("get_saved_data", {}), timeout=_START_TIMEOUT)
        return True
    except Exception:
        return False


def start() -> int:
    if _daemon_pid() is not None:
        print(f"Daemon already running (pid {_daemon_pid()})")
        return 0

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("ab") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "mcp_server.py"),
                "--transport",
                "streamable-http",
                "--host",
                HOST,
                "--port",
                str(PORT),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    PID_FILE.write_text(str(process.pid))
    print('Starting daemon; click "Allow" on the remote debugging prompt in Chrome...')

    if asyncio.run(_wait_until_ready(process)):
        print(f"Daemon attached to Chrome (pid {process.pid}, log: {LOG_FILE})")
        return 0

    print(f"Daemon failed to start; see {LOG_FILE}")
    if process.poll() is None:
        process.terminate()
    PID_FILE.unlink(missing_ok=True)
    return 1


def stop() -> int:
    pid = _daemon_pid()
    if pid is None:
        print("Daemon is not running")
    else:
        os.kill(pid, signal.SIGTERM)
        print(f"Daemon stopped (pid {pid})")
    PID_FILE.unlink(missing_ok=True)
    return 0


# CLI command → daemon tool
_TOOLS = {
    "status": "check_login_status",
    "search": "search_notes",
    "note": "get_note_detail",
    "crawl": "crawl_keyword",
    "saved": "get_saved_data",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="rednote crawler client")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("start", help="start the background daemon and attach to Chrome")
    commands.add_parser("stop", help="stop the background daemon")
    commands.add_parser("status", help="check the daemon and the rednote login")

    search = commands.add_parser("search", help="search notes by keyword")
    search.add_argument("keyword")
    search.add_argument("-n", "--max-count", type=int, default=20)

    note = commands.add_parser("note", help="collect one note's details and comments")
    note.add_argument("note_url")
    note.add_argument("-c", "--max-comments", type=int, default=20)

    crawl = commands.add_parser("crawl", help="search, collect details and comments, save")
    crawl.add_argument("keyword")
    crawl.add_argument("-n", "--max-notes", type=int, default=10)
    crawl.add_argument("-c", "--max-comments", type=int, default=20)

    saved = commands.add_parser("saved", help="list saved data files")
    saved.add_argument("keyword", nargs="?", default="")

    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.command == "start":
        return start()
    if args.command == "stop":
        return stop()

    if _daemon_pid() is None:
        print("Daemon is not running. Start it with: uv run python rednote.py start")
        return 1

    # The remaining arguments are named after the tool's parameters
    arguments = {key: value for key, value in vars(args).items() if key != "command"}
    result = asyncio.run(_call(_TOOLS[args.command], arguments))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())

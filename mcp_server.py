"""
rednote crawler MCP server entry point

Exposes the crawler as tools that AI assistants can call over MCP. Supports:
  - Any MCP client, such as Claude Desktop / Code / Cursor

Tools:
  - check_login_status: check the login status
  - search_notes: search notes by keyword
  - get_note_detail: fetch note details + comments
  - crawl_keyword: full crawl pipeline
  - get_saved_data: list locally saved data

Transport modes (Phase E):
  - stdio (default): local integration, called directly by Claude Desktop / Code
  - sse: SSE transport, supports remote deployment
  - streamable-http: Streamable HTTP transport, the latest MCP standard

Usage:
  # stdio mode (default, for Claude Desktop / Code)
  uv run python mcp_server.py

  # SSE mode (remote deployment)
  uv run python mcp_server.py --transport sse --host 0.0.0.0 --port 8000

  # Streamable HTTP mode
  uv run python mcp_server.py --transport streamable-http --host 0.0.0.0 --port 8000

  # Local development and debugging (MCP Inspector)
  mcp dev mcp_server.py

Configuring Claude Desktop / Code:
  See claude_mcp_config.example.json

Notes:
  In MCP stdio mode stdout is reserved for the protocol, so logs must go to stderr.
  The server works in the Chrome you already have open; log in to rednote.com there first.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import AsyncGenerator

from mcp.server.fastmcp import FastMCP

from src.errors import invalid_input_error, timeout_error
from src.session import CrawlerSession

# In MCP stdio mode stdout is reserved for the protocol, so logs go to stderr
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)


# ============================================================
# Phase D: tool timeouts (seconds)
# ============================================================

TOOL_TIMEOUTS: dict[str, int] = {
    "search_notes": 120,
    "get_note_detail": 90,
    "crawl_keyword": 600,
}


# ============================================================
# Phase D: log file output
# ============================================================

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DIR_DEFAULT = Path("logs")


def setup_file_logging(
    log_dir: Path = _LOG_DIR_DEFAULT,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
) -> None:
    """Configure log file output (RotatingFileHandler).

    In MCP stdio mode stdout is reserved for the protocol, so key logs are also written to a file for troubleshooting.

    Args:
        log_dir: log directory (default logs/)
        max_bytes: maximum size of a single log file (default 5MB)
        backup_count: number of rotated log files to keep (default 3)
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "mcp_server.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

    root_logger = logging.getLogger()
    # Ensure the root logger records at least INFO (basicConfig may not take effect in the MCP process)
    if root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    logger.info("Log file output enabled: %s", log_dir / "mcp_server.log")


# ---- Global session singleton (lives for the lifetime of the MCP process) ----
_session = CrawlerSession()

# Over the HTTP transports this lifespan runs once per client connection, not once
# per process. Detaching after each client would make Chrome ask to allow remote
# debugging again on the next one, so there the session stays attached until the
# process exits. main() sets this for the HTTP transports.
_stay_attached = False


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncGenerator[None, None]:
    """MCP server startup/shutdown hook: manages the browser lifecycle.

    Initializes the browser and enables file logging on startup; releases resources on shutdown.
    """
    # Phase D: configure file logging on startup
    setup_file_logging()

    logger.info("rednote-crawler MCP server starting...")
    await _session.start()
    logger.info("rednote-crawler MCP server ready (browser started)")
    try:
        yield
    finally:
        if not _stay_attached:
            logger.info("rednote-crawler MCP server shutting down...")
            await _session.stop()
            logger.info("rednote-crawler MCP server stopped")


# ---- Create the MCP server instance ----
mcp = FastMCP("rednote-crawler", lifespan=lifespan)


# ============================================================
# Phase D: timeout wrapper
# ============================================================


async def _with_timeout(coro, tool_name: str) -> dict:
    """Apply a timeout to an async operation.

    Args:
        coro: the coroutine to run
        tool_name: tool name (used for the error message and the timeout lookup)

    Returns:
        The normal result, or a timeout error dict
    """
    timeout_seconds = TOOL_TIMEOUTS.get(tool_name, 120)
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.error("%s timed out (%d seconds)", tool_name, timeout_seconds)
        return timeout_error(tool_name=tool_name, timeout_seconds=timeout_seconds).to_dict()


# ============================================================
# Phase A tools
# ============================================================


@mcp.tool()
async def check_login_status() -> dict:
    """Check the rednote login status.

    Returns whether the browser is running and whether it is logged in.
    If not logged in, log in to rednote.com in Chrome (QR code or phone number) and retry.

    Expected duration: 5-10 seconds (visits the rednote home page)

    Returns:
        logged_in (bool): whether rednote is logged in
        browser_running (bool): whether the browser is running
        message (str): status description and suggested action
    """
    logger.info("Tool call: check_login_status")
    result = await _session.check_login_status()
    logger.info("Login status: %s", result)
    return result


# ============================================================
# Phase B tools
# ============================================================


@mcp.tool()
async def search_notes(keyword: str, max_count: int = 20) -> dict:
    """Search rednote notes by keyword and return a list of summaries.

    Args:
        keyword: search keyword (required, must not be empty)
        max_count: maximum number of notes to return (optional, default 20, range 1-50)

    Returns:
        keyword (str): the search keyword
        count (int): number of results actually returned
        results (list): note summaries, each containing
            note_id / title / author / likes / note_url and other fields

    Expected duration: 30-90 seconds (page load + scrolling). Timeout: 120 seconds.
    """
    # Input validation: keyword must not be empty
    stripped_keyword = keyword.strip()
    if not stripped_keyword:
        return invalid_input_error(field="keyword", reason="must not be empty").to_dict()

    # Clamp: max_count is limited to 1-50
    clamped_max_count = max(1, min(max_count, 50))

    logger.info("Tool call: search_notes (keyword=%s, max_count=%d)", stripped_keyword, clamped_max_count)

    # Phase D: timeout
    result = await _with_timeout(
        _session.search_notes(keyword=stripped_keyword, max_count=clamped_max_count),
        tool_name="search_notes",
    )
    logger.info("search_notes done: count=%s", result.get("count", result.get("code", 0)))
    return result


@mcp.tool()
async def get_note_detail(note_url: str, max_comments: int = 20) -> dict:
    """Fetch the details and comments of a single rednote note.

    Args:
        note_url: note detail page URL (required), in the form:
            https://www.rednote.com/explore/{note_id}?xsec_token=...
        max_comments: maximum number of comments to fetch (optional, default 20, range 0-50)

    Returns:
        On success, a note detail dict containing:
            note_id / title / content / author / likes / collects /
            tags / images / comments and other fields
        On failure, returns {"error": True, "code": str, "message": str, "action": str}

    Expected duration: 15-60 seconds (page load + comment scrolling). Timeout: 90 seconds.
    """
    # Input validation: URL must not be empty
    if not note_url.strip():
        return invalid_input_error(field="note_url", reason="must not be empty").to_dict()

    # Clamp: max_comments is limited to 0-50
    clamped_max_comments = max(0, min(max_comments, 50))

    # Strip query parameters such as xsec_token so sensitive tokens are not written to the logs
    safe_url = note_url.split("?")[0]
    logger.info("Tool call: get_note_detail (url=%s, max_comments=%d)", safe_url, clamped_max_comments)

    # Phase D: timeout
    result = await _with_timeout(
        _session.get_note_detail(note_url=note_url, max_comments=clamped_max_comments),
        tool_name="get_note_detail",
    )

    # Defensive check (the session layer already guarantees a dict; this is a fallback)
    if result is None:
        from src.errors import crawl_failed_error
        return crawl_failed_error(f"Failed to fetch note details: {safe_url}").to_dict()

    logger.info("get_note_detail done: note_id=%s", result.get("note_id", result.get("code", "unknown")))
    return result


# ============================================================
# Phase C tools
# ============================================================

# MCP resource path constants (module-level so tests can patch them)
_CONFIG_PATH = Path("config/settings.yaml")
_DATA_DIR = Path("data")


@mcp.tool()
async def crawl_keyword(keyword: str, max_notes: int = 10, max_comments: int = 20) -> dict:
    """Full crawl pipeline: search a keyword → fetch note details + comments → save to local files.

    Args:
        keyword: search keyword (required, must not be empty)
        max_notes: maximum number of notes to crawl (optional, default 10, range 1-20)
        max_comments: maximum number of comments to fetch per note (optional, default 20, range 0-50)

    Returns:
        keyword / search_count / detail_count / total_comments / summary
        On failure, returns {"error": True, "code": str, "message": str, "action": str}

    Expected duration: 2-15 minutes (depending on the number of notes). Timeout: 600 seconds.
    Consider validating the keyword with search_notes before calling this tool.
    """
    stripped_keyword = keyword.strip()
    if not stripped_keyword:
        return invalid_input_error(field="keyword", reason="must not be empty").to_dict()

    # Clamp
    clamped_max_notes = max(1, min(max_notes, 20))
    clamped_max_comments = max(0, min(max_comments, 50))

    logger.info(
        "Tool call: crawl_keyword (keyword=%s, max_notes=%d, max_comments=%d)",
        stripped_keyword, clamped_max_notes, clamped_max_comments,
    )

    # Phase D: timeout
    result = await _with_timeout(
        _session.crawl_keyword(
            keyword=stripped_keyword,
            max_notes=clamped_max_notes,
            max_comments=clamped_max_comments,
        ),
        tool_name="crawl_keyword",
    )
    logger.info("crawl_keyword done: %s", result.get("summary", result.get("message", "")))
    return result


@mcp.tool()
async def get_saved_data(keyword: str = "") -> dict:
    """List the locally saved crawl data files.

    Args:
        keyword: keyword filter (optional, case-insensitive substring match; omitted or an empty string returns all files)

    Returns:
        files: list of files, each containing path / keyword / created_at / size_bytes

    Expected duration: < 1 second (local filesystem scan)
    """
    filter_keyword = keyword.strip() or None
    logger.info("Tool call: get_saved_data (keyword=%s)", filter_keyword or "(all)")
    result = await _session.get_saved_data(keyword=filter_keyword)
    logger.info("get_saved_data done: %d files", len(result.get("files", [])))
    return result


# ============================================================
# Phase C resource endpoints
# ============================================================


@mcp.resource("rednote://config")
async def get_config_resource() -> str:
    """Read the current settings.yaml configuration (read-only).

    Returns the configuration as YAML text so the AI can see the current crawl settings (keywords, delays, storage, etc.).
    """
    if not _CONFIG_PATH.exists():
        return f"Config file not found: {_CONFIG_PATH}. Make sure config/settings.yaml has been created."
    return _CONFIG_PATH.read_text(encoding="utf-8")


@mcp.resource("rednote://data/{filename}")
async def get_data_resource(filename: str) -> str:
    """Read the contents of a local data file (read-only).

    Looks for the file in the data/raw/ and data/processed/ subdirectories and returns its contents.

    Args:
        filename: data file name (e.g. python_tutorial_20240315_143022.json), without a path

    Returns:
        The file's text content (JSON), or an error message

    Security: only files under data/ can be accessed; path traversal (../) is rejected.
    """
    # Security check: reject path traversal and subdirectory access
    if ".." in filename or "/" in filename or "\\" in filename:
        return f"Invalid file name (path traversal and subdirectory access are not allowed): {filename}"

    # Look in both the raw and processed subdirectories
    for subdir in ("raw", "processed"):
        file_path = _DATA_DIR / subdir / filename
        if file_path.exists() and file_path.is_file():
            return file_path.read_text(encoding="utf-8", errors="replace")

    return (
        f"File not found: {filename}. "
        "Collect data with crawl_keyword or search_notes first, "
        "or use get_saved_data to list the existing files."
    )


# ============================================================
# Phase E: CLI argument parsing + transport selection
# ============================================================

_VALID_TRANSPORTS = ("stdio", "sse", "streamable-http")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments: transport / host / port.

    Args:
        argv: list of command-line arguments (None uses sys.argv[1:]; lets tests pass their own)

    Returns:
        The parsed Namespace, with transport / host / port fields
    """
    parser = argparse.ArgumentParser(
        description="rednote crawler MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--transport",
        choices=_VALID_TRANSPORTS,
        default="stdio",
        help="Transport: stdio (default, local) / sse (remote SSE) / streamable-http (HTTP)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="SSE / HTTP listen address (default 127.0.0.1; use 0.0.0.0 for remote deployment)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="SSE / HTTP listen port (default 8000)",
    )
    return parser.parse_args(argv)


def main() -> None:
    """MCP server entry point: parse arguments and start the selected transport."""
    global _stay_attached
    args = parse_args()

    if args.transport == "stdio":
        # stdio mode: run directly without touching the host/port settings
        logger.info("Starting MCP server in stdio mode")
        mcp.run()
    else:
        # SSE / Streamable HTTP mode: update the listen address, then start
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        _stay_attached = True
        logger.info(
            "Starting MCP server in %s mode (%s:%d)",
            args.transport, args.host, args.port,
        )
        mcp.run(transport=args.transport)


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()

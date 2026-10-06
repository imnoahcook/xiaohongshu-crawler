"""
MCP service-level browser session management module

Responsibilities:
  - Manage the service-level lifecycle of the Playwright browser instance (long-lived process, unlike a one-off async with)
  - Serialize all browser operations through asyncio.Lock to prevent concurrent races
  - Provide a login status check interface for MCP tools to call
  - Browser health check + automatic crash recovery (Phase D)
  - Detection of login expiry during operations (Phase D)
  - Unified structured error format (Phase D)

Differences from BrowserManager:
  - BrowserManager: an async with context manager for a single crawl
  - CrawlerSession: a service object that keeps running for the lifetime of the MCP process,
    with its lifecycle managed manually via start()/stop()

Usage:
    session = CrawlerSession(headless=True)
    await session.start()
    result = await session.check_login_status()
    async with session.browser_lock() as bm:
        page = await bm.new_page()
        # ... crawl operations
    await session.stop()
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

import src.note
import src.search
from src.auth import is_logged_in
from src.browser import BrowserManager
from src.errors import (
    browser_crashed_error,
    browser_not_running_error,
    crawl_failed_error,
    login_expired_error,
)
from src.storage import Storage

logger = logging.getLogger(__name__)

# Default storage config used by the crawl_keyword tool
_DEFAULT_STORAGE_CONFIG: dict = {
    "output_dir": "data",
    "save_raw_json": True,
    "save_xlsx": True,
}

# Upper bound on max_notes for the full crawl flow (keeps a single task from running too long)
_MAX_NOTES_LIMIT = 20


def _extract_keyword_from_stem(stem: str) -> str:
    """Extract the keyword from a file name (without extension).

    File name format: [notes_]{keyword}_{YYYYMMDD}_{HHMMSS}
    For example: python_tutorial_20240315_143022  →  python_tutorial
                 notes_rednote_tips_20240315_143022  →  rednote_tips

    Args:
        stem: File name (without extension)

    Returns:
        The extracted keyword string
    """
    # Strip the notes_ prefix (naming convention for note detail files)
    if stem.startswith("notes_"):
        stem = stem[6:]

    # The timestamp has two parts, {YYYYMMDD}_{HHMMSS}, taking up the last two "_"-separated chunks
    parts = stem.rsplit("_", 2)
    if len(parts) >= 3:
        return parts[0]
    return stem


class CrawlerSession:
    """Service-level browser session for the long-lived MCP server process.

    Design constraints:
      - Only one CrawlerSession instance should be running at a time (the caller is responsible for this)
      - All browser operations must run serially through the browser_lock() context manager
      - Defaults to headless=True in MCP stdio mode to save resources
      - Automatically attempts recovery once when the browser crashes (Phase D)
      - Checks login status when an operation fails and returns a precise error code (Phase D)
    """

    def __init__(self, headless: bool = True) -> None:
        """Initialize the session (does not start the browser).

        Args:
            headless: Whether to run headless. Defaults to True for the MCP server; set to False when debugging.
        """
        self._headless = headless
        self._bm: Optional[BrowserManager] = None
        self._exit_stack: Optional[contextlib.AsyncExitStack] = None
        self._running: bool = False
        self._lock = asyncio.Lock()

    def is_running(self) -> bool:
        """Return whether the browser has started successfully and is running."""
        return self._running

    async def start(self) -> None:
        """Start the browser (idempotent: returns immediately if already running).

        Uses AsyncExitStack to manage the BrowserManager lifecycle:
          - If BrowserManager.__aenter__ raises, the ExitStack automatically cleans up registered resources
          - self._exit_stack / self._bm are assigned only after a successful start, keeping state consistent

        Raises:
            Exception: Propagated as-is when the browser fails to start
        """
        if self._running:
            logger.debug("Browser session already running; skipping duplicate start")
            return

        logger.info("Starting MCP browser session (headless=%s)", self._headless)
        exit_stack = contextlib.AsyncExitStack()
        # enter_async_context calls __aenter__ internally; exit_stack cleans up automatically on failure
        bm = await exit_stack.enter_async_context(BrowserManager(headless=self._headless))
        # Assign only after everything succeeds, so stop() always deals with complete state
        self._exit_stack = exit_stack
        self._bm = bm
        self._running = True
        logger.info("MCP browser session started")

    async def stop(self) -> None:
        """Close the browser and release all resources (idempotent: safe to call when not running)."""
        if self._exit_stack is not None:
            logger.info("Closing MCP browser session")
            await self._exit_stack.aclose()  # Calls the registered __aexit__(None, None, None)
            self._exit_stack = None
            self._bm = None
        self._running = False
        logger.info("MCP browser session closed")

    # ============================================================
    # Phase D: health check and automatic recovery
    # ============================================================

    async def _is_browser_healthy(self) -> bool:
        """Check whether the browser is still alive and usable.

        Uses Playwright's context.browser.is_connected() to tell whether the browser process is healthy.

        Returns:
            True if the browser is healthy and usable, False if it is not
        """
        if self._bm is None:
            return False
        try:
            ctx = self._bm.context
            if ctx is None:
                return False
            return ctx.browser.is_connected()
        except Exception:
            return False

    async def _ensure_browser(self) -> Optional[BrowserManager]:
        """Ensure the browser is usable, attempting automatic recovery after a crash.

        Checks browser health and, if unhealthy, runs the stop → start recovery flow once.

        Returns:
            The BrowserManager instance (when usable), or None (recovery failed)
        """
        if not self._running:
            return None

        if await self._is_browser_healthy():
            return self._bm

        # Browser is unhealthy; attempt recovery
        logger.warning("Browser health check failed; attempting automatic recovery...")
        await self.stop()
        try:
            await self.start()
            logger.info("Browser automatic recovery succeeded")
            return self._bm
        except Exception as e:
            logger.error("Browser automatic recovery failed: %s", e)
            return None

    # ============================================================
    # Phase D: login expiry detection
    # ============================================================

    async def _check_login_in_lock(self) -> bool:
        """Check login status while already holding the lock (internal method).

        Creates a temporary page to run the login check and makes sure the page is closed afterwards.

        Returns:
            True if logged in, False if not logged in or the check failed
        """
        if self._bm is None:
            return False
        try:
            page = await self._bm.new_page()
            try:
                return await is_logged_in(page)
            finally:
                await page.close()
        except Exception as e:
            logger.warning("Login check inside lock raised an exception: %s", e)
            return False

    @asynccontextmanager
    async def browser_lock(self) -> AsyncGenerator[Optional[BrowserManager], None]:
        """Acquire the exclusive browser lock so operations run serially.

        Usage:
            async with session.browser_lock() as bm:
                page = await bm.new_page()
                # ... exclusive operations

        Yields:
            The BrowserManager instance (when started), or None (when not started)
        """
        async with self._lock:
            yield self._bm

    async def search_notes(self, keyword: str, max_count: int = 20) -> dict:
        """Search notes by keyword and return a list of summaries (MCP tool entry point).

        Phase D enhancements:
          - Returns a structured error (with code/action) when the browser is not running or has crashed
          - Checks login status on empty search results to tell LOGIN_EXPIRED apart from a genuine empty result

        Args:
            keyword: Search keyword (the caller is responsible for ensuring it is non-empty)
            max_count: Maximum number of results to return (default 20)

        Returns:
            Success: { keyword, count, results }
            Error: { error, code, message, action }
        """
        # Fast path: return early when the browser is definitely not running
        if not self._running:
            return browser_not_running_error().to_dict()

        async with self._lock:
            # Health check + automatic recovery (done before releasing the lock; other requests queue during recovery)
            bm = await self._ensure_browser()
            if bm is None:
                return browser_crashed_error().to_dict()

            # Second guard: _ensure_browser may change _bm during recovery
            if self._bm is None:
                return browser_crashed_error().to_dict()

            results = await src.search.search_notes(
                self._bm, keyword=keyword, max_count=max_count
            )

            # Check login status on empty results (tells "really found nothing" apart from "login expired")
            if not results:
                logged_in = await self._check_login_in_lock()
                if not logged_in:
                    return login_expired_error().to_dict()

        return {
            "keyword": keyword,
            "count": len(results),
            "results": results,
        }

    async def get_note_detail(self, note_url: str, max_comments: int = 20) -> dict:
        """Crawl a single note's details + comments (MCP tool entry point).

        Phase D enhancements:
          - Returns a structured error when the browser is not running or has crashed
          - Checks login status when the crawl fails to tell LOGIN_EXPIRED apart from CRAWL_FAILED

        Args:
            note_url: Full URL of the note detail page
            max_comments: Maximum number of comments to crawl (default 20)

        Returns:
            Success: the note detail dict (including the comments field)
            Error: { error, code, message, action }
        """
        # Fast path: return early when the browser is definitely not running
        if not self._running:
            return browser_not_running_error().to_dict()

        async with self._lock:
            bm = await self._ensure_browser()
            if bm is None:
                return browser_crashed_error().to_dict()

            if self._bm is None:
                return browser_crashed_error().to_dict()

            result = await src.note.fetch_single_note(
                self._bm, note_url=note_url, max_comments=max_comments
            )

            # Check login status when the crawl fails
            if result is None:
                logged_in = await self._check_login_in_lock()
                if not logged_in:
                    return login_expired_error().to_dict()
                return crawl_failed_error("URL is invalid or the page could not be loaded").to_dict()

        return result

    async def check_login_status(self) -> dict:
        """Check the current rednote login status.

        Phase D enhancements:
          - Returns a structured error including the code field when not running

        Returns:
            {
                "logged_in": bool,
                "browser_running": bool,
                "message": str,
                "code": str (errors only)
            }
        """
        if not self._running:
            err = browser_not_running_error()
            return {
                "logged_in": False,
                "browser_running": False,
                "message": err.message,
                "code": err.code,
            }

        async with self._lock:
            if self._bm is None:
                err = browser_not_running_error()
                return {
                    "logged_in": False,
                    "browser_running": False,
                    "message": err.message,
                    "code": err.code,
                }
            page = await self._bm.new_page()
            try:
                logged_in = await is_logged_in(page)
                if logged_in:
                    message = "Logged in; crawling features are available."
                else:
                    message = (
                        "Not logged in. Run "
                        "`uv run python scripts/verify_login.py` in a terminal to log in, "
                        "then restart the MCP server."
                    )
                return {
                    "logged_in": logged_in,
                    "browser_running": True,
                    "message": message,
                }
            finally:
                await page.close()

    async def crawl_keyword(
        self,
        keyword: str,
        max_notes: int = 10,
        max_comments: int = 20,
    ) -> dict:
        """Run the full crawl flow: search → details → comments → storage (MCP tool entry point).

        Phase D enhancements:
          - Returns a structured error when the browser is not running or has crashed

        Args:
            keyword: Search keyword (the caller is responsible for ensuring it is non-empty)
            max_notes: Maximum number of notes to crawl (default 10, automatically capped at 20)
            max_comments: Maximum number of comments to crawl per note (default 20)

        Returns:
            Success: { keyword, search_count, detail_count, total_comments, summary }
            Error: { error, code, message, action }
        """
        # Fast path: return early when the browser is definitely not running
        if not self._running:
            return browser_not_running_error().to_dict()

        # Cap max_notes at the limit to keep a single task from running too long
        clamped_max_notes = min(max_notes, _MAX_NOTES_LIMIT)

        async with self._lock:
            bm = await self._ensure_browser()
            if bm is None:
                return browser_crashed_error().to_dict()

            if self._bm is None:
                return browser_crashed_error().to_dict()

            # Step 1: search
            search_results = await src.search.search_notes(
                self._bm, keyword=keyword, max_count=clamped_max_notes
            )

            # Step 2: batch-crawl details + comments (skipped when there are no results)
            if search_results:
                note_details = await src.note.fetch_note_details(
                    self._bm, search_results=search_results, max_comments=max_comments
                )
            else:
                note_details = []

            # Step 3: persist (JSON + Excel)
            storage = Storage(_DEFAULT_STORAGE_CONFIG)
            storage.save_all(keyword, search_results, note_details)

        total_comments = sum(len(note.get("comments", [])) for note in note_details)
        summary = (
            f"Keyword [{keyword}] crawl complete: "
            f"{len(search_results)} search results, "
            f"{len(note_details)} note details, "
            f"{total_comments} comments"
        )
        logger.info(summary)
        return {
            "keyword": keyword,
            "search_count": len(search_results),
            "detail_count": len(note_details),
            "total_comments": total_comments,
            "summary": summary,
        }

    async def get_saved_data(
        self,
        keyword: Optional[str] = None,
        data_dir: Path = Path("data"),
    ) -> dict:
        """Query locally saved crawl data files (does not depend on the browser).

        Scans the data/raw/ and data/processed/ directories and returns a list of file metadata.
        The keyword argument applies a fuzzy filter (case-insensitive).

        Args:
            keyword: Keyword filter (optional; empty / None returns all files)
            data_dir: Data root directory (default "data"; tests pass tmp_path)

        Returns:
            {
                "files": [
                    {
                        "path": str,
                        "keyword": str,
                        "created_at": str,
                        "size_bytes": int
                    },
                    ...
                ]
            }
        """
        files: list[dict] = []
        # Only the raw and processed subdirectories are recognized
        for subdir in ("raw", "processed"):
            dir_path = data_dir / subdir
            if not dir_path.exists():
                continue

            for file_path in sorted(dir_path.iterdir()):
                if not file_path.is_file():
                    continue

                # Only handle JSON and xlsx files
                if file_path.suffix not in (".json", ".xlsx"):
                    continue

                extracted_keyword = _extract_keyword_from_stem(file_path.stem)

                # keyword filter: case-insensitive fuzzy match
                if keyword and keyword.lower() not in extracted_keyword.lower():
                    continue

                stat = file_path.stat()
                files.append({
                    "path": str(file_path),
                    "keyword": extracted_keyword,
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(timespec="seconds"),
                    "size_bytes": stat.st_size,
                })

        return {"files": files}

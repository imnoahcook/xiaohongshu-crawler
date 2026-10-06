"""
Note detail collection module

Responsibilities:
  - Take the list of note URLs from the search results
  - Open each note detail page and wait for the core content to load
  - Call the parser to extract the detail fields
  - Call the comment module to collect comments
  - Pace the crawl (random delays)

Collection flow:
  1. Iterate over the list of note URLs
  2. Open the note detail page and wait for the key elements to load
  3. Call parse_note_detail() to parse the page
  4. Call fetch_comments() to collect comments
  5. Move on to the next note after a random delay
  6. On error, skip the current note and log it

Usage:
    async with BrowserManager() as bm:
        results = await fetch_note_details(bm, search_results, max_comments=20)
"""

from __future__ import annotations

import asyncio
import logging
import random
import re

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.browser import BrowserManager
from src.comment import fetch_comments
from src.parser import parse_note_detail

logger = logging.getLogger(__name__)

# Core content selectors for the note detail page (the page counts as loaded once any one appears)
# Real DOM: after navigating to /explore/{id}?xsec_token=..., the detail renders inside #noteContainer
_NOTE_READY_SELECTORS = [
    "#noteContainer",
    "#detail-title",
    ".note-content",
    ".note-container",
]

# Page load timeout (milliseconds)
_PAGE_LOAD_TIMEOUT_MS = 30_000

# Extra time to wait for the detail content to render (seconds)
_RENDER_WAIT = 2.0

# Maximum retries per note
_MAX_RETRIES = 2


# Regex extracting note_id from a rednote note URL, format: /explore/{note_id}
_NOTE_ID_PATTERN = re.compile(
    r"/(?:explore|discovery/item|search_result)/([a-zA-Z0-9]+)"
)


def _extract_note_id_from_url(note_url: str) -> str | None:
    """Extract the note_id from a note detail page URL.

    Supported format: https://www.rednote.com/explore/{note_id}?xsec_token=...

    Args:
        note_url: Full URL of the note detail page

    Returns:
        The note_id string, or None (URL format does not match)
    """
    match = _NOTE_ID_PATTERN.search(note_url)
    return match.group(1) if match else None


async def fetch_single_note(
    bm: BrowserManager,
    note_url: str,
    max_comments: int = 20,
    scroll_pause: float = 1.5,
    scroll_interval: tuple[float, float] = (1.0, 3.0),
) -> dict | None:
    """Collect a single note's details + comments (public MCP interface).

    Extracts the note_id from note_url automatically, then calls the internal collection logic.
    Meant to be called directly by MCP tools and external modules, with no need to know the note_id in advance.

    Args:
        bm: An initialised, logged-in BrowserManager instance
        note_url: Full URL of the note detail page
        max_comments: Maximum number of comments to collect (default 20)
        scroll_pause: Wait time after scrolling the comment section (seconds)
        scroll_interval: Extra random delay range (min, max) for the comment section (seconds)

    Returns:
        A dict with the note details and comments, or None (invalid URL / collection failed)
    """
    note_id = _extract_note_id_from_url(note_url)
    if not note_id:
        logger.error("Could not extract note_id from URL, please check the URL format: %s", note_url)
        return None

    return await _fetch_single_note(
        bm,
        note_id=note_id,
        note_url=note_url,
        max_comments=max_comments,
        scroll_pause=scroll_pause,
        scroll_interval=scroll_interval,
    )


async def fetch_note_details(
    bm: BrowserManager,
    search_results: list[dict],
    max_comments: int = 20,
    delay_range: tuple[float, float] = (2.0, 5.0),
    scroll_pause: float = 1.5,
    scroll_interval: tuple[float, float] = (1.0, 3.0),
) -> list[dict]:
    """Collect note details and comments in bulk.

    Iterates over the note URLs in the search results, opening each one, parsing its details and collecting its comments.
    A random delay is added between notes to mimic human browsing.

    Args:
        bm: An initialised, logged-in BrowserManager instance
        search_results: List of note summaries returned by search_notes(); each must contain note_id and note_url
        max_comments: Maximum number of comments to collect per note
        delay_range: Random delay range (min, max) between notes (seconds)
        scroll_pause: Fixed wait time when scrolling comments (seconds)
        scroll_interval: Extra random delay range when scrolling comments (seconds)

    Returns:
        List of note detail dicts, each containing the detail fields + a comments sub-list
    """
    total = len(search_results)
    logger.info("Starting bulk note detail collection, %d notes in total", total)

    results: list[dict] = []

    for idx, item in enumerate(search_results):
        note_id = item.get("note_id", "")
        note_url = item.get("note_url", "")

        if not note_id or not note_url:
            logger.warning("Item %d is missing note_id or note_url, skipping", idx + 1)
            continue

        logger.info("[%d/%d] Collecting note details: %s", idx + 1, total, note_url)

        detail = await _fetch_single_note(
            bm,
            note_id=note_id,
            note_url=note_url,
            max_comments=max_comments,
            scroll_pause=scroll_pause,
            scroll_interval=scroll_interval,
        )

        if detail:
            results.append(detail)
            logger.info(
                "[%d/%d] Collected: title=%s, comments=%d",
                idx + 1,
                total,
                detail.get("title", "")[:30],
                len(detail.get("comments", [])),
            )
        else:
            logger.warning("[%d/%d] Collection failed: note_id=%s", idx + 1, total, note_id)

        # Random delay between notes (not needed after the last one)
        if idx < total - 1:
            delay = random.uniform(*delay_range)
            logger.debug("Waiting %.1f s before collecting the next note...", delay)
            await asyncio.sleep(delay)

    logger.info(
        "Bulk collection finished: %d/%d notes succeeded",
        len(results),
        total,
    )
    return results


async def _fetch_single_note(
    bm: BrowserManager,
    note_id: str,
    note_url: str,
    max_comments: int,
    scroll_pause: float,
    scroll_interval: tuple[float, float],
) -> dict | None:
    """Collect a single note's details and comments, with retry logic."""
    for attempt in range(_MAX_RETRIES + 1):
        page = await bm.new_page()
        try:
            # Navigate to the note detail page
            await page.goto(
                note_url,
                wait_until="domcontentloaded",
                timeout=_PAGE_LOAD_TIMEOUT_MS,
            )

            # Wait for the core content to load
            await _wait_for_content(page)

            # Parse the details
            detail = await parse_note_detail(page, note_id)
            if detail is None:
                logger.warning("Note detail parsing returned None (note_id=%s)", note_id)
                return None

            # Collect comments
            comments = await fetch_comments(
                page,
                note_id=note_id,
                max_count=max_comments,
                scroll_pause=scroll_pause,
                scroll_interval=scroll_interval,
            )
            detail["comments"] = comments

            return detail

        except PlaywrightTimeoutError:
            if attempt < _MAX_RETRIES:
                logger.warning(
                    "Note page load timed out, retry %d/%d (note_id=%s)",
                    attempt + 1,
                    _MAX_RETRIES,
                    note_id,
                )
                await asyncio.sleep(1)
            else:
                logger.error("Note page load timed out, maximum retries reached (note_id=%s)", note_id)
                return None
        except Exception as e:
            logger.error("Error collecting note details (note_id=%s): %s", note_id, e, exc_info=True)
            return None
        finally:
            await page.close()

    return None


async def _wait_for_content(page: Page) -> None:
    """Wait for the core content of the note detail page to finish rendering.

    Tries several selectors in priority order; the page counts as ready once any one appears.
    If all of them time out, still continue after a fixed wait (allowing degraded parsing).
    """
    for sel in _NOTE_READY_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=5_000)
            logger.debug("Detail page content ready (selector: %s)", sel)
            break
        except PlaywrightTimeoutError:
            continue
    else:
        logger.debug("No known selector detected on the detail page, continuing after %.1f s", _RENDER_WAIT)

    # Extra wait to make sure JS rendering has finished (engagement data, comment section, etc.)
    await asyncio.sleep(_RENDER_WAIT)

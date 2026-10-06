"""
Comment collection module

Responsibilities:
  - Locate the comment section on a note detail page
  - Scroll the comment section to load more comments (if below the target count)
  - Extract comment DOM elements in order and parse them with parser
  - Return a structured list of comments

Collection flow:
  1. Locate the comment section on the loaded note detail page
  2. Scroll the comment section to load more (if below the target count)
  3. Extract comment elements and parse them one by one
  4. Return at most max_count comments

Usage:
    comments = await fetch_comments(page, note_id="abc123", max_count=20)
"""

from __future__ import annotations

import asyncio
import logging
import random

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.parser import parse_comment

logger = logging.getLogger(__name__)

# Selectors for a single comment (tried in priority order)
# Real DOM: .comments-container > .parent-comment > .comment-item#comment-{id}
# .parent-comment > .comment-item selects only top-level comments, excluding .comment-item-sub replies
_COMMENT_ITEM_SELECTORS = [
    ".parent-comment > .comment-item",         # exact: top-level comments only
    ".comments-container .comment-item",        # fallback: includes replies
    ".comment-item",                            # generic fallback
]

# Timeout waiting for the comment section to appear (ms)
_COMMENT_WAIT_TIMEOUT_MS = 10_000

# Parameters for scrolling the comment section
_SCROLL_PX_MIN = 200
_SCROLL_PX_MAX = 400
_MAX_STALE_ROUNDS = 3


async def fetch_comments(
    page: Page,
    note_id: str,
    max_count: int = 20,
    scroll_pause: float = 1.5,
    scroll_interval: tuple[float, float] = (1.0, 2.0),
) -> list[dict]:
    """Collect the comment list from a note detail page.

    The page must already have the note detail loaded; this does not navigate.

    Args:
        page: Playwright Page with the note detail page loaded
        note_id: Note ID (attached to each comment record)
        max_count: Maximum number of comments to collect
        scroll_pause: Fixed wait after each scroll (seconds)
        scroll_interval: Extra random delay range (min, max) (seconds)

    Returns:
        A list of comment dicts, each containing:
        comment_id / note_id / user_name / user_id / content / likes / time / ip_location
    """
    logger.info("Collecting comments (note_id=%s, target=%d)", note_id, max_count)

    # Detect the comment element selector
    item_selector = await _detect_comment_selector(page)
    if item_selector is None:
        logger.warning("No comment elements found (note_id=%s); the note may have no comments or the selectors are stale", note_id)
        return []

    logger.info("Comment selector confirmed: %s", item_selector)

    # Scroll to load more comments
    await _scroll_comments(
        page,
        item_selector=item_selector,
        target_count=max_count,
        scroll_pause=scroll_pause,
        scroll_interval=scroll_interval,
    )

    # Extract and parse comments
    comment_els = await page.query_selector_all(item_selector)
    logger.info("Found %d comment elements, parsing...", len(comment_els))

    results: list[dict] = []
    for i, el in enumerate(comment_els[:max_count]):
        parsed = await parse_comment(el, note_id)
        if parsed:
            results.append(parsed)
        else:
            logger.debug("Comment #%d failed to parse, skipped", i + 1)

    logger.info(
        "Comment collection done: note_id=%s, parsed %d/%d",
        note_id,
        len(results),
        min(len(comment_els), max_count),
    )
    return results


async def _detect_comment_selector(page: Page) -> str | None:
    """Try candidate selectors in priority order and return the first with matching elements.

    Waits up to 10 seconds; returns None if nothing appears (the note may have no comments).
    """
    for sel in _COMMENT_ITEM_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=_COMMENT_WAIT_TIMEOUT_MS)
            count = len(await page.query_selector_all(sel))
            if count > 0:
                logger.debug("Comment selector '%s' matched %d elements", sel, count)
                return sel
        except PlaywrightTimeoutError:
            logger.debug("Comment selector '%s' timed out, trying the next one", sel)
        except Exception as e:
            logger.debug("Comment selector '%s' raised: %s", sel, e)

    return None


async def _scroll_comments(
    page: Page,
    item_selector: str,
    target_count: int,
    scroll_pause: float,
    scroll_interval: tuple[float, float],
) -> None:
    """Scroll the comment section container to load more comments.

    On rednote note detail pages the comment section lives inside the scrollable .note-scroller container.
    That container must be scrolled, not the page itself.
    Falls back to page-level scrolling if .note-scroller is not found.
    """
    stale_rounds = 0

    # Scrollable containers that hold the comment section
    scroller_selectors = [".note-scroller", ".interaction-container"]

    while True:
        current_count = len(await page.query_selector_all(item_selector))
        logger.debug("Current comments: %d / target: %d", current_count, target_count)

        if current_count >= target_count:
            logger.info("Reached target comment count (%d), stopping scroll", target_count)
            break

        # Scroll the scrollable container
        scroll_px = random.randint(_SCROLL_PX_MIN, _SCROLL_PX_MAX)
        scrolled = False
        for sel in scroller_selectors:
            scroller = await page.query_selector(sel)
            if scroller:
                await scroller.evaluate(f"el => el.scrollBy(0, {scroll_px})")
                scrolled = True
                break
        if not scrolled:
            # Fall back to page-level scrolling
            await page.mouse.wheel(0, scroll_px)

        # Wait for new comments to load
        await asyncio.sleep(scroll_pause)
        extra_wait = random.uniform(*scroll_interval)
        await asyncio.sleep(extra_wait)

        new_count = len(await page.query_selector_all(item_selector))

        if new_count <= current_count:
            stale_rounds += 1
            logger.debug("Comment count did not grow, stale_rounds=%d", stale_rounds)
            if stale_rounds >= _MAX_STALE_ROUNDS:
                logger.info("No new comments for %d consecutive rounds, stopping scroll", stale_rounds)
                break
        else:
            stale_rounds = 0

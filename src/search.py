"""
Search result collection module

Responsibilities:
  - Navigate to the rednote search page for a keyword
  - Mimic human scrolling to trigger the waterfall feed to load
  - Extract the note cards on the page and call the parser on them
  - Stop once the target count is reached or no new content appears

Paging strategy (waterfall feed):
  rednote search results use infinite scroll (not pagination), so changes in the card count are watched to tell whether more content remains.
  If the card count has not grown after two consecutive scrolls, the bottom is assumed to have been reached.

Usage:
    async with BrowserManager() as bm:
        results = await search_notes(bm, keyword="Python", max_count=20)
"""

from __future__ import annotations

import asyncio
import logging
import random
from urllib.parse import quote

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.browser import BrowserManager
from src.parser import parse_search_card
from src.site import SEARCH_URL

logger = logging.getLogger(__name__)

# Search page URL template (type=51 is the general search)
_SEARCH_URL = SEARCH_URL

# Search card selectors (tried in priority order)
_CARD_SELECTORS = [
    "section.note-item",
    "div.note-item",
    "[class*='NoteItem']",
    ".search-result-list > *",  # Fallback: direct children of the container
]

# Timeout waiting for the first batch of cards (milliseconds)
_INITIAL_WAIT_TIMEOUT_MS = 30_000

# Distance range of a single scroll (pixels)
_SCROLL_PX_MIN = 300
_SCROLL_PX_MAX = 600

# Threshold of consecutive rounds with no new cards; scrolling stops once it is reached
_MAX_STALE_ROUNDS = 2


async def search_notes(
    bm: BrowserManager,
    keyword: str,
    max_count: int = 20,
    scroll_pause: float = 1.5,
    scroll_interval: tuple[float, float] = (1.0, 3.0),
) -> list[dict]:
    """Search rednote for a keyword and collect a list of note summaries.

    Args:
        bm: An initialised, logged-in BrowserManager instance
        keyword: Search keyword
        max_count: Maximum number of notes to return
        scroll_pause: Fixed wait time after each scroll (seconds)
        scroll_interval: Extra random delay range (min, max) (seconds)

    Returns:
        A list of note summary dicts, each containing:
        note_id / title / author / author_id / cover_url / likes / note_url / note_type
    """
    url = _SEARCH_URL.format(keyword=quote(keyword))
    logger.info("Starting search: keyword=%s, target count=%d", keyword, max_count)

    page = await bm.new_page()
    try:
        # Navigate to the search page
        await page.goto(url, wait_until="domcontentloaded", timeout=_INITIAL_WAIT_TIMEOUT_MS)
        logger.info("Search page loaded: %s", url)

        # Wait for the first batch of cards to appear
        card_selector = await _detect_card_selector(page)
        if card_selector is None:
            logger.error("No search result cards found, please check the selectors or login state (keyword=%s)", keyword)
            return []

        logger.info("Card selector confirmed: %s", card_selector)

        # Scroll to load more cards
        await _scroll_to_load(
            page,
            card_selector=card_selector,
            target_count=max_count,
            scroll_pause=scroll_pause,
            scroll_interval=scroll_interval,
        )

        # Extract all card elements and parse them
        cards = await page.query_selector_all(card_selector)
        logger.info("Got %d card elements, starting to parse...", len(cards))

        results: list[dict] = []
        for i, card in enumerate(cards[:max_count]):
            parsed = await parse_search_card(card)
            if parsed:
                results.append(parsed)
            else:
                logger.debug("Card #%d failed to parse, skipped", i + 1)

        logger.info(
            "Search collection finished: keyword=%s, parsed %d/%d successfully",
            keyword,
            len(results),
            len(cards[:max_count]),
        )
        return results

    except PlaywrightTimeoutError:
        logger.error("Search page load timed out (keyword=%s)", keyword)
        return []
    except Exception as e:
        logger.error("Search collection error: %s", e, exc_info=True)
        return []
    finally:
        await page.close()


async def _detect_card_selector(page) -> str | None:
    """Try several candidate selectors and return the first one that matches elements on the page.

    Waits up to 30 seconds for the first batch of cards to appear.

    Args:
        page: Playwright Page object

    Returns:
        A valid CSS selector string, or None (all failed)
    """
    for sel in _CARD_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=_INITIAL_WAIT_TIMEOUT_MS)
            count = len(await page.query_selector_all(sel))
            if count > 0:
                logger.debug("Selector '%s' matched %d elements", sel, count)
                return sel
        except PlaywrightTimeoutError:
            logger.debug("Selector '%s' timed out, trying the next one", sel)
        except Exception as e:
            logger.debug("Selector '%s' failed: %s", sel, e)

    return None


async def _scroll_to_load(
    page,
    card_selector: str,
    target_count: int,
    scroll_pause: float,
    scroll_interval: tuple[float, float],
) -> None:
    """Scroll the page in a loop until the target card count is reached or no new content appears.

    Args:
        page: Playwright Page object
        card_selector: A verified card CSS selector
        target_count: Target number of cards
        scroll_pause: Fixed wait time (seconds)
        scroll_interval: Extra random wait range (min, max) (seconds)
    """
    stale_rounds = 0  # Consecutive rounds with no new cards

    while True:
        current_count = len(await page.query_selector_all(card_selector))
        logger.debug("Current card count: %d / target: %d", current_count, target_count)

        if current_count >= target_count:
            logger.info("Target card count reached (%d), stopping scrolling", target_count)
            break

        # Perform a random scroll
        scroll_px = random.randint(_SCROLL_PX_MIN, _SCROLL_PX_MAX)
        await page.mouse.wheel(0, scroll_px)

        # Wait for new content to load
        await asyncio.sleep(scroll_pause)
        extra_wait = random.uniform(*scroll_interval)
        await asyncio.sleep(extra_wait)

        new_count = len(await page.query_selector_all(card_selector))

        if new_count <= current_count:
            stale_rounds += 1
            logger.debug("Card count did not grow, stale_rounds=%d", stale_rounds)
            if stale_rounds >= _MAX_STALE_ROUNDS:
                logger.info("No new cards for %d consecutive rounds, assuming the bottom has been reached", stale_rounds)
                break
        else:
            stale_rounds = 0  # New cards appeared, reset the counter

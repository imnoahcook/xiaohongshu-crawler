"""
Unit tests for the search module

Test strategy:
  - BrowserManager is mocked with AsyncMock, with no dependency on a real browser
  - asyncio.sleep is patched to a no-op to avoid test delays
  - parse_search_card is patched to isolate the parser dependency
  - Covers: search_notes, _detect_card_selector, _scroll_to_load
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.search import _detect_card_selector, _scroll_to_load, search_notes


# ============================================================
# Helpers
# ============================================================


def _make_bm(page: AsyncMock | None = None) -> AsyncMock:
    """Create a mock BrowserManager whose new_page() returns the given page mock."""
    bm = AsyncMock()
    bm.new_page = AsyncMock(return_value=page or AsyncMock())
    return bm


def _make_page(
    qsa_results: dict | None = None,
    goto_raises: Exception | None = None,
) -> AsyncMock:
    """Create a general-purpose mock Page.

    Args:
        qsa_results: Mapping of sel → [element, ...]
        goto_raises: If set, goto() raises this exception
    """
    page = AsyncMock()
    qsa_results = qsa_results or {}

    if goto_raises:
        page.goto = AsyncMock(side_effect=goto_raises)
    else:
        page.goto = AsyncMock(return_value=None)

    page.query_selector_all = AsyncMock(
        side_effect=lambda sel: qsa_results.get(sel, [])
    )
    page.wait_for_selector = AsyncMock(
        side_effect=lambda sel, **kw: (_ for _ in ()).throw(PlaywrightTimeoutError("timeout"))
        if not qsa_results.get(sel)
        else None
    )
    page.mouse = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.close = AsyncMock()
    return page


# ============================================================
# _detect_card_selector
# ============================================================


class TestDetectCardSelector:
    """Tests for search card selector detection."""

    async def test_returns_selector_with_elements(self):
        """A selector that has elements should be returned."""
        el = AsyncMock()
        page = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[el])

        result = await _detect_card_selector(page)

        assert result is not None

    async def test_returns_none_when_all_timeout(self):
        """Should return None when all selectors time out."""
        page = AsyncMock()
        page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )

        result = await _detect_card_selector(page)

        assert result is None

    async def test_returns_none_on_exception(self):
        """Should keep trying when a selector raises and eventually return None."""
        page = AsyncMock()
        page.wait_for_selector = AsyncMock(side_effect=Exception("unexpected"))

        result = await _detect_card_selector(page)

        assert result is None

    async def test_skips_selector_with_zero_elements(self):
        """Only returned when there are matching elements (non-empty); empty lists are skipped."""
        el = AsyncMock()
        call_count = 0

        async def qsa(sel):
            nonlocal call_count
            call_count += 1
            return [] if call_count == 1 else [el]

        page = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(side_effect=qsa)

        result = await _detect_card_selector(page)

        assert result is not None
        assert call_count >= 2


# ============================================================
# _scroll_to_load
# ============================================================


class TestScrollToLoad:
    """Tests for the waterfall feed scroll-loading logic."""

    async def test_stops_immediately_when_count_met(self):
        """No scrolling when the current card count already meets the target."""
        page = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[AsyncMock()] * 5)
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()

        with patch("asyncio.sleep", new=AsyncMock()):
            await _scroll_to_load(
                page,
                card_selector="section.note-item",
                target_count=3,
                scroll_pause=0.0,
                scroll_interval=(0.0, 0.0),
            )

        page.mouse.wheel.assert_not_called()

    async def test_stops_after_stale_rounds(self):
        """Stops when consecutive rounds with no new cards reach the threshold."""
        page = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[])
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()

        with patch("asyncio.sleep", new=AsyncMock()):
            await _scroll_to_load(
                page,
                card_selector="section.note-item",
                target_count=20,
                scroll_pause=0.0,
                scroll_interval=(0.0, 0.0),
            )

        assert page.mouse.wheel.call_count >= 1

    async def test_resets_stale_count_when_new_cards_appear(self):
        """stale_rounds should reset when new cards appear."""
        counts = [0, 3, 3, 3]  # Growth in the second round, then stagnation
        call_idx = 0

        async def qsa(sel):
            nonlocal call_idx
            val = counts[min(call_idx, len(counts) - 1)]
            call_idx += 1
            return [AsyncMock()] * val

        page = AsyncMock()
        page.query_selector_all = AsyncMock(side_effect=qsa)
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()

        with patch("asyncio.sleep", new=AsyncMock()):
            await _scroll_to_load(
                page,
                card_selector="section.note-item",
                target_count=20,
                scroll_pause=0.0,
                scroll_interval=(0.0, 0.0),
            )

        assert page.mouse.wheel.call_count >= 1


# ============================================================
# search_notes
# ============================================================


class TestSearchNotes:
    """Tests for the search_notes public interface."""

    async def test_returns_empty_when_no_selector_found(self):
        """Should return an empty list when no card selector is found."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )
        page.close = AsyncMock()

        bm = _make_bm(page)

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await search_notes(
                bm,
                keyword="Python",
                max_count=5,
                scroll_pause=0.0,
                scroll_interval=(0.0, 0.0),
            )

        assert result == []

    async def test_returns_parsed_cards(self):
        """Should return the result list when cards are found and parsed successfully."""
        el = AsyncMock()
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[el, el])
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()
        page.close = AsyncMock()

        bm = _make_bm(page)

        mock_card = {"note_id": "n1", "title": "Test"}

        with (
            patch("src.search.parse_search_card", return_value=mock_card),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await search_notes(
                bm,
                keyword="Python",
                max_count=10,
                scroll_pause=0.0,
                scroll_interval=(0.0, 0.0),
            )

        assert len(result) == 2

    async def test_skips_failed_cards(self):
        """Cards for which parse_search_card returns None should be skipped."""
        el = AsyncMock()
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[el])
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()
        page.close = AsyncMock()

        bm = _make_bm(page)

        with (
            patch("src.search.parse_search_card", return_value=None),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await search_notes(
                bm,
                keyword="Python",
                max_count=5,
                scroll_pause=0.0,
                scroll_interval=(0.0, 0.0),
            )

        assert result == []

    async def test_returns_empty_on_timeout(self):
        """Should return an empty list when the page load times out."""
        page = AsyncMock()
        page.goto = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))
        page.close = AsyncMock()

        bm = _make_bm(page)

        result = await search_notes(bm, keyword="Python", max_count=5)

        assert result == []

    async def test_returns_empty_on_general_exception(self):
        """Should return an empty list on any other exception."""
        page = AsyncMock()
        page.goto = AsyncMock(side_effect=Exception("network error"))
        page.close = AsyncMock()

        bm = _make_bm(page)

        result = await search_notes(bm, keyword="Python", max_count=5)

        assert result == []

    async def test_closes_page_even_on_error(self):
        """page.close() should be called whether it succeeds or fails."""
        page = AsyncMock()
        page.goto = AsyncMock(side_effect=Exception("error"))
        page.close = AsyncMock()

        bm = _make_bm(page)

        await search_notes(bm, keyword="Python", max_count=5)

        page.close.assert_called_once()

    async def test_respects_max_count(self):
        """Returns at most max_count results."""
        els = [AsyncMock() for _ in range(10)]
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=els)
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()
        page.close = AsyncMock()

        bm = _make_bm(page)

        mock_card = {"note_id": "n1", "title": "Test"}

        with (
            patch("src.search.parse_search_card", return_value=mock_card),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await search_notes(
                bm,
                keyword="Python",
                max_count=3,
                scroll_pause=0.0,
                scroll_interval=(0.0, 0.0),
            )

        assert len(result) == 3

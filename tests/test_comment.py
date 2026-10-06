"""
Unit tests for the comment module

Test strategy:
  - Playwright Page is fully mocked with AsyncMock; no real browser needed
  - asyncio.sleep is patched to a no-op to avoid test delays
  - parse_comment is patched to isolate the parser dependency
  - Coverage: fetch_comments, _detect_comment_selector, _scroll_comments
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.comment import _detect_comment_selector, _scroll_comments, fetch_comments


# ============================================================
# Helpers
# ============================================================


def _make_page(
    selector_elements: dict | None = None,
    all_elements: dict | None = None,
) -> AsyncMock:
    """Create a general-purpose mock Page.

    Args:
        selector_elements: mapping of sel → element (query_selector)
        all_elements: mapping of sel → [element, ...] (query_selector_all)
    """
    page = AsyncMock()
    selector_elements = selector_elements or {}
    all_elements = all_elements or {}

    async def wait_for_selector(sel, *, timeout=None):
        if sel not in (all_elements or {}) or not all_elements.get(sel):
            raise PlaywrightTimeoutError("timeout")

    page.wait_for_selector = AsyncMock(side_effect=wait_for_selector)
    page.query_selector_all = AsyncMock(
        side_effect=lambda sel: all_elements.get(sel, [])
    )
    page.query_selector = AsyncMock(
        side_effect=lambda sel: selector_elements.get(sel)
    )
    page.mouse = AsyncMock()
    page.mouse.wheel = AsyncMock()
    return page


# ============================================================
# _detect_comment_selector
# ============================================================


class TestDetectCommentSelector:
    """Test comment selector detection logic."""

    async def test_returns_first_matching_selector(self):
        """The first selector with elements should be returned."""
        el = AsyncMock()
        page = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[el])

        result = await _detect_comment_selector(page)

        assert result is not None
        assert isinstance(result, str)

    async def test_skips_empty_selector(self):
        """Only a selector with matching elements is returned (empty lists are skipped)."""
        el = AsyncMock()
        call_count = 0

        page = AsyncMock()

        async def wait_for_selector(sel, *, timeout=None):
            pass  # does not raise

        async def qsa(sel):
            nonlocal call_count
            call_count += 1
            # First call returns empty (skipped), second returns elements
            return [] if call_count == 1 else [el]

        page.wait_for_selector = AsyncMock(side_effect=wait_for_selector)
        page.query_selector_all = AsyncMock(side_effect=qsa)

        result = await _detect_comment_selector(page)

        assert result is not None
        assert call_count >= 2

    async def test_returns_none_when_all_selectors_timeout(self):
        """Should return None when every selector times out."""
        page = AsyncMock()
        page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )

        result = await _detect_comment_selector(page)

        assert result is None

    async def test_returns_none_on_exception(self):
        """Should keep trying on non-timeout exceptions and finally return None."""
        page = AsyncMock()
        page.wait_for_selector = AsyncMock(
            side_effect=Exception("unexpected")
        )

        result = await _detect_comment_selector(page)

        assert result is None


# ============================================================
# _scroll_comments
# ============================================================


class TestScrollComments:
    """Test comment section scrolling logic."""

    async def test_stops_immediately_when_count_met(self):
        """Should not scroll when the current comment count already meets the target."""
        el = AsyncMock()
        page = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[el] * 5)
        page.query_selector = AsyncMock(return_value=None)
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()

        with patch("asyncio.sleep", new=AsyncMock()):
            await _scroll_comments(
                page,
                item_selector=".comment-item",
                target_count=3,  # target < current
                scroll_pause=0.0,
                scroll_interval=(0.0, 0.0),
            )

        page.mouse.wheel.assert_not_called()

    async def test_scrolls_using_scroller_element(self):
        """Should scroll via the container rather than mouse.wheel when a scrollable container is found."""
        el = AsyncMock()
        scroller = AsyncMock()
        scroller.evaluate = AsyncMock()

        counts = [0, 5]  # first 0, then 5 → target met
        call_idx = 0

        async def qsa(sel):
            nonlocal call_idx
            if ".comment-item" in sel or sel == ".comment-item":
                val = counts[min(call_idx, len(counts) - 1)]
                call_idx += 1
                return [AsyncMock()] * val
            return []

        async def qs(sel):
            if sel in (".note-scroller", ".interaction-container"):
                return scroller if sel == ".note-scroller" else None
            return None

        page = AsyncMock()
        page.query_selector_all = AsyncMock(side_effect=qsa)
        page.query_selector = AsyncMock(side_effect=qs)
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()

        with patch("asyncio.sleep", new=AsyncMock()):
            await _scroll_comments(
                page,
                item_selector=".comment-item",
                target_count=5,
                scroll_pause=0.0,
                scroll_interval=(0.0, 0.0),
            )

        scroller.evaluate.assert_called()
        page.mouse.wheel.assert_not_called()

    async def test_falls_back_to_mouse_wheel_when_no_scroller(self):
        """Should fall back to mouse.wheel scrolling when no scroll container is found."""
        counts = [0, 5]
        call_idx = 0

        async def qsa(sel):
            nonlocal call_idx
            val = counts[min(call_idx, len(counts) - 1)]
            call_idx += 1
            return [AsyncMock()] * val

        page = AsyncMock()
        page.query_selector_all = AsyncMock(side_effect=qsa)
        page.query_selector = AsyncMock(return_value=None)  # no scroll container
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()

        with patch("asyncio.sleep", new=AsyncMock()):
            await _scroll_comments(
                page,
                item_selector=".comment-item",
                target_count=5,
                scroll_pause=0.0,
                scroll_interval=(0.0, 0.0),
            )

        page.mouse.wheel.assert_called()

    async def test_stops_after_stale_rounds(self):
        """Should stop scrolling once consecutive rounds without new comments hit the threshold."""
        page = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[])  # always empty
        page.query_selector = AsyncMock(return_value=None)
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()

        with patch("asyncio.sleep", new=AsyncMock()):
            # Target is 10 but the count stays 0; should stop after stale_rounds=3
            await _scroll_comments(
                page,
                item_selector=".comment-item",
                target_count=10,
                scroll_pause=0.0,
                scroll_interval=(0.0, 0.0),
            )

        # Scrolled at least once (and did not loop forever)
        assert page.mouse.wheel.call_count >= 1


# ============================================================
# fetch_comments
# ============================================================


class TestFetchComments:
    """Test the fetch_comments public interface."""

    async def test_returns_empty_when_no_selector_found(self):
        """Should return an empty list when no comment selector is found."""
        page = AsyncMock()
        page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )

        result = await fetch_comments(page, note_id="abc", max_count=5)

        assert result == []

    async def test_returns_parsed_comments(self):
        """Should return the comment list when parsing succeeds."""
        el1 = AsyncMock()
        el2 = AsyncMock()
        mock_comment1 = {"comment_id": "c1", "content": "Comment 1"}
        mock_comment2 = {"comment_id": "c2", "content": "Comment 2"}

        page = AsyncMock()

        async def wait_for_selector(sel, *, timeout=None):
            pass  # does not time out

        page.wait_for_selector = AsyncMock(side_effect=wait_for_selector)
        page.query_selector_all = AsyncMock(return_value=[el1, el2])
        page.query_selector = AsyncMock(return_value=None)
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()

        with (
            patch("src.comment.parse_comment", side_effect=[mock_comment1, mock_comment2]),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await fetch_comments(page, note_id="abc", max_count=10)

        assert len(result) == 2
        assert result[0]["comment_id"] == "c1"

    async def test_skips_failed_comments(self):
        """Comments whose parse returns None should be skipped."""
        el = AsyncMock()
        page = AsyncMock()

        async def wait_for_selector(sel, *, timeout=None):
            pass

        page.wait_for_selector = AsyncMock(side_effect=wait_for_selector)
        page.query_selector_all = AsyncMock(return_value=[el])
        page.query_selector = AsyncMock(return_value=None)
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()

        with (
            patch("src.comment.parse_comment", return_value=None),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await fetch_comments(page, note_id="abc", max_count=5)

        assert result == []

    async def test_respects_max_count(self):
        """Should return at most max_count comments."""
        els = [AsyncMock() for _ in range(10)]
        page = AsyncMock()

        async def wait_for_selector(sel, *, timeout=None):
            pass

        page.wait_for_selector = AsyncMock(side_effect=wait_for_selector)
        page.query_selector_all = AsyncMock(return_value=els)
        page.query_selector = AsyncMock(return_value=None)
        page.mouse = AsyncMock()
        page.mouse.wheel = AsyncMock()

        def fake_parse(el, note_id):
            return {"comment_id": "x", "content": "c"}

        with (
            patch("src.comment.parse_comment", side_effect=fake_parse),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await fetch_comments(page, note_id="abc", max_count=3)

        assert len(result) == 3

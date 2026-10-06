"""
CrawlerSession Phase D tests — health check, automatic recovery, login status detection, structured errors

Test strategy:
  - BrowserManager is fully mocked; no real browser is needed
  - Simulate a browser crash (is_connected returns False) to verify automatic recovery
  - Simulate login expiry to verify the structured error response
  - All error responses contain the four fields error/code/message/action
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from src.session import CrawlerSession


def _make_mock_bm(*, connected: bool = True) -> AsyncMock:
    """Create a standard mock BrowserManager with a controllable is_connected state."""
    mock_bm = AsyncMock()
    mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
    mock_bm.__aexit__ = AsyncMock(return_value=None)

    # Simulate context.browser.is_connected()
    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = connected
    mock_context = MagicMock()
    mock_context.browser = mock_browser
    type(mock_bm).context = PropertyMock(return_value=mock_context)

    # Default new_page
    mock_page = AsyncMock()
    mock_bm.new_page = AsyncMock(return_value=mock_page)

    return mock_bm


class TestBrowserHealthCheck:
    """D1: browser health check."""

    async def test_healthy_browser_returns_true(self):
        """_is_browser_healthy() returns True when the browser is connected."""
        with patch("src.session.BrowserManager") as MockBM:
            MockBM.return_value = _make_mock_bm(connected=True)

            session = CrawlerSession()
            await session.start()

            assert await session._is_browser_healthy() is True

    async def test_disconnected_browser_returns_false(self):
        """_is_browser_healthy() returns False when the browser is disconnected."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = _make_mock_bm(connected=False)
            MockBM.return_value = mock_bm

            session = CrawlerSession()
            await session.start()

            assert await session._is_browser_healthy() is False

    async def test_none_bm_returns_false(self):
        """_is_browser_healthy() returns False when _bm is None."""
        session = CrawlerSession()
        assert await session._is_browser_healthy() is False

    async def test_none_context_returns_false(self):
        """_is_browser_healthy() returns False when context is None."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = _make_mock_bm(connected=True)
            type(mock_bm).context = PropertyMock(return_value=None)
            MockBM.return_value = mock_bm

            session = CrawlerSession()
            await session.start()

            assert await session._is_browser_healthy() is False

    async def test_exception_during_check_returns_false(self):
        """Returns False when the health check raises (the exception is not propagated)."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = _make_mock_bm(connected=True)
            # Accessing the context attribute raises
            type(mock_bm).context = PropertyMock(side_effect=RuntimeError("boom"))
            MockBM.return_value = mock_bm

            session = CrawlerSession()
            await session.start()

            assert await session._is_browser_healthy() is False


class TestBrowserAutoRecovery:
    """D1: automatic recovery from browser crashes."""

    async def test_auto_recovery_on_crashed_browser(self):
        """After a browser crash, _ensure_browser() should rebuild the browser automatically."""
        call_count = 0

        # First creation: disconnected (simulated crash)
        # Second creation: connected (recovery succeeded)
        def make_bm_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_mock_bm(connected=False)
            return _make_mock_bm(connected=True)

        with patch("src.session.BrowserManager", side_effect=make_bm_side_effect):
            session = CrawlerSession()
            await session.start()

            # First check: crashed, should trigger recovery
            bm = await session._ensure_browser()
            assert bm is not None
            assert session.is_running() is True

    async def test_auto_recovery_failure_returns_none(self):
        """_ensure_browser() should return None when automatic recovery also fails."""
        call_count = 0

        def make_bm_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_mock_bm(connected=False)
            # Second creation raises (recovery failed)
            mock_bm = AsyncMock()
            mock_bm.__aenter__ = AsyncMock(side_effect=RuntimeError("recovery failed"))
            mock_bm.__aexit__ = AsyncMock(return_value=None)
            return mock_bm

        with patch("src.session.BrowserManager", side_effect=make_bm_side_effect):
            session = CrawlerSession()
            await session.start()

            bm = await session._ensure_browser()
            assert bm is None

    async def test_ensure_browser_returns_bm_when_healthy(self):
        """When the browser is healthy, _ensure_browser() returns the current BrowserManager directly."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = _make_mock_bm(connected=True)
            MockBM.return_value = mock_bm

            session = CrawlerSession()
            await session.start()

            bm = await session._ensure_browser()
            assert bm is mock_bm

    async def test_ensure_browser_when_not_running(self):
        """_ensure_browser() returns None when not started."""
        session = CrawlerSession()
        bm = await session._ensure_browser()
        assert bm is None


class TestStructuredErrors:
    """D1 + D3: every method should return structured errors in the unified format."""

    async def test_search_notes_returns_structured_error_when_not_running(self):
        """search_notes should return an error with a code field when the browser is not running."""
        session = CrawlerSession()
        result = await session.search_notes("test")

        assert result["error"] is True
        assert "code" in result
        assert result["code"] == "BROWSER_NOT_RUNNING"
        assert "action" in result

    async def test_get_note_detail_returns_structured_error_when_not_running(self):
        """get_note_detail should return a structured error when the browser is not running."""
        session = CrawlerSession()
        result = await session.get_note_detail("https://example.com/explore/123")

        assert result["error"] is True
        assert result["code"] == "BROWSER_NOT_RUNNING"
        assert "action" in result

    async def test_crawl_keyword_returns_structured_error_when_not_running(self):
        """crawl_keyword should return a structured error when the browser is not running."""
        session = CrawlerSession()
        result = await session.crawl_keyword("test")

        assert result["error"] is True
        assert result["code"] == "BROWSER_NOT_RUNNING"
        assert "action" in result

    async def test_check_login_returns_structured_error_when_not_running(self):
        """check_login_status should return a structured error when the browser is not running."""
        session = CrawlerSession()
        result = await session.check_login_status()

        assert result["logged_in"] is False
        assert result["browser_running"] is False
        assert "code" in result
        assert result["code"] == "BROWSER_NOT_RUNNING"

    async def test_search_notes_returns_structured_error_on_browser_crash(self):
        """search_notes returns BROWSER_CRASHED when the browser crashed and recovery failed."""
        call_count = 0

        def make_bm_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_mock_bm(connected=False)
            mock_bm = AsyncMock()
            mock_bm.__aenter__ = AsyncMock(side_effect=RuntimeError("recovery failed"))
            mock_bm.__aexit__ = AsyncMock(return_value=None)
            return mock_bm

        with patch("src.session.BrowserManager", side_effect=make_bm_side_effect):
            session = CrawlerSession()
            await session.start()

            result = await session.search_notes("test")
            assert result["error"] is True
            assert result["code"] == "BROWSER_CRASHED"


class TestLoginDetection:
    """D2: detection of login expiry during operations."""

    async def test_search_detects_login_expired(self):
        """When search_notes gets empty results, it should check login status and return LOGIN_EXPIRED."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = _make_mock_bm(connected=True)
            MockBM.return_value = mock_bm

            session = CrawlerSession()
            await session.start()

            # search returns empty + the login check reports not logged in
            with patch("src.search.search_notes", new_callable=AsyncMock, return_value=[]):
                with patch("src.session.is_logged_in", new_callable=AsyncMock, return_value=False):
                    result = await session.search_notes("test")

                    assert result["error"] is True
                    assert result["code"] == "LOGIN_EXPIRED"
                    assert "Log in" in result["action"]

    async def test_search_returns_normal_empty_when_logged_in(self):
        """Logged in but no search results: returns a normal empty result (no false LOGIN_EXPIRED)."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = _make_mock_bm(connected=True)
            MockBM.return_value = mock_bm

            session = CrawlerSession()
            await session.start()

            with patch("src.search.search_notes", new_callable=AsyncMock, return_value=[]):
                with patch("src.session.is_logged_in", new_callable=AsyncMock, return_value=True):
                    result = await session.search_notes("test")

                    # Normal empty result, not an error
                    assert result.get("error") is not True
                    assert result["count"] == 0

    async def test_get_note_detail_detects_login_expired(self):
        """When get_note_detail gets None, it should check login status and return LOGIN_EXPIRED."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = _make_mock_bm(connected=True)
            MockBM.return_value = mock_bm

            session = CrawlerSession()
            await session.start()

            with patch("src.note.fetch_single_note", new_callable=AsyncMock, return_value=None):
                with patch("src.session.is_logged_in", new_callable=AsyncMock, return_value=False):
                    result = await session.get_note_detail(
                        "https://www.rednote.com/explore/abc123"
                    )

                    assert result["error"] is True
                    assert result["code"] == "LOGIN_EXPIRED"

    async def test_get_note_detail_returns_crawl_failed_when_logged_in(self):
        """Logged in but the crawl failed: returns CRAWL_FAILED (not LOGIN_EXPIRED)."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = _make_mock_bm(connected=True)
            MockBM.return_value = mock_bm

            session = CrawlerSession()
            await session.start()

            with patch("src.note.fetch_single_note", new_callable=AsyncMock, return_value=None):
                with patch("src.session.is_logged_in", new_callable=AsyncMock, return_value=True):
                    result = await session.get_note_detail(
                        "https://www.rednote.com/explore/abc123"
                    )

                    assert result["error"] is True
                    assert result["code"] == "CRAWL_FAILED"

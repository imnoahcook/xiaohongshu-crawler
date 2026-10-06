"""
CrawlerSession unit tests

Test strategy:
  - BrowserManager is fully mocked; no real browser is needed
  - The is_logged_in function is mocked to isolate network calls
  - Covers: initial state, lifecycle, concurrency lock, login status check
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

# The import below fails until src/session.py is implemented (expected RED state)
from src.session import CrawlerSession


class TestCrawlerSessionInitialState:
    """Tests the initial state (browser not started)."""

    def test_not_running_initially(self):
        """is_running() should be False for a new instance."""
        session = CrawlerSession()
        assert session.is_running() is False

    def test_default_headless_is_true(self):
        """The MCP server uses headless mode by default."""
        session = CrawlerSession()
        assert session._headless is True

    def test_custom_headless_false(self):
        """headless=False can be set explicitly (for debugging)."""
        session = CrawlerSession(headless=False)
        assert session._headless is False


class TestCrawlerSessionLifecycle:
    """Tests browser lifecycle management."""

    async def test_start_sets_running(self):
        """is_running() should be True after start() succeeds."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = AsyncMock()
            MockBM.return_value = mock_bm
            mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
            mock_bm.__aexit__ = AsyncMock(return_value=None)

            session = CrawlerSession()
            await session.start()

            assert session.is_running() is True

    async def test_stop_clears_running(self):
        """is_running() should be False after stop()."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = AsyncMock()
            MockBM.return_value = mock_bm
            mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
            mock_bm.__aexit__ = AsyncMock(return_value=None)

            session = CrawlerSession()
            await session.start()
            await session.stop()

            assert session.is_running() is False

    async def test_stop_when_not_running_is_safe(self):
        """Calling stop() when not started should not raise."""
        session = CrawlerSession()
        await session.stop()  # Should not raise
        assert session.is_running() is False

    async def test_double_start_is_idempotent(self):
        """Calling start() repeatedly should not create duplicate browser instances."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = AsyncMock()
            MockBM.return_value = mock_bm
            mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
            mock_bm.__aexit__ = AsyncMock(return_value=None)

            session = CrawlerSession()
            await session.start()
            await session.start()  # The second call should be idempotent

            # BrowserManager should be instantiated only once
            assert MockBM.call_count == 1

    async def test_stop_cleans_up_resources(self):
        """stop() should close the BrowserManager properly and clear all internal state.

        AsyncExitStack.aclose() triggers cleanup through type(cm).__aexit__;
        verify that both _bm and _exit_stack are None after stop().
        """
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = AsyncMock()
            MockBM.return_value = mock_bm
            mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
            mock_bm.__aexit__ = AsyncMock(return_value=None)

            session = CrawlerSession()
            await session.start()
            await session.stop()

            assert session._bm is None
            assert session._exit_stack is None
            assert session.is_running() is False


class TestCrawlerSessionLock:
    """Tests that the concurrency lock serializes operations."""

    async def test_lock_serializes_concurrent_access(self):
        """Concurrent browser_lock() calls should run serially (no interleaving)."""
        session = CrawlerSession()
        execution_order: list[str] = []

        async def task(name: str) -> None:
            async with session.browser_lock():
                execution_order.append(f"enter_{name}")
                await asyncio.sleep(0.01)
                execution_order.append(f"exit_{name}")

        await asyncio.gather(task("a"), task("b"))

        # Verify there is no interleaving: the event right after enter_x must be exit_x
        a_enter = execution_order.index("enter_a")
        a_exit = execution_order.index("exit_a")
        b_enter = execution_order.index("enter_b")
        b_exit = execution_order.index("exit_b")

        # a finishes before b starts, or b finishes before a starts
        assert (a_exit < b_enter) or (b_exit < a_enter)

    async def test_lock_yields_browser_manager(self):
        """browser_lock() should yield the BrowserManager instance (after start)."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = AsyncMock()
            MockBM.return_value = mock_bm
            mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
            mock_bm.__aexit__ = AsyncMock(return_value=None)

            session = CrawlerSession()
            await session.start()

            async with session.browser_lock() as bm:
                assert bm is mock_bm


class TestCrawlerSessionLoginStatus:
    """Tests the login status check interface."""

    async def test_check_login_when_not_running(self):
        """Returns browser_running=False when the browser is not running."""
        session = CrawlerSession()
        result = await session.check_login_status()

        assert result["logged_in"] is False
        assert result["browser_running"] is False
        assert "message" in result
        assert isinstance(result["message"], str)

    async def test_check_login_returns_true_when_logged_in(self):
        """Returns logged_in=True, browser_running=True when logged in."""
        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.session.is_logged_in", return_value=True):
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)
                mock_page = AsyncMock()
                mock_bm.new_page = AsyncMock(return_value=mock_page)

                session = CrawlerSession()
                await session.start()
                result = await session.check_login_status()

                assert result["logged_in"] is True
                assert result["browser_running"] is True
                assert "message" in result

    async def test_check_login_returns_false_when_not_logged_in(self):
        """Returns logged_in=False, browser_running=True when not logged in."""
        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.session.is_logged_in", return_value=False):
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)
                mock_page = AsyncMock()
                mock_bm.new_page = AsyncMock(return_value=mock_page)

                session = CrawlerSession()
                await session.start()
                result = await session.check_login_status()

                assert result["logged_in"] is False
                assert result["browser_running"] is True
                assert "message" in result

    async def test_check_login_closes_page_after_check(self):
        """The page should be closed after the login check to prevent resource leaks."""
        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.session.is_logged_in", return_value=True):
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)
                mock_page = AsyncMock()
                mock_bm.new_page = AsyncMock(return_value=mock_page)

                session = CrawlerSession()
                await session.start()
                await session.check_login_status()

                mock_page.close.assert_called_once()


class TestCrawlerSessionRaceConditionGuards:
    """Tests the second guard against race conditions in each method (the _bm is None path)."""

    async def test_check_login_returns_error_when_bm_is_none_despite_running_flag(self):
        """check_login_status should return browser_running=False when _running=True but _bm=None.

        Simulates the race where stop() completes after the fast-path check but before the lock is acquired, setting _bm to None.
        """
        session = CrawlerSession()
        session._running = True  # Bypass the fast path
        session._bm = None       # Simulate stop() having already set _bm to None

        result = await session.check_login_status()

        assert result["logged_in"] is False
        assert result["browser_running"] is False
        assert "message" in result

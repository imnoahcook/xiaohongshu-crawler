"""
Tests for CrawlerSession Phase B methods

Tests the B1/B3 backend: the search_notes and get_note_detail methods

Test strategy:
  - BrowserManager and the src modules are mocked; no real browser is needed
  - Covers: error responses when the browser is not running, the normal call path, argument passthrough
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.session import CrawlerSession


class TestCrawlerSessionSearchNotes:
    """Tests for the CrawlerSession.search_notes() method."""

    async def test_returns_error_dict_when_not_running(self):
        """Should return a dict with error=True when the browser is not running, without raising."""
        session = CrawlerSession()
        result = await session.search_notes("test-keyword")

        assert isinstance(result, dict)
        assert result.get("error") is True
        assert "message" in result

    async def test_calls_search_module_with_correct_args(self):
        """Should pass keyword and max_count correctly to src.search.search_notes."""
        mock_results = [{"note_id": "1", "title": "Note one"}, {"note_id": "2", "title": "Note two"}]

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=mock_results)) as mock_search:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                session = CrawlerSession()
                await session.start()
                result = await session.search_notes("Python", max_count=10)

                mock_search.assert_called_once_with(mock_bm, keyword="Python", max_count=10)
                assert result["keyword"] == "Python"
                assert result["count"] == 2
                assert result["results"] == mock_results

    async def test_returns_structured_response_keys(self):
        """The return value must contain the keys keyword / count / results."""
        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=[])):
                # Phase D: login status is checked on empty results; mock as logged in to get a normal empty response
                with patch("src.session.is_logged_in", new=AsyncMock(return_value=True)):
                    mock_bm = AsyncMock()
                    MockBM.return_value = mock_bm
                    mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                    mock_bm.__aexit__ = AsyncMock(return_value=None)
                    mock_bm.new_page = AsyncMock(return_value=AsyncMock())

                    session = CrawlerSession()
                    await session.start()
                    result = await session.search_notes("keyword")

                    assert "keyword" in result
                    assert "count" in result
                    assert "results" in result

    async def test_uses_browser_lock_during_search(self):
        """The browser lock should be held during the search (serialized via _lock)."""
        lock_acquired_during_search = False

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes") as mock_search:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                session = CrawlerSession()
                await session.start()

                async def check_lock(*args, **kwargs):
                    nonlocal lock_acquired_during_search
                    # Try to acquire the lock immediately (should fail because search_notes holds it)
                    lock_acquired_during_search = session._lock.locked()
                    return []

                mock_search.side_effect = check_lock

                await session.search_notes("test")
                assert lock_acquired_during_search is True

    async def test_default_max_count_is_20(self):
        """The default max_count should be 20."""
        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=[])) as mock_search:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                session = CrawlerSession()
                await session.start()
                await session.search_notes("test")

                call_kwargs = mock_search.call_args[1]
                assert call_kwargs["max_count"] == 20


class TestCrawlerSessionSearchNotesRaceCondition:
    """Tests the second-guard path for race conditions in search_notes."""

    async def test_returns_error_when_bm_is_none_despite_running_flag(self):
        """Should return an error dict when _running=True but _bm=None (stop() race).

        Phase D: _ensure_browser() attempts automatic recovery, so BrowserManager must be mocked
        to make recovery fail too, verifying that a BROWSER_CRASHED error is returned in the end.
        """
        with patch("src.session.BrowserManager") as MockBM:
            # Recovery fails too
            mock_bm = AsyncMock()
            mock_bm.__aenter__ = AsyncMock(side_effect=RuntimeError("recovery failed"))
            mock_bm.__aexit__ = AsyncMock(return_value=None)
            MockBM.return_value = mock_bm

            session = CrawlerSession()
            session._running = True  # Bypass the fast path
            session._bm = None       # Simulate stop() having already set _bm to None

            result = await session.search_notes("test")

            assert isinstance(result, dict)
            assert result.get("error") is True
            assert result.get("code") == "BROWSER_CRASHED"


class TestCrawlerSessionGetNoteDetailRaceCondition:
    """Tests the second-guard path for race conditions in get_note_detail."""

    async def test_returns_error_when_bm_is_none_despite_running_flag(self):
        """Should return an error dict when _running=True but _bm=None (stop() race)."""
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = AsyncMock()
            mock_bm.__aenter__ = AsyncMock(side_effect=RuntimeError("recovery failed"))
            mock_bm.__aexit__ = AsyncMock(return_value=None)
            MockBM.return_value = mock_bm

            session = CrawlerSession()
            session._running = True
            session._bm = None

            result = await session.get_note_detail("https://www.rednote.com/explore/abc123")

            assert isinstance(result, dict)
            assert result.get("error") is True
            assert result.get("code") == "BROWSER_CRASHED"


class TestCrawlerSessionGetNoteDetail:
    """Tests for the CrawlerSession.get_note_detail() method."""

    async def test_returns_error_dict_when_not_running(self):
        """Should return a dict with error=True when the browser is not running, without raising."""
        session = CrawlerSession()
        result = await session.get_note_detail("https://www.rednote.com/explore/abc123")

        assert isinstance(result, dict)
        assert result.get("error") is True
        assert "message" in result

    async def test_calls_fetch_single_note_with_correct_args(self):
        """Should pass note_url and max_comments correctly to src.note.fetch_single_note."""
        mock_detail = {"note_id": "abc123", "title": "Test note", "comments": []}
        note_url = "https://www.rednote.com/explore/abc123?xsec_token=xyz"

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.note.fetch_single_note", new=AsyncMock(return_value=mock_detail)) as mock_fetch:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                session = CrawlerSession()
                await session.start()
                result = await session.get_note_detail(note_url, max_comments=5)

                mock_fetch.assert_called_once_with(mock_bm, note_url=note_url, max_comments=5)
                assert result == mock_detail

    async def test_returns_error_dict_when_fetch_returns_none(self):
        """When fetch_single_note returns None, it should be wrapped as an error dict rather than passing None through."""
        note_url = "https://www.rednote.com/explore/abc123"

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.note.fetch_single_note", new=AsyncMock(return_value=None)):
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                session = CrawlerSession()
                await session.start()
                result = await session.get_note_detail(note_url)

                assert isinstance(result, dict)
                assert result.get("error") is True
                assert "message" in result

    async def test_default_max_comments_is_20(self):
        """The default max_comments should be 20."""
        note_url = "https://www.rednote.com/explore/abc123"

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.note.fetch_single_note", new=AsyncMock(return_value={})) as mock_fetch:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                session = CrawlerSession()
                await session.start()
                await session.get_note_detail(note_url)

                call_kwargs = mock_fetch.call_args[1]
                assert call_kwargs["max_comments"] == 20

    async def test_uses_browser_lock_during_fetch(self):
        """The browser lock should be held while crawling a note."""
        lock_acquired = False
        note_url = "https://www.rednote.com/explore/abc123"

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.note.fetch_single_note") as mock_fetch:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                session = CrawlerSession()
                await session.start()

                async def check_lock(*args, **kwargs):
                    nonlocal lock_acquired
                    lock_acquired = session._lock.locked()
                    return {}

                mock_fetch.side_effect = check_lock
                await session.get_note_detail(note_url)
                assert lock_acquired is True

"""
MCP tool integration tests (Phase B)

Tests the full call chain: MCP tool handler → real CrawlerSession → underlying crawl modules

Differences from test_mcp_tools.py (unit tests):
  - _session is not mocked; a real CrawlerSession instance is used
  - Mocks sit at the BrowserManager and crawl module layer (src.search, src.note)
  - Covers: full call chain, session lifecycle, lifespan management, fallback paths when the session is not started
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mcp_server
from src.session import CrawlerSession


class TestMCPIntegrationSearchNotes:
    """Test the full call chain of the search_notes tool through a real CrawlerSession."""

    async def test_full_chain_returns_structured_result(self):
        """Full chain: mcp_server.search_notes → CrawlerSession.search_notes → src.search.search_notes."""
        mock_results = [{"note_id": "abc", "title": "Test note"}]
        real_session = CrawlerSession(headless=True)

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=mock_results)) as mock_search:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                await real_session.start()

                with patch.object(mcp_server, "_session", real_session):
                    result = await mcp_server.search_notes(keyword="Python")

                await real_session.stop()

        assert result["keyword"] == "Python"
        assert result["count"] == 1
        assert result["results"] == mock_results
        mock_search.assert_called_once_with(mock_bm, keyword="Python", max_count=20)

    async def test_full_chain_input_validation_before_session(self):
        """An empty keyword is rejected before the session is called; the session is not started."""
        real_session = CrawlerSession(headless=True)

        with patch.object(mcp_server, "_session", real_session):
            result = await mcp_server.search_notes(keyword="")

        assert result.get("error") is True
        assert real_session.is_running() is False  # session was never started

    async def test_full_chain_max_count_clamped_before_session(self):
        """max_count > 50 is clamped to 50 before reaching the session."""
        real_session = CrawlerSession(headless=True)

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=[])) as mock_search:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                await real_session.start()

                with patch.object(mcp_server, "_session", real_session):
                    await mcp_server.search_notes(keyword="test", max_count=200)

                await real_session.stop()

        call_kwargs = mock_search.call_args[1]
        assert call_kwargs["max_count"] == 50

    async def test_full_chain_keyword_stripped_before_session(self):
        """Leading/trailing whitespace is stripped from keyword before it reaches the session."""
        real_session = CrawlerSession(headless=True)

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=[])) as mock_search:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                await real_session.start()

                with patch.object(mcp_server, "_session", real_session):
                    await mcp_server.search_notes(keyword="  Python  ")

                await real_session.stop()

        call_kwargs = mock_search.call_args[1]
        assert call_kwargs["keyword"] == "Python"


class TestMCPIntegrationGetNoteDetail:
    """Test the full call chain of the get_note_detail tool through a real CrawlerSession."""

    async def test_full_chain_returns_note_detail(self):
        """Full chain: mcp_server.get_note_detail → CrawlerSession.get_note_detail → src.note.fetch_single_note."""
        mock_detail = {"note_id": "abc123", "title": "Test note", "comments": []}
        note_url = "https://www.rednote.com/explore/abc123?xsec_token=xyz"
        real_session = CrawlerSession(headless=True)

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.note.fetch_single_note", new=AsyncMock(return_value=mock_detail)) as mock_fetch:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                await real_session.start()

                with patch.object(mcp_server, "_session", real_session):
                    result = await mcp_server.get_note_detail(note_url=note_url)

                await real_session.stop()

        assert result == mock_detail
        mock_fetch.assert_called_once_with(mock_bm, note_url=note_url, max_comments=20)

    async def test_full_chain_fetch_returns_none_becomes_error_dict(self):
        """When the crawl module returns None, the MCP tool should return an error dict (not pass None through)."""
        note_url = "https://www.rednote.com/explore/invalid"
        real_session = CrawlerSession(headless=True)

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.note.fetch_single_note", new=AsyncMock(return_value=None)):
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                await real_session.start()

                with patch.object(mcp_server, "_session", real_session):
                    result = await mcp_server.get_note_detail(note_url=note_url)

                await real_session.stop()

        assert isinstance(result, dict)
        assert result.get("error") is True
        assert "message" in result

    async def test_full_chain_max_comments_clamped_before_session(self):
        """max_comments > 50 is clamped to 50 before reaching the session."""
        note_url = "https://www.rednote.com/explore/abc123"
        real_session = CrawlerSession(headless=True)

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.note.fetch_single_note", new=AsyncMock(return_value={})) as mock_fetch:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                await real_session.start()

                with patch.object(mcp_server, "_session", real_session):
                    await mcp_server.get_note_detail(note_url=note_url, max_comments=100)

                await real_session.stop()

        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["max_comments"] == 50

    async def test_full_chain_max_comments_clamped_below_zero(self):
        """max_comments < 0 is clamped to 0 before reaching the session."""
        note_url = "https://www.rednote.com/explore/abc123"
        real_session = CrawlerSession(headless=True)

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.note.fetch_single_note", new=AsyncMock(return_value={})) as mock_fetch:
                mock_bm = AsyncMock()
                MockBM.return_value = mock_bm
                mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
                mock_bm.__aexit__ = AsyncMock(return_value=None)

                await real_session.start()

                with patch.object(mcp_server, "_session", real_session):
                    await mcp_server.get_note_detail(note_url=note_url, max_comments=-5)

                await real_session.stop()

        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["max_comments"] == 0


class TestMCPIntegrationLifespan:
    """Test the lifespan hook's integration with a real CrawlerSession."""

    async def test_lifespan_starts_and_stops_real_session(self):
        """lifespan should start and stop a real CrawlerSession (not a mock)."""
        real_session = CrawlerSession(headless=True)

        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = AsyncMock()
            MockBM.return_value = mock_bm
            mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
            mock_bm.__aexit__ = AsyncMock(return_value=None)

            with patch.object(mcp_server, "_session", real_session):
                assert real_session.is_running() is False

                async with mcp_server.lifespan(MagicMock()):
                    assert real_session.is_running() is True

                assert real_session.is_running() is False

    async def test_lifespan_cleans_up_bm_on_exception(self):
        """When an exception is raised inside lifespan, the session's internal state should be fully cleaned up."""
        real_session = CrawlerSession(headless=True)

        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = AsyncMock()
            MockBM.return_value = mock_bm
            mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
            mock_bm.__aexit__ = AsyncMock(return_value=None)

            with patch.object(mcp_server, "_session", real_session):
                try:
                    async with mcp_server.lifespan(MagicMock()):
                        raise RuntimeError("simulated server crash")
                except RuntimeError:
                    pass

                assert real_session.is_running() is False
                assert real_session._bm is None
                assert real_session._exit_stack is None


class TestMCPIntegrationSessionNotRunning:
    """Test the MCP tools' fallback paths when the session is not running (not started via lifespan)."""

    async def test_search_notes_without_lifespan_returns_error(self):
        """When not started via lifespan, search_notes should gracefully return an error dict rather than crash."""
        real_session = CrawlerSession(headless=True)
        assert real_session.is_running() is False

        with patch.object(mcp_server, "_session", real_session):
            result = await mcp_server.search_notes(keyword="test")

        assert result.get("error") is True
        assert "message" in result

    async def test_get_note_detail_without_lifespan_returns_error(self):
        """When not started via lifespan, get_note_detail should gracefully return an error dict rather than crash."""
        real_session = CrawlerSession(headless=True)

        with patch.object(mcp_server, "_session", real_session):
            result = await mcp_server.get_note_detail(
                note_url="https://www.rednote.com/explore/abc123"
            )

        assert result.get("error") is True
        assert "message" in result

    async def test_check_login_status_without_lifespan_returns_not_running(self):
        """When not started via lifespan, check_login_status should return browser_running=False."""
        real_session = CrawlerSession(headless=True)

        with patch.object(mcp_server, "_session", real_session):
            result = await mcp_server.check_login_status()

        assert result["browser_running"] is False
        assert result["logged_in"] is False

    async def test_search_notes_not_running_returns_structured_error(self):
        """A structured error should be returned when the browser is not running (Phase D: includes code/action)."""
        real_session = CrawlerSession(headless=True)

        with patch.object(mcp_server, "_session", real_session):
            result = await mcp_server.search_notes(keyword="test")

        assert result.get("error") is True
        assert result.get("code") == "BROWSER_NOT_RUNNING"
        assert "action" in result

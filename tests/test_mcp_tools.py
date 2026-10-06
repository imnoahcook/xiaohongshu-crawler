"""
MCP tool handler tests (Phase A + Phase B)

Tests the check_login_status / search_notes / get_note_detail MCP tools and the lifespan hook

Test strategy:
  - Replace the module-level _session with a mock via patch.object
  - Call the tool functions directly and verify argument passing and return value format
  - Covers: happy path, input validation, boundary clamping, handling of a None session result
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mcp_server


class TestCheckLoginStatusTool:
    """Test the check_login_status MCP tool (Phase A)."""

    async def test_returns_session_result(self):
        """The session.check_login_status() result should be returned to the caller as-is."""
        mock_result = {"logged_in": True, "browser_running": True, "message": "Logged in"}
        mock_session = AsyncMock()
        mock_session.check_login_status = AsyncMock(return_value=mock_result)

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.check_login_status()

        mock_session.check_login_status.assert_called_once()
        assert result == mock_result

    async def test_returns_not_logged_in_response(self):
        """When not logged in, the status dict returned by the session should be passed through."""
        mock_result = {
            "logged_in": False,
            "browser_running": True,
            "message": "Not logged in, please scan the QR code",
        }
        mock_session = AsyncMock()
        mock_session.check_login_status = AsyncMock(return_value=mock_result)

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.check_login_status()

        assert result["logged_in"] is False


class TestLifespan:
    """Test the lifespan startup/shutdown hook."""

    async def test_lifespan_starts_and_stops_session(self):
        """Entering lifespan should start the session; exiting should stop it."""
        mock_session = AsyncMock()
        mock_session.start = AsyncMock()
        mock_session.stop = AsyncMock()

        with patch.object(mcp_server, "_session", mock_session):
            async with mcp_server.lifespan(MagicMock()):
                mock_session.start.assert_called_once()
                mock_session.stop.assert_not_called()

        mock_session.stop.assert_called_once()

    async def test_lifespan_stops_session_on_exception(self):
        """Even if an exception is raised inside the yield, lifespan's finally should ensure stop() is called."""
        mock_session = AsyncMock()
        mock_session.start = AsyncMock()
        mock_session.stop = AsyncMock()

        with patch.object(mcp_server, "_session", mock_session):
            try:
                async with mcp_server.lifespan(MagicMock()):
                    raise RuntimeError("simulated server crash")
            except RuntimeError:
                pass

        mock_session.stop.assert_called_once()


class TestSearchNotesTool:
    """Test the search_notes MCP tool."""

    async def test_returns_results_from_session(self):
        """A normal call should return the session result; max_count defaults to 20."""
        mock_result = {
            "keyword": "test",
            "count": 2,
            "results": [{"note_id": "1"}, {"note_id": "2"}],
        }
        mock_session = AsyncMock()
        mock_session.search_notes = AsyncMock(return_value=mock_result)

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.search_notes(keyword="test")

        mock_session.search_notes.assert_called_once_with(keyword="test", max_count=20)
        assert result == mock_result

    async def test_clamps_max_count_above_50(self):
        """max_count > 50 should be clamped to 50."""
        mock_session = AsyncMock()
        mock_session.search_notes = AsyncMock(return_value={"keyword": "k", "count": 0, "results": []})

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.search_notes(keyword="test", max_count=100)

        call_kwargs = mock_session.search_notes.call_args[1]
        assert call_kwargs["max_count"] == 50

    async def test_clamps_max_count_below_1(self):
        """max_count < 1 should be clamped to 1."""
        mock_session = AsyncMock()
        mock_session.search_notes = AsyncMock(return_value={"keyword": "k", "count": 0, "results": []})

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.search_notes(keyword="test", max_count=0)

        call_kwargs = mock_session.search_notes.call_args[1]
        assert call_kwargs["max_count"] == 1

    async def test_returns_error_for_empty_keyword(self):
        """An empty keyword should return an error immediately without calling the session."""
        mock_session = AsyncMock()

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.search_notes(keyword="")

        assert result.get("error") is True
        mock_session.search_notes.assert_not_called()

    async def test_returns_error_for_whitespace_only_keyword(self):
        """A whitespace-only keyword should be treated as empty and return an error."""
        mock_session = AsyncMock()

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.search_notes(keyword="   ")

        assert result.get("error") is True
        mock_session.search_notes.assert_not_called()

    async def test_strips_keyword_before_calling_session(self):
        """Leading/trailing whitespace should be stripped from keyword before it is passed to the session."""
        mock_session = AsyncMock()
        mock_session.search_notes = AsyncMock(return_value={"keyword": "test", "count": 0, "results": []})

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.search_notes(keyword="  test  ")

        call_kwargs = mock_session.search_notes.call_args[1]
        assert call_kwargs["keyword"] == "test"

    async def test_valid_max_count_at_boundary(self):
        """Boundary values max_count=1 and max_count=50 should be left unchanged."""
        mock_session = AsyncMock()
        mock_session.search_notes = AsyncMock(return_value={"keyword": "k", "count": 0, "results": []})

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.search_notes(keyword="test", max_count=1)
        assert mock_session.search_notes.call_args[1]["max_count"] == 1

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.search_notes(keyword="test", max_count=50)
        assert mock_session.search_notes.call_args[1]["max_count"] == 50


class TestGetNoteDetailTool:
    """Test the get_note_detail MCP tool."""

    async def test_returns_detail_from_session(self):
        """A normal call should return the session result; max_comments defaults to 20."""
        mock_detail = {"note_id": "abc123", "title": "Test note", "comments": []}
        mock_session = AsyncMock()
        mock_session.get_note_detail = AsyncMock(return_value=mock_detail)
        note_url = "https://www.rednote.com/explore/abc123"

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.get_note_detail(note_url=note_url)

        mock_session.get_note_detail.assert_called_once_with(note_url=note_url, max_comments=20)
        assert result == mock_detail

    async def test_returns_error_when_session_returns_none(self):
        """When the session returns None, a dict with error=True should be returned."""
        mock_session = AsyncMock()
        mock_session.get_note_detail = AsyncMock(return_value=None)
        note_url = "https://www.rednote.com/explore/abc123"

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.get_note_detail(note_url=note_url)

        assert result.get("error") is True
        assert "message" in result

    async def test_clamps_max_comments_above_50(self):
        """max_comments > 50 should be clamped to 50."""
        mock_session = AsyncMock()
        mock_session.get_note_detail = AsyncMock(return_value={"note_id": "x"})
        note_url = "https://www.rednote.com/explore/abc123"

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.get_note_detail(note_url=note_url, max_comments=100)

        call_kwargs = mock_session.get_note_detail.call_args[1]
        assert call_kwargs["max_comments"] == 50

    async def test_clamps_max_comments_below_0(self):
        """max_comments < 0 should be clamped to 0."""
        mock_session = AsyncMock()
        mock_session.get_note_detail = AsyncMock(return_value={"note_id": "x"})
        note_url = "https://www.rednote.com/explore/abc123"

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.get_note_detail(note_url=note_url, max_comments=-5)

        call_kwargs = mock_session.get_note_detail.call_args[1]
        assert call_kwargs["max_comments"] == 0

    async def test_returns_error_for_empty_url(self):
        """An empty note_url should return an error immediately without calling the session."""
        mock_session = AsyncMock()

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.get_note_detail(note_url="")

        assert result.get("error") is True
        mock_session.get_note_detail.assert_not_called()

    async def test_valid_max_comments_at_boundaries(self):
        """Boundary values max_comments=0 and max_comments=50 should be left unchanged."""
        mock_session = AsyncMock()
        mock_session.get_note_detail = AsyncMock(return_value={"note_id": "x"})
        note_url = "https://www.rednote.com/explore/abc123"

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.get_note_detail(note_url=note_url, max_comments=0)
        assert mock_session.get_note_detail.call_args[1]["max_comments"] == 0

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.get_note_detail(note_url=note_url, max_comments=50)
        assert mock_session.get_note_detail.call_args[1]["max_comments"] == 50

    async def test_error_response_contains_note_url(self):
        """The error response should include the original note_url to aid debugging."""
        mock_session = AsyncMock()
        mock_session.get_note_detail = AsyncMock(return_value=None)
        note_url = "https://www.rednote.com/explore/abc123"

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.get_note_detail(note_url=note_url)

        assert note_url in result.get("message", "")

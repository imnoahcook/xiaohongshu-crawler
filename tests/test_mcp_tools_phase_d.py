"""
MCP tool Phase D tests — timeouts + log file output + structured error propagation

Test strategy:
  - D4: verify each tool's asyncio.wait_for timeout behavior
  - D5: verify the log file output configuration
  - Structured errors: verify the MCP layer correctly propagates structured errors from the session layer
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import mcp_server


class TestToolTimeouts:
    """D4: tool timeouts."""

    async def test_search_notes_timeout_returns_structured_error(self):
        """A search_notes timeout should return a structured TIMEOUT error."""
        # Simulate session.search_notes never returning
        async def slow_search(*args, **kwargs):
            await asyncio.sleep(999)

        mock_session = AsyncMock()
        mock_session.search_notes = slow_search

        with patch.object(mcp_server, "_session", mock_session):
            # Temporarily set a very short timeout to speed up the test
            with patch.object(mcp_server, "TOOL_TIMEOUTS", {"search_notes": 0.01, "get_note_detail": 0.01, "crawl_keyword": 0.01}):
                result = await mcp_server.search_notes(keyword="test")

        assert result["error"] is True
        assert result["code"] == "TIMEOUT"
        assert "search_notes" in result["message"]

    async def test_get_note_detail_timeout_returns_structured_error(self):
        """A get_note_detail timeout should return a structured TIMEOUT error."""
        async def slow_detail(*args, **kwargs):
            await asyncio.sleep(999)

        mock_session = AsyncMock()
        mock_session.get_note_detail = slow_detail

        with patch.object(mcp_server, "_session", mock_session):
            with patch.object(mcp_server, "TOOL_TIMEOUTS", {"search_notes": 0.01, "get_note_detail": 0.01, "crawl_keyword": 0.01}):
                result = await mcp_server.get_note_detail(
                    note_url="https://www.rednote.com/explore/abc123"
                )

        assert result["error"] is True
        assert result["code"] == "TIMEOUT"
        assert "get_note_detail" in result["message"]

    async def test_crawl_keyword_timeout_returns_structured_error(self):
        """A crawl_keyword timeout should return a structured TIMEOUT error."""
        async def slow_crawl(*args, **kwargs):
            await asyncio.sleep(999)

        mock_session = AsyncMock()
        mock_session.crawl_keyword = slow_crawl

        with patch.object(mcp_server, "_session", mock_session):
            with patch.object(mcp_server, "TOOL_TIMEOUTS", {"search_notes": 0.01, "get_note_detail": 0.01, "crawl_keyword": 0.01}):
                result = await mcp_server.crawl_keyword(keyword="test")

        assert result["error"] is True
        assert result["code"] == "TIMEOUT"
        assert "crawl_keyword" in result["message"]

    async def test_search_notes_normal_within_timeout(self):
        """A normal return (no timeout) is unaffected by the timeout wrapper."""
        mock_result = {"keyword": "ok", "count": 1, "results": [{"note_id": "1"}]}
        mock_session = AsyncMock()
        mock_session.search_notes = AsyncMock(return_value=mock_result)

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.search_notes(keyword="ok")

        assert result == mock_result

    async def test_timeout_values_match_spec(self):
        """Timeout values should match the PLAN spec: search 120s / detail 90s / crawl 600s."""
        assert mcp_server.TOOL_TIMEOUTS["search_notes"] == 120
        assert mcp_server.TOOL_TIMEOUTS["get_note_detail"] == 90
        assert mcp_server.TOOL_TIMEOUTS["crawl_keyword"] == 600


class TestStructuredErrorPassthrough:
    """Verify the MCP tool layer correctly propagates structured errors from the session layer."""

    async def test_search_passes_through_session_error_with_code(self):
        """An error with a code returned by the session should be passed through by the MCP tool layer."""
        mock_error = {
            "error": True,
            "code": "LOGIN_EXPIRED",
            "message": "Login expired",
            "action": "Please log in again",
        }
        mock_session = AsyncMock()
        mock_session.search_notes = AsyncMock(return_value=mock_error)

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.search_notes(keyword="test")

        assert result["code"] == "LOGIN_EXPIRED"

    async def test_get_note_detail_passes_through_crawl_failed(self):
        """A CRAWL_FAILED returned by the session should be passed through."""
        mock_error = {
            "error": True,
            "code": "CRAWL_FAILED",
            "message": "Crawl failed",
            "action": "Please check the URL",
        }
        mock_session = AsyncMock()
        mock_session.get_note_detail = AsyncMock(return_value=mock_error)

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.get_note_detail(
                note_url="https://www.rednote.com/explore/abc123"
            )

        assert result["code"] == "CRAWL_FAILED"


class TestFileLogging:
    """D5: log file output configuration."""

    def test_setup_file_logging_creates_handler(self):
        """setup_file_logging should add a RotatingFileHandler to the root logger."""
        from logging.handlers import RotatingFileHandler

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            mcp_server.setup_file_logging(log_dir=log_dir)

            root_logger = logging.getLogger()
            # Find the file handler we added
            file_handlers = [
                h for h in root_logger.handlers
                if isinstance(h, RotatingFileHandler)
            ]
            assert len(file_handlers) >= 1

            # Verify the log file was created
            log_files = list(log_dir.glob("*.log"))
            assert len(log_files) >= 1

            # Cleanup: remove the handler we added
            for h in file_handlers:
                root_logger.removeHandler(h)
                h.close()

    def test_setup_file_logging_creates_log_directory(self):
        """setup_file_logging should create the log directory automatically."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "nested" / "logs"
            assert not log_dir.exists()

            mcp_server.setup_file_logging(log_dir=log_dir)

            assert log_dir.exists()

            # Cleanup
            from logging.handlers import RotatingFileHandler
            root_logger = logging.getLogger()
            for h in list(root_logger.handlers):
                if isinstance(h, RotatingFileHandler):
                    root_logger.removeHandler(h)
                    h.close()

    def test_log_message_appears_in_file(self):
        """Logged messages should appear in the file."""
        from logging.handlers import RotatingFileHandler

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            mcp_server.setup_file_logging(log_dir=log_dir)

            # Write via the root logger directly to avoid child logger propagation issues
            root_logger = logging.getLogger()
            root_logger.info("test log write verification")

            # Force a flush
            file_handlers = [
                h for h in root_logger.handlers
                if isinstance(h, RotatingFileHandler)
            ]
            for h in file_handlers:
                h.flush()

            log_file = log_dir / "mcp_server.log"
            content = log_file.read_text(encoding="utf-8")
            assert "test log write verification" in content

            # Cleanup
            for h in file_handlers:
                root_logger.removeHandler(h)
                h.close()

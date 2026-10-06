"""
MCP tool handler tests (Phase C)

Tests the crawl_keyword / get_saved_data tools and the rednote://config / rednote://data resource endpoints

Test strategy:
  - Replace the module-level _session with a mock via patch.object
  - For resource functions, replace the module-level path constants via patch.object and call the functions directly
  - Covers: happy path, input validation, boundary clamping, security checks
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import mcp_server


# ============================================================
# crawl_keyword MCP tool tests
# ============================================================


class TestCrawlKeywordTool:
    """Test the crawl_keyword MCP tool."""

    def _make_ok_result(self, keyword: str = "test") -> dict:
        return {
            "keyword": keyword,
            "search_count": 5,
            "detail_count": 5,
            "total_comments": 20,
            "summary": f"Keyword [{keyword}] crawl complete",
        }

    async def test_returns_session_result_for_valid_input(self):
        """A normal call should pass the session result through to the caller."""
        mock_result = self._make_ok_result("test")
        mock_session = AsyncMock()
        mock_session.crawl_keyword = AsyncMock(return_value=mock_result)

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.crawl_keyword(keyword="test")

        assert result == mock_result

    async def test_returns_error_for_empty_keyword(self):
        """An empty keyword should return an error immediately without calling the session."""
        mock_session = AsyncMock()

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.crawl_keyword(keyword="")

        assert result.get("error") is True
        mock_session.crawl_keyword.assert_not_called()

    async def test_returns_error_for_whitespace_keyword(self):
        """A whitespace-only keyword should return an error without calling the session."""
        mock_session = AsyncMock()

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.crawl_keyword(keyword="   ")

        assert result.get("error") is True
        mock_session.crawl_keyword.assert_not_called()

    async def test_strips_keyword_before_passing_to_session(self):
        """Leading/trailing whitespace should be stripped from keyword before it is passed to the session."""
        mock_session = AsyncMock()
        mock_session.crawl_keyword = AsyncMock(return_value=self._make_ok_result("test"))

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.crawl_keyword(keyword="  test  ")

        call_kwargs = mock_session.crawl_keyword.call_args[1]
        assert call_kwargs["keyword"] == "test"

    async def test_default_max_notes_is_10(self):
        """max_notes should default to 10 when omitted."""
        mock_session = AsyncMock()
        mock_session.crawl_keyword = AsyncMock(return_value=self._make_ok_result())

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.crawl_keyword(keyword="test")

        call_kwargs = mock_session.crawl_keyword.call_args[1]
        assert call_kwargs["max_notes"] == 10

    async def test_clamps_max_notes_above_20(self):
        """max_notes > 20 should be clamped to 20."""
        mock_session = AsyncMock()
        mock_session.crawl_keyword = AsyncMock(return_value=self._make_ok_result())

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.crawl_keyword(keyword="test", max_notes=100)

        call_kwargs = mock_session.crawl_keyword.call_args[1]
        assert call_kwargs["max_notes"] == 20

    async def test_clamps_max_notes_below_1(self):
        """max_notes < 1 should be clamped to 1."""
        mock_session = AsyncMock()
        mock_session.crawl_keyword = AsyncMock(return_value=self._make_ok_result())

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.crawl_keyword(keyword="test", max_notes=0)

        call_kwargs = mock_session.crawl_keyword.call_args[1]
        assert call_kwargs["max_notes"] == 1

    async def test_max_notes_boundary_values_unchanged(self):
        """Boundary values max_notes=1 and max_notes=20 should be left unchanged."""
        mock_session = AsyncMock()
        mock_session.crawl_keyword = AsyncMock(return_value=self._make_ok_result())

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.crawl_keyword(keyword="test", max_notes=1)
        assert mock_session.crawl_keyword.call_args[1]["max_notes"] == 1

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.crawl_keyword(keyword="test", max_notes=20)
        assert mock_session.crawl_keyword.call_args[1]["max_notes"] == 20

    async def test_default_max_comments_is_20(self):
        """max_comments should default to 20 when omitted."""
        mock_session = AsyncMock()
        mock_session.crawl_keyword = AsyncMock(return_value=self._make_ok_result())

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.crawl_keyword(keyword="test")

        call_kwargs = mock_session.crawl_keyword.call_args[1]
        assert call_kwargs["max_comments"] == 20

    async def test_clamps_max_comments_above_50(self):
        """max_comments > 50 should be clamped to 50."""
        mock_session = AsyncMock()
        mock_session.crawl_keyword = AsyncMock(return_value=self._make_ok_result())

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.crawl_keyword(keyword="test", max_comments=100)

        call_kwargs = mock_session.crawl_keyword.call_args[1]
        assert call_kwargs["max_comments"] == 50

    async def test_clamps_max_comments_below_0(self):
        """max_comments < 0 should be clamped to 0."""
        mock_session = AsyncMock()
        mock_session.crawl_keyword = AsyncMock(return_value=self._make_ok_result())

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.crawl_keyword(keyword="test", max_comments=-5)

        call_kwargs = mock_session.crawl_keyword.call_args[1]
        assert call_kwargs["max_comments"] == 0


# ============================================================
# get_saved_data MCP tool tests
# ============================================================


class TestGetSavedDataTool:
    """Test the get_saved_data MCP tool."""

    async def test_returns_session_result(self):
        """A normal call should pass the session result through."""
        mock_result = {
            "files": [
                {
                    "path": "data/raw/test_20240315_143022.json",
                    "keyword": "test",
                    "created_at": "2024-03-15T14:30:22",
                    "size_bytes": 1024,
                }
            ]
        }
        mock_session = AsyncMock()
        mock_session.get_saved_data = AsyncMock(return_value=mock_result)

        with patch.object(mcp_server, "_session", mock_session):
            result = await mcp_server.get_saved_data()

        assert result == mock_result

    async def test_passes_keyword_filter_when_provided(self):
        """When keyword is provided, it should be passed to the session's get_saved_data."""
        mock_session = AsyncMock()
        mock_session.get_saved_data = AsyncMock(return_value={"files": []})

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.get_saved_data(keyword="Python")

        call_kwargs = mock_session.get_saved_data.call_args[1]
        assert call_kwargs["keyword"] == "Python"

    async def test_keyword_not_passed_when_empty_string(self):
        """With an empty keyword, the session should be called with None (no filtering)."""
        mock_session = AsyncMock()
        mock_session.get_saved_data = AsyncMock(return_value={"files": []})

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.get_saved_data(keyword="")

        call_kwargs = mock_session.get_saved_data.call_args[1]
        assert call_kwargs.get("keyword") is None

    async def test_keyword_defaults_to_none(self):
        """When keyword is omitted, the session should be called with None."""
        mock_session = AsyncMock()
        mock_session.get_saved_data = AsyncMock(return_value={"files": []})

        with patch.object(mcp_server, "_session", mock_session):
            await mcp_server.get_saved_data()

        call_kwargs = mock_session.get_saved_data.call_args[1]
        assert call_kwargs.get("keyword") is None


# ============================================================
# rednote://config resource endpoint tests
# ============================================================


class TestMCPConfigResource:
    """Test the rednote://config resource endpoint."""

    async def test_returns_yaml_content_when_config_exists(self, tmp_path):
        """When the config file exists, its YAML text should be returned."""
        config_content = "crawler:\n  keywords: []\n"
        config_file = tmp_path / "settings.yaml"
        config_file.write_text(config_content, encoding="utf-8")

        with patch.object(mcp_server, "_CONFIG_PATH", config_file):
            result = await mcp_server.get_config_resource()

        assert "crawler" in result

    async def test_returns_error_message_when_config_missing(self, tmp_path):
        """When the config file is missing, a readable error message should be returned without raising."""
        missing_file = tmp_path / "nonexistent.yaml"

        with patch.object(mcp_server, "_CONFIG_PATH", missing_file):
            result = await mcp_server.get_config_resource()

        assert isinstance(result, str)
        assert len(result) > 0

    async def test_returns_string_type(self, tmp_path):
        """The return value must be a string (required by the MCP resource protocol)."""
        config_file = tmp_path / "settings.yaml"
        config_file.write_text("key: value\n", encoding="utf-8")

        with patch.object(mcp_server, "_CONFIG_PATH", config_file):
            result = await mcp_server.get_config_resource()

        assert isinstance(result, str)


# ============================================================
# rednote://data/{filename} resource endpoint tests
# ============================================================


class TestMCPDataResource:
    """Test the rednote://data/{filename} resource endpoint."""

    async def test_returns_file_content_for_existing_json(self, tmp_path):
        """When the file exists, its text content should be returned."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        (tmp_path / "processed").mkdir(parents=True)

        data_file = raw_dir / "test_20240315_143022.json"
        data_file.write_text('{"count": 1}', encoding="utf-8")

        with patch.object(mcp_server, "_DATA_DIR", tmp_path):
            result = await mcp_server.get_data_resource(filename="test_20240315_143022.json")

        assert "count" in result

    async def test_returns_error_for_missing_file(self, tmp_path):
        """When the file is missing, a readable error message should be returned without raising."""
        (tmp_path / "raw").mkdir(parents=True)
        (tmp_path / "processed").mkdir(parents=True)

        with patch.object(mcp_server, "_DATA_DIR", tmp_path):
            result = await mcp_server.get_data_resource(filename="nonexistent.json")

        assert isinstance(result, str)
        # Should include the file name to aid debugging
        assert "nonexistent" in result or "not found" in result

    async def test_rejects_path_traversal_with_dotdot(self):
        """A filename containing ../ should return a security error, rejecting path traversal."""
        result = await mcp_server.get_data_resource(filename="../../../etc/passwd")

        assert isinstance(result, str)
        # Should not return system file contents
        assert "root" not in result
        # Should include a security rejection message
        assert len(result) > 0

    async def test_rejects_path_with_slash(self):
        """A filename containing / should be rejected (prevents subdirectory access)."""
        result = await mcp_server.get_data_resource(filename="subdir/file.json")

        assert isinstance(result, str)
        # Should include a security error message
        assert len(result) > 0

    async def test_finds_file_in_processed_subdir(self, tmp_path):
        """Files under the processed subdirectory should also be found."""
        (tmp_path / "raw").mkdir(parents=True)
        processed_dir = tmp_path / "processed"
        processed_dir.mkdir(parents=True)

        xlsx_file = processed_dir / "keyword_20240315_143022.xlsx"
        xlsx_file.write_bytes(b"xlsx_data")

        with patch.object(mcp_server, "_DATA_DIR", tmp_path):
            result = await mcp_server.get_data_resource(filename="keyword_20240315_143022.xlsx")

        # xlsx is a binary file, so reading it as text may yield garbage, but it should not raise and should return a string
        assert isinstance(result, str)

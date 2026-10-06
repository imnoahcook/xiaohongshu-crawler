"""
Tests for CrawlerSession Phase C methods

Tests the crawl_keyword and get_saved_data methods

Test strategy:
  - BrowserManager and the src modules are mocked; no real browser is needed
  - get_saved_data uses the tmp_path fixture to test filesystem operations
  - Covers: the normal path, browser-not-running errors, argument bounds, race conditions
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.session import CrawlerSession


def _make_mock_bm():
    """Create a mock BrowserManager that supports the async with protocol."""
    mock_bm = AsyncMock()
    mock_bm.__aenter__ = AsyncMock(return_value=mock_bm)
    mock_bm.__aexit__ = AsyncMock(return_value=None)
    return mock_bm


# ============================================================
# Tests for CrawlerSession.crawl_keyword()
# ============================================================


class TestCrawlerSessionCrawlKeyword:
    """Tests for the CrawlerSession.crawl_keyword() method."""

    async def test_returns_error_when_not_running(self):
        """Should return a dict with error=True when the browser is not running, without raising."""
        session = CrawlerSession()
        result = await session.crawl_keyword("test")

        assert isinstance(result, dict)
        assert result.get("error") is True
        assert "message" in result

    async def test_calls_search_and_fetch_details(self):
        """Should call search_notes and fetch_note_details in order, passing arguments correctly."""
        mock_search_results = [
            {"note_id": "1", "title": "Note one", "note_url": "https://example.com/1"},
        ]
        mock_note_details = [
            {"note_id": "1", "title": "Note one", "comments": []},
        ]

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=mock_search_results)) as mock_search:
                with patch("src.note.fetch_note_details", new=AsyncMock(return_value=mock_note_details)) as mock_fetch:
                    with patch("src.session.Storage") as MockStorage:
                        mock_bm = _make_mock_bm()
                        MockBM.return_value = mock_bm
                        MockStorage.return_value = MagicMock()

                        session = CrawlerSession()
                        await session.start()
                        await session.crawl_keyword("test-keyword", max_notes=1, max_comments=5)

                        mock_search.assert_called_once()
                        assert mock_search.call_args[1]["keyword"] == "test-keyword"
                        assert mock_search.call_args[1]["max_count"] == 1
                        mock_fetch.assert_called_once()
                        assert mock_fetch.call_args[1]["max_comments"] == 5

    async def test_returns_structured_result(self):
        """The return value should contain the keys keyword/search_count/detail_count/total_comments/summary."""
        mock_search_results = [{"note_id": "1"}, {"note_id": "2"}]
        mock_note_details = [
            {"note_id": "1", "comments": [{"id": "c1"}, {"id": "c2"}]},
            {"note_id": "2", "comments": [{"id": "c3"}]},
        ]

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=mock_search_results)):
                with patch("src.note.fetch_note_details", new=AsyncMock(return_value=mock_note_details)):
                    with patch("src.session.Storage") as MockStorage:
                        mock_bm = _make_mock_bm()
                        MockBM.return_value = mock_bm
                        MockStorage.return_value = MagicMock()

                        session = CrawlerSession()
                        await session.start()
                        result = await session.crawl_keyword("test")

                        assert result["keyword"] == "test"
                        assert result["search_count"] == 2
                        assert result["detail_count"] == 2
                        assert result["total_comments"] == 3
                        assert "summary" in result

    async def test_limits_max_notes_to_20(self):
        """When max_notes exceeds 20, the max_count passed to search_notes should be capped at 20."""
        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=[])) as mock_search:
                with patch("src.note.fetch_note_details", new=AsyncMock(return_value=[])):
                    with patch("src.session.Storage") as MockStorage:
                        mock_bm = _make_mock_bm()
                        MockBM.return_value = mock_bm
                        MockStorage.return_value = MagicMock()

                        session = CrawlerSession()
                        await session.start()
                        await session.crawl_keyword("test", max_notes=50)

                        call_kwargs = mock_search.call_args[1]
                        assert call_kwargs["max_count"] == 20

    async def test_handles_empty_search_results(self):
        """With no search results, should return a valid empty structure (not an error) without crashing."""
        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=[])):
                with patch("src.note.fetch_note_details", new=AsyncMock(return_value=[])):
                    with patch("src.session.Storage") as MockStorage:
                        mock_bm = _make_mock_bm()
                        MockBM.return_value = mock_bm
                        MockStorage.return_value = MagicMock()

                        session = CrawlerSession()
                        await session.start()
                        result = await session.crawl_keyword("no-results-keyword")

                        assert result.get("error") is not True
                        assert result["search_count"] == 0
                        assert result["detail_count"] == 0
                        assert result["total_comments"] == 0

    async def test_saves_data_via_storage(self):
        """Should call Storage.save_all to persist data, with the keyword + two lists as arguments."""
        mock_search_results = [{"note_id": "1"}]
        mock_note_details = [{"note_id": "1", "comments": []}]

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=mock_search_results)):
                with patch("src.note.fetch_note_details", new=AsyncMock(return_value=mock_note_details)):
                    with patch("src.session.Storage") as MockStorage:
                        mock_bm = _make_mock_bm()
                        MockBM.return_value = mock_bm
                        mock_storage = MagicMock()
                        MockStorage.return_value = mock_storage

                        session = CrawlerSession()
                        await session.start()
                        await session.crawl_keyword("save-test")

                        mock_storage.save_all.assert_called_once_with(
                            "save-test", mock_search_results, mock_note_details
                        )

    async def test_uses_browser_lock_during_crawl(self):
        """The browser lock should be held during the crawl (guarantees serialization)."""
        lock_acquired = False

        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes") as mock_search:
                with patch("src.note.fetch_note_details", new=AsyncMock(return_value=[])):
                    with patch("src.session.Storage") as MockStorage:
                        mock_bm = _make_mock_bm()
                        MockBM.return_value = mock_bm
                        MockStorage.return_value = MagicMock()

                        session = CrawlerSession()
                        await session.start()

                        async def check_lock(*args, **kwargs):
                            nonlocal lock_acquired
                            lock_acquired = session._lock.locked()
                            return []

                        mock_search.side_effect = check_lock
                        await session.crawl_keyword("lock_test")

                        assert lock_acquired is True

    async def test_returns_error_when_bm_none_race_condition(self):
        """Should return an error dict when _running=True but _bm=None (race).

        Phase D: _ensure_browser() attempts automatic recovery; the mock makes recovery fail.
        """
        with patch("src.session.BrowserManager") as MockBM:
            mock_bm = AsyncMock()
            mock_bm.__aenter__ = AsyncMock(side_effect=RuntimeError("recovery failed"))
            mock_bm.__aexit__ = AsyncMock(return_value=None)
            MockBM.return_value = mock_bm

            session = CrawlerSession()
            session._running = True
            session._bm = None

            result = await session.crawl_keyword("test")

            assert isinstance(result, dict)
            assert result.get("error") is True
            assert result.get("code") == "BROWSER_CRASHED"

    async def test_default_max_notes_is_10(self):
        """The default max_notes should be 10."""
        with patch("src.session.BrowserManager") as MockBM:
            with patch("src.search.search_notes", new=AsyncMock(return_value=[])) as mock_search:
                with patch("src.note.fetch_note_details", new=AsyncMock(return_value=[])):
                    with patch("src.session.Storage") as MockStorage:
                        mock_bm = _make_mock_bm()
                        MockBM.return_value = mock_bm
                        MockStorage.return_value = MagicMock()

                        session = CrawlerSession()
                        await session.start()
                        await session.crawl_keyword("test")

                        call_kwargs = mock_search.call_args[1]
                        assert call_kwargs["max_count"] == 10


# ============================================================
# Tests for CrawlerSession.get_saved_data()
# ============================================================


class TestCrawlerSessionGetSavedData:
    """Tests for the CrawlerSession.get_saved_data() method."""

    async def test_returns_empty_when_data_dir_not_exists(self, tmp_path):
        """Should return an empty file list when the data directory does not exist, without raising."""
        session = CrawlerSession()
        result = await session.get_saved_data(data_dir=tmp_path / "nonexistent")

        assert isinstance(result, dict)
        assert result["files"] == []

    async def test_returns_all_files_when_no_keyword_filter(self, tmp_path):
        """Should return all recognized data files when no keyword is given."""
        raw_dir = tmp_path / "raw"
        processed_dir = tmp_path / "processed"
        raw_dir.mkdir(parents=True)
        processed_dir.mkdir(parents=True)

        (raw_dir / "Python-tutorial_20240315_143022.json").write_text("{}", encoding="utf-8")
        (raw_dir / "food_20240315_143022.json").write_text("{}", encoding="utf-8")
        (processed_dir / "Python-tutorial_20240315_143022.xlsx").write_bytes(b"xlsx_content")

        session = CrawlerSession()
        result = await session.get_saved_data(data_dir=tmp_path)

        assert len(result["files"]) == 3

    async def test_filters_files_by_keyword(self, tmp_path):
        """Should return only matching files when a keyword is given (case-insensitive, fuzzy match)."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        (tmp_path / "processed").mkdir(parents=True)

        (raw_dir / "Python-tutorial_20240315_143022.json").write_text("{}", encoding="utf-8")
        (raw_dir / "food-picks_20240315_143022.json").write_text("{}", encoding="utf-8")

        session = CrawlerSession()
        result = await session.get_saved_data(keyword="python", data_dir=tmp_path)

        assert len(result["files"]) == 1
        assert "Python" in result["files"][0]["keyword"]

    async def test_returns_file_metadata(self, tmp_path):
        """Each file record should contain the four fields path/keyword/created_at/size_bytes."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        (tmp_path / "processed").mkdir(parents=True)

        test_file = raw_dir / "test-keyword_20240315_143022.json"
        test_file.write_text('{"count": 5}', encoding="utf-8")

        session = CrawlerSession()
        result = await session.get_saved_data(data_dir=tmp_path)

        assert len(result["files"]) == 1
        file_info = result["files"][0]
        assert "path" in file_info
        assert "keyword" in file_info
        assert "created_at" in file_info
        assert "size_bytes" in file_info
        assert file_info["keyword"] == "test-keyword"
        assert file_info["size_bytes"] > 0

    async def test_extracts_keyword_from_notes_prefix(self, tmp_path):
        """Files with the notes_ prefix should have it stripped before the keyword is extracted."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        (tmp_path / "processed").mkdir(parents=True)

        (raw_dir / "notes_rednote-tips_20240315_143022.json").write_text("{}", encoding="utf-8")

        session = CrawlerSession()
        result = await session.get_saved_data(data_dir=tmp_path)

        assert len(result["files"]) == 1
        assert result["files"][0]["keyword"] == "rednote-tips"

    async def test_ignores_unrecognized_files(self, tmp_path):
        """Non-data files (e.g. .gitkeep) should be ignored and not appear in the results."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        (tmp_path / "processed").mkdir(parents=True)

        (raw_dir / ".gitkeep").write_text("", encoding="utf-8")
        (raw_dir / "keyword_20240315_143022.json").write_text("{}", encoding="utf-8")

        session = CrawlerSession()
        result = await session.get_saved_data(data_dir=tmp_path)

        assert len(result["files"]) == 1

    async def test_returns_files_key(self, tmp_path):
        """The return value must contain the files key."""
        session = CrawlerSession()
        result = await session.get_saved_data(data_dir=tmp_path)

        assert "files" in result
        assert isinstance(result["files"], list)

    async def test_does_not_require_browser(self):
        """get_saved_data does not depend on the browser and works even when it is not running."""
        session = CrawlerSession()
        # Browser not running, data_dir does not exist
        result = await session.get_saved_data(data_dir=Path("/tmp/nonexistent_rednote_test_dir_xyz"))

        assert "files" in result
        assert result.get("error") is not True

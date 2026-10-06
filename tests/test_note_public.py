"""
B2: tests for the fetch_single_note public interface

Test strategy:
  - _extract_note_id_from_url is a pure function and is tested directly
  - fetch_single_note is isolated from browser calls by mocking _fetch_single_note
  - Covers: happy path, invalid URL, None fallback, default arguments
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.note import _extract_note_id_from_url, fetch_single_note


class TestExtractNoteIdFromUrl:
    """Tests for the helper that extracts note_id from a URL."""

    def test_extracts_id_from_standard_url(self):
        """A standard explore URL should yield the correct note_id."""
        url = "https://www.rednote.com/explore/65abc1234567890abcde?xsec_token=xxx"
        assert _extract_note_id_from_url(url) == "65abc1234567890abcde"

    def test_extracts_id_without_query_params(self):
        """A URL without query parameters should also be extracted correctly."""
        url = "https://www.rednote.com/explore/abc123def456"
        assert _extract_note_id_from_url(url) == "abc123def456"

    def test_returns_none_for_url_without_explore(self):
        """A URL without the /explore/ path should return None."""
        assert _extract_note_id_from_url("https://www.rednote.com/search") is None

    def test_returns_none_for_empty_string(self):
        """An empty string should return None."""
        assert _extract_note_id_from_url("") is None

    def test_returns_none_for_non_url(self):
        """A non-URL string should return None."""
        assert _extract_note_id_from_url("not-a-url") is None

    def test_handles_mixed_case_note_id(self):
        """A note_id may contain upper- and lower-case letters and digits."""
        url = "https://www.rednote.com/explore/AbC123XyZ"
        assert _extract_note_id_from_url(url) == "AbC123XyZ"


class TestFetchSingleNote:
    """Tests for the fetch_single_note public interface."""

    async def test_returns_none_for_invalid_url(self):
        """Should return None without raising when the URL has no note_id."""
        mock_bm = MagicMock()
        result = await fetch_single_note(mock_bm, note_url="https://example.com/no/id")
        assert result is None

    async def test_returns_none_for_empty_url(self):
        """An empty URL should return None."""
        mock_bm = MagicMock()
        result = await fetch_single_note(mock_bm, note_url="")
        assert result is None

    async def test_calls_internal_with_extracted_note_id(self):
        """Should pass the note_id extracted from the URL to the internal implementation."""
        mock_bm = MagicMock()
        mock_detail = {"note_id": "abc123", "title": "Test note", "comments": []}
        note_url = "https://www.rednote.com/explore/abc123?xsec_token=xyz"

        with patch("src.note._fetch_single_note", new=AsyncMock(return_value=mock_detail)) as mock_inner:
            result = await fetch_single_note(mock_bm, note_url=note_url, max_comments=10)

            mock_inner.assert_called_once()
            call_kwargs = mock_inner.call_args[1]
            assert call_kwargs["note_id"] == "abc123"
            assert call_kwargs["note_url"] == note_url
            assert call_kwargs["max_comments"] == 10
            assert result == mock_detail

    async def test_default_max_comments_is_20(self):
        """The default max_comments should be 20."""
        mock_bm = MagicMock()
        note_url = "https://www.rednote.com/explore/abc123"

        with patch("src.note._fetch_single_note", new=AsyncMock(return_value={})) as mock_inner:
            await fetch_single_note(mock_bm, note_url=note_url)
            assert mock_inner.call_args[1]["max_comments"] == 20

    async def test_returns_none_when_inner_returns_none(self):
        """Should pass None through when the internal function returns None."""
        mock_bm = MagicMock()
        note_url = "https://www.rednote.com/explore/abc123"

        with patch("src.note._fetch_single_note", new=AsyncMock(return_value=None)):
            result = await fetch_single_note(mock_bm, note_url=note_url)
            assert result is None

    async def test_passes_bm_to_internal(self):
        """The BrowserManager instance should be passed to the internal function correctly."""
        mock_bm = MagicMock()
        note_url = "https://www.rednote.com/explore/abc123"

        with patch("src.note._fetch_single_note", new=AsyncMock(return_value={})) as mock_inner:
            await fetch_single_note(mock_bm, note_url=note_url)
            # The first positional argument is bm
            assert mock_inner.call_args[0][0] is mock_bm

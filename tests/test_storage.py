"""
Unit tests for the Storage module

Test strategy:
  - Uses the pytest tmp_path fixture to isolate file I/O and keep the real data directory clean
  - Covers the full behaviour of the Storage class: directory creation, JSON writing, Excel writing
  - Covers the various input formats of the _sanitize_filename pure function
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from src.storage import Storage, _sanitize_filename

# ---- Test data ----

SAMPLE_SEARCH_RESULTS = [
    {
        "note_id": "abc123",
        "title": "Python Beginner Tutorial",
        "author": "rednote user",
        "author_id": "user001",
        "likes": 1200,
        "note_type": "image",
        "note_url": "https://www.rednote.com/explore/abc123",
        "publish_time": "2025-01-15",
    },
    {
        "note_id": "def456",
        "title": "Advanced Python",
        "author": "another user",
        "author_id": "user002",
        "likes": 500,
        "note_type": "video",
        "note_url": "https://www.rednote.com/explore/def456",
        "publish_time": "2025-01-16",
    },
]

SAMPLE_NOTE_DETAILS = [
    {
        "note_id": "abc123",
        "title": "Python Beginner Tutorial",
        "content": "This is a Python beginner tutorial...",
        "author": "rednote user",
        "author_id": "user001",
        "publish_time": "2025-01-15",
        "likes": 1200,
        "collects": 300,
        "comments_count": 50,
        "shares": 20,
        "tags": ["Python", "programming", "tutorial"],
        "note_type": "image",
        "note_url": "https://www.rednote.com/explore/abc123",
        "images": ["https://example.com/img1.jpg"],
        "video_url": "",
        "comments": [
            {
                "comment_id": "cmt001",
                "note_id": "abc123",
                "user_name": "commenter",
                "user_id": "usr001",
                "content": "So useful!",
                "likes": 10,
                "time": "01-15",
                "ip_location": "Guangdong",
            }
        ],
    }
]


class TestSanitizeFilename:
    """Tests for the filename-sanitising pure function."""

    def test_normal_alphanumeric_unchanged(self):
        """A plain alphanumeric string should stay unchanged."""
        assert _sanitize_filename("Python123") == "Python123"

    def test_chinese_keyword_preserved(self):
        """Chinese characters should be preserved."""
        result = _sanitize_filename("小红书教程")
        assert "小红书教程" in result

    def test_replaces_slash(self):
        """Slashes should be replaced."""
        result = _sanitize_filename("a/b")
        assert "/" not in result

    def test_replaces_colon(self):
        """Colons should be replaced."""
        result = _sanitize_filename("a:b")
        assert ":" not in result

    def test_replaces_spaces(self):
        """Spaces should be replaced."""
        result = _sanitize_filename("hello world")
        assert " " not in result

    def test_merges_consecutive_underscores(self):
        """Consecutive underscores should be collapsed into one."""
        result = _sanitize_filename("a//b")
        assert "__" not in result

    def test_strips_leading_and_trailing_underscores(self):
        """Leading and trailing underscores should be stripped."""
        result = _sanitize_filename("/test/")
        assert not result.startswith("_")
        assert not result.endswith("_")

    def test_all_special_chars_returns_unnamed(self):
        """Should return 'unnamed' when every character is unsafe."""
        assert _sanitize_filename("///") == "unnamed"
        assert _sanitize_filename("?*<>") == "unnamed"

    def test_replaces_all_unsafe_chars(self):
        """All unsafe characters should be replaced."""
        for ch in r'\/:*?"<>|':
            result = _sanitize_filename(ch + "text" + ch)
            assert ch not in result


class TestStorageInit:
    """Tests for Storage initialisation behaviour."""

    def test_creates_raw_directory(self, tmp_path):
        """Initialisation should create the raw/ subdirectory."""
        Storage({"output_dir": str(tmp_path / "data")})
        assert (tmp_path / "data" / "raw").is_dir()

    def test_creates_processed_directory(self, tmp_path):
        """Initialisation should create the processed/ subdirectory."""
        Storage({"output_dir": str(tmp_path / "data")})
        assert (tmp_path / "data" / "processed").is_dir()

    def test_default_output_dir_is_data(self, tmp_path, monkeypatch):
        """Defaults to 'data' when output_dir is not specified."""
        monkeypatch.chdir(tmp_path)
        Storage({})
        assert (tmp_path / "data" / "raw").is_dir()

    def test_save_json_defaults_to_true(self, tmp_path):
        """save_raw_json defaults to True."""
        s = Storage({"output_dir": str(tmp_path)})
        assert s._save_json is True

    def test_save_xlsx_defaults_to_true(self, tmp_path):
        """save_xlsx defaults to True."""
        s = Storage({"output_dir": str(tmp_path)})
        assert s._save_xlsx is True

    def test_save_json_can_be_disabled(self, tmp_path):
        """save_raw_json=False turns off JSON writing."""
        s = Storage({"output_dir": str(tmp_path), "save_raw_json": False})
        assert s._save_json is False

    def test_save_xlsx_can_be_disabled(self, tmp_path):
        """save_xlsx=False turns off Excel writing."""
        s = Storage({"output_dir": str(tmp_path), "save_xlsx": False})
        assert s._save_xlsx is False


class TestWriteJson:
    """Tests for JSON writing."""

    def test_creates_search_json_file(self, tmp_path):
        """Should create a JSON file in raw/ when there are search results."""
        storage = Storage({"output_dir": str(tmp_path), "save_xlsx": False})
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, [])
        raw_files = list((tmp_path / "raw").glob("*.json"))
        assert len(raw_files) == 1

    def test_search_json_has_correct_structure(self, tmp_path):
        """The search JSON file should contain keyword / crawled_at / count / results."""
        storage = Storage({"output_dir": str(tmp_path), "save_xlsx": False})
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, [])
        json_file = list((tmp_path / "raw").glob("Python_*.json"))[0]
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)
        assert data["keyword"] == "Python"
        assert "crawled_at" in data
        assert data["count"] == len(SAMPLE_SEARCH_RESULTS)
        assert len(data["results"]) == len(SAMPLE_SEARCH_RESULTS)

    def test_notes_json_created_when_details_exist(self, tmp_path):
        """Should create a notes_{keyword}_*.json file when there are note details."""
        storage = Storage({"output_dir": str(tmp_path), "save_xlsx": False})
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, SAMPLE_NOTE_DETAILS)
        notes_files = list((tmp_path / "raw").glob("notes_Python_*.json"))
        assert len(notes_files) == 1

    def test_notes_json_contains_notes_key(self, tmp_path):
        """The note details JSON should contain the notes key and count."""
        storage = Storage({"output_dir": str(tmp_path), "save_xlsx": False})
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, SAMPLE_NOTE_DETAILS)
        notes_file = list((tmp_path / "raw").glob("notes_Python_*.json"))[0]
        with open(notes_file, encoding="utf-8") as f:
            data = json.load(f)
        assert "notes" in data
        assert data["count"] == len(SAMPLE_NOTE_DETAILS)

    def test_no_json_when_search_results_empty(self, tmp_path):
        """No search JSON file is created when the search results are empty."""
        storage = Storage({"output_dir": str(tmp_path), "save_xlsx": False})
        storage.save_all("Python", [], [])
        raw_files = list((tmp_path / "raw").glob("*.json"))
        assert len(raw_files) == 0

    def test_no_json_when_disabled(self, tmp_path):
        """No JSON file is created when save_raw_json=False."""
        storage = Storage(
            {"output_dir": str(tmp_path), "save_raw_json": False, "save_xlsx": False}
        )
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, SAMPLE_NOTE_DETAILS)
        raw_files = list((tmp_path / "raw").glob("*.json"))
        assert len(raw_files) == 0

    def test_json_preserves_unicode(self, tmp_path):
        """Chinese content should be written to UTF-8 JSON correctly."""
        storage = Storage({"output_dir": str(tmp_path), "save_xlsx": False})
        storage.save_all("小红书", SAMPLE_SEARCH_RESULTS, [])
        json_file = list((tmp_path / "raw").glob("*.json"))[0]
        content = json_file.read_text(encoding="utf-8")
        assert "小红书" in content


class TestWriteXlsx:
    """Tests for Excel writing."""

    def test_creates_xlsx_file(self, tmp_path):
        """Should create an xlsx file in processed/ when there is data."""
        storage = Storage({"output_dir": str(tmp_path), "save_raw_json": False})
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, SAMPLE_NOTE_DETAILS)
        xlsx_files = list((tmp_path / "processed").glob("*.xlsx"))
        assert len(xlsx_files) == 1

    def test_xlsx_has_three_sheets(self, tmp_path):
        """The Excel file should contain the three sheets Search Results / Note Details / Comments."""
        storage = Storage({"output_dir": str(tmp_path), "save_raw_json": False})
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, SAMPLE_NOTE_DETAILS)
        xlsx_file = list((tmp_path / "processed").glob("*.xlsx"))[0]
        wb = load_workbook(xlsx_file)
        assert "Search Results" in wb.sheetnames
        assert "Note Details" in wb.sheetnames
        assert "Comments" in wb.sheetnames

    def test_search_sheet_has_header_row(self, tmp_path):
        """The Search Results sheet should have the correct header row."""
        storage = Storage({"output_dir": str(tmp_path), "save_raw_json": False})
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, [])
        xlsx_file = list((tmp_path / "processed").glob("*.xlsx"))[0]
        ws = load_workbook(xlsx_file)["Search Results"]
        header = [cell.value for cell in ws[1]]
        assert "Note ID" in header
        assert "Title" in header
        assert "Author" in header

    def test_search_sheet_row_count(self, tmp_path):
        """The Search Results sheet row count should be header + data rows."""
        storage = Storage({"output_dir": str(tmp_path), "save_raw_json": False})
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, [])
        xlsx_file = list((tmp_path / "processed").glob("*.xlsx"))[0]
        ws = load_workbook(xlsx_file)["Search Results"]
        assert ws.max_row == 1 + len(SAMPLE_SEARCH_RESULTS)

    def test_comments_aggregated_in_third_sheet(self, tmp_path):
        """Comments from all notes should be combined in the Comments sheet (1 header + number of comments)."""
        storage = Storage({"output_dir": str(tmp_path), "save_raw_json": False})
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, SAMPLE_NOTE_DETAILS)
        xlsx_file = list((tmp_path / "processed").glob("*.xlsx"))[0]
        ws = load_workbook(xlsx_file)["Comments"]
        total_comments = sum(len(n.get("comments", [])) for n in SAMPLE_NOTE_DETAILS)
        assert ws.max_row == 1 + total_comments

    def test_sheet_has_frozen_pane(self, tmp_path):
        """The header row should have a frozen pane (A2)."""
        storage = Storage({"output_dir": str(tmp_path), "save_raw_json": False})
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, [])
        xlsx_file = list((tmp_path / "processed").glob("*.xlsx"))[0]
        ws = load_workbook(xlsx_file)["Search Results"]
        assert ws.freeze_panes == "A2"

    def test_note_tags_serialized_as_semicolon_string(self, tmp_path):
        """The tags list in the Note Details sheet should be serialised as a semicolon-separated string."""
        storage = Storage({"output_dir": str(tmp_path), "save_raw_json": False})
        storage.save_all("Python", [], SAMPLE_NOTE_DETAILS)
        xlsx_file = list((tmp_path / "processed").glob("*.xlsx"))[0]
        ws = load_workbook(xlsx_file)["Note Details"]
        header = [cell.value for cell in ws[1]]
        tags_col = header.index("Tags") + 1
        tags_cell = ws.cell(row=2, column=tags_col)
        assert tags_cell.value == "Python;programming;tutorial"

    def test_no_xlsx_when_disabled(self, tmp_path):
        """No xlsx file is created when save_xlsx=False."""
        storage = Storage(
            {"output_dir": str(tmp_path), "save_raw_json": False, "save_xlsx": False}
        )
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, SAMPLE_NOTE_DETAILS)
        xlsx_files = list((tmp_path / "processed").glob("*.xlsx"))
        assert len(xlsx_files) == 0

    def test_xlsx_created_with_empty_data(self, tmp_path):
        """An xlsx file should be created with save_xlsx=True even when the data is empty."""
        storage = Storage({"output_dir": str(tmp_path), "save_raw_json": False})
        storage.save_all("Python", [], [])
        xlsx_files = list((tmp_path / "processed").glob("*.xlsx"))
        assert len(xlsx_files) == 1

    def test_xlsx_column_width_is_set(self, tmp_path):
        """Column widths should be set automatically (not the default None)."""
        storage = Storage({"output_dir": str(tmp_path), "save_raw_json": False})
        storage.save_all("Python", SAMPLE_SEARCH_RESULTS, [])
        xlsx_file = list((tmp_path / "processed").glob("*.xlsx"))[0]
        ws = load_workbook(xlsx_file)["Search Results"]
        # At least the first column (Note ID) should have its width set
        col_width = ws.column_dimensions["A"].width
        assert col_width is not None
        assert col_width > 0

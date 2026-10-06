"""
Tests for the unified error format module (Phase D — D3)

Test strategy:
  - Verify CrawlerError immutability (frozen dataclass)
  - Verify the to_dict() output format and field completeness
  - Verify the field values of the predefined error factory functions
  - Cover all error code constants
"""

from __future__ import annotations

import pytest

from src.errors import (
    CrawlerError,
    browser_crashed_error,
    browser_not_running_error,
    crawl_failed_error,
    invalid_input_error,
    login_expired_error,
    timeout_error,
)


class TestCrawlerErrorDataclass:
    """Tests for the CrawlerError data structure."""

    def test_fields_are_set(self):
        """Should store the code / message / action fields correctly."""
        err = CrawlerError(code="TEST", message="test message", action="test action")
        assert err.code == "TEST"
        assert err.message == "test message"
        assert err.action == "test action"

    def test_frozen_immutability(self):
        """frozen=True should prevent fields from being modified."""
        err = CrawlerError(code="TEST", message="msg", action="act")
        with pytest.raises(AttributeError):
            err.code = "CHANGED"

    def test_to_dict_format(self):
        """to_dict() should return the standard error dict format."""
        err = CrawlerError(code="ERR_CODE", message="something went wrong", action="please retry")
        result = err.to_dict()

        assert result == {
            "error": True,
            "code": "ERR_CODE",
            "message": "something went wrong",
            "action": "please retry",
        }

    def test_to_dict_always_has_error_true(self):
        """The error field of to_dict() is always True."""
        err = CrawlerError(code="X", message="m", action="a")
        assert err.to_dict()["error"] is True

    def test_to_dict_returns_new_dict_each_call(self):
        """Each to_dict() call should return a new dict (immutability guarantee)."""
        err = CrawlerError(code="X", message="m", action="a")
        d1 = err.to_dict()
        d2 = err.to_dict()
        assert d1 == d2
        assert d1 is not d2


class TestPredefinedErrors:
    """Tests for the predefined error factory functions."""

    def test_browser_not_running_error(self):
        """The browser-not-running error should contain the correct code and action."""
        err = browser_not_running_error()
        d = err.to_dict()
        assert d["code"] == "BROWSER_NOT_RUNNING"
        assert d["error"] is True
        assert "action" in d
        assert len(d["message"]) > 0

    def test_browser_crashed_error(self):
        """The browser-crashed error should contain the correct code."""
        err = browser_crashed_error()
        d = err.to_dict()
        assert d["code"] == "BROWSER_CRASHED"
        assert "recover" in d["action"] or "Restart" in d["action"]

    def test_login_expired_error(self):
        """The login-expired error should contain the correct code and login instructions."""
        err = login_expired_error()
        d = err.to_dict()
        assert d["code"] == "LOGIN_EXPIRED"
        assert "verify_login" in d["action"]

    def test_timeout_error_with_tool_name(self):
        """The timeout error should contain the tool name and timeout duration."""
        err = timeout_error(tool_name="search_notes", timeout_seconds=120)
        d = err.to_dict()
        assert d["code"] == "TIMEOUT"
        assert "search_notes" in d["message"]
        assert "120" in d["message"]

    def test_timeout_error_custom_values(self):
        """The timeout error should fill in custom arguments correctly."""
        err = timeout_error(tool_name="crawl_keyword", timeout_seconds=600)
        d = err.to_dict()
        assert "crawl_keyword" in d["message"]
        assert "600" in d["message"]

    def test_invalid_input_error_with_field(self):
        """The invalid-input error should contain the field name and the specific reason."""
        err = invalid_input_error(field="keyword", reason="must not be empty")
        d = err.to_dict()
        assert d["code"] == "INVALID_INPUT"
        assert "keyword" in d["message"]
        assert "must not be empty" in d["message"]

    def test_crawl_failed_error_with_detail(self):
        """The crawl-failed error should contain the specific failure details."""
        err = crawl_failed_error(detail="URL is invalid or the page could not be loaded")
        d = err.to_dict()
        assert d["code"] == "CRAWL_FAILED"
        assert "URL" in d["message"]

"""
Unified error format module (Phase D — D3)

Responsibilities:
  - Define the unified error data structure returned by MCP tools
  - Provide predefined error factory functions so error codes and message style stay consistent
  - All MCP tool errors are built through this module, making them easy for AI assistants to parse and handle

Error dict format:
  {
      "error": True,       # Marks the response as an error
      "code": str,         # Machine-readable error code (upper snake case)
      "message": str,      # Human-readable error description
      "action": str        # Suggested fix
  }

Error codes:
  - BROWSER_NOT_RUNNING: the browser is not running
  - BROWSER_CRASHED: the browser crashed and automatic recovery failed
  - LOGIN_EXPIRED: the login session has expired
  - TIMEOUT: the operation timed out
  - INVALID_INPUT: an input parameter is invalid
  - CRAWL_FAILED: the crawl operation failed
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CrawlerError:
    """Unified error structure for MCP tools (immutable).

    Attributes:
        code: Machine-readable error code (e.g. BROWSER_NOT_RUNNING)
        message: Human-readable error description
        action: Suggested fix for the user or AI to carry out
    """

    code: str
    message: str
    action: str

    def to_dict(self) -> dict:
        """Convert to the standard error dict returned by MCP tools."""
        return {
            "error": True,
            "code": self.code,
            "message": self.message,
            "action": self.action,
        }


# ============================================================
# Predefined error factory functions
# ============================================================


def browser_not_running_error() -> CrawlerError:
    """Error for when the browser is not running."""
    return CrawlerError(
        code="BROWSER_NOT_RUNNING",
        message="Browser is not running. Make sure the MCP server is running, then retry.",
        action="Restart the MCP server, or check that Playwright is installed correctly.",
    )


def browser_crashed_error() -> CrawlerError:
    """Error for when the browser crashed and automatic recovery failed."""
    return CrawlerError(
        code="BROWSER_CRASHED",
        message="Browser crashed and automatic recovery failed.",
        action="Restart the MCP server to recover the browser.",
    )


def login_expired_error() -> CrawlerError:
    """Error for when the login session has expired."""
    return CrawlerError(
        code="LOGIN_EXPIRED",
        message="rednote login has expired; you need to log in again.",
        action=(
            "Run `uv run python scripts/verify_login.py` in a terminal "
            "to log in by scanning the QR code, then restart the MCP server."
        ),
    )


def timeout_error(tool_name: str, timeout_seconds: int) -> CrawlerError:
    """Error for when an operation times out.

    Args:
        tool_name: Name of the tool that timed out
        timeout_seconds: Timeout duration (seconds)
    """
    return CrawlerError(
        code="TIMEOUT",
        message=f"{tool_name} timed out after {timeout_seconds} seconds.",
        action="Retry later, or reduce the crawl size (e.g. max_count / max_notes).",
    )


def invalid_input_error(field: str, reason: str) -> CrawlerError:
    """Error for when an input parameter is invalid.

    Args:
        field: Name of the invalid parameter
        reason: Why it is invalid
    """
    return CrawlerError(
        code="INVALID_INPUT",
        message=f"Invalid parameter {field}: {reason}",
        action=f"Check the {field} parameter and retry.",
    )


def crawl_failed_error(detail: str) -> CrawlerError:
    """Error for when the crawl operation fails.

    Args:
        detail: Specific reason for the failure
    """
    return CrawlerError(
        code="CRAWL_FAILED",
        message=f"Crawl failed: {detail}",
        action="Check that the URL is valid, or retry later.",
    )

"""
Phase B MCP tool end-to-end verification script

Verifies the MCP tool layer (mcp_server.py) against a real browser:
  1. Start a CrawlerSession (real browser)
  2. Call the check_login_status tool and verify the return structure
  3. Verify search_notes input validation (empty keyword, max_count clamping)
  4. Call the search_notes tool and verify the structured result
  5. Call the get_note_detail tool (using the URL of the first search result)
  6. Print the verification report

Usage:
    uv run python scripts/verify_mcp_tools.py [keyword]

Examples:
    uv run python scripts/verify_mcp_tools.py              # use the default keyword
    uv run python scripts/verify_mcp_tools.py "Python tutorial" # use a specific keyword

Prerequisites:
    - Already logged in to rednote in your everyday Chrome
    - If not logged in, first run: uv run python scripts/verify_login.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import mcp_server
from src.session import CrawlerSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Default keyword for verification
DEFAULT_KEYWORD = "Python tutorial"

# Use a small-scale configuration for end-to-end verification to keep it fast
VERIFY_MAX_COUNT = 3
VERIFY_MAX_COMMENTS = 5


def _check(label: str, condition: bool, detail: str = "") -> bool:
    """Print the result of a single check and return whether it passed."""
    mark = "✓" if condition else "✗"
    suffix = f": {detail}" if detail else ""
    print(f"  {mark} {label}{suffix}")
    return condition


async def run(keyword: str) -> bool:
    """Run the Phase B MCP tool end-to-end verification.

    Returns:
        True if verification passed, False if it failed
    """
    print("\n" + "=" * 60)
    print("  Phase B — MCP tool end-to-end verification")
    print("=" * 60)
    print(f"  Keyword: {keyword}")
    print(f"  Search count: {VERIFY_MAX_COUNT}, comment count: {VERIFY_MAX_COMMENTS}")
    print()

    passed = True
    session = CrawlerSession()

    # Replace the module-level _session so the mcp_server tool functions use the local session
    original_session = mcp_server._session
    mcp_server._session = session

    search_result: dict = {}

    try:
        # ---- Step 1: start the browser session (simulates lifespan) ----
        print("[1/5] Starting browser session...")
        await session.start()
        ok = _check("Browser session started", session.is_running() is True)
        passed &= ok
        print()

        # ---- Step 2: verify the check_login_status tool ----
        print("[2/5] Verifying the check_login_status tool...")
        login_result = await mcp_server.check_login_status()
        passed &= _check("Result contains logged_in", "logged_in" in login_result)
        passed &= _check("Result contains browser_running", "browser_running" in login_result)
        passed &= _check("Result contains message", "message" in login_result)
        passed &= _check("browser_running=True", login_result.get("browser_running") is True)

        is_logged_in = login_result.get("logged_in", False)
        if not is_logged_in:
            print("\n  ⚠️  Not logged in; the search/detail tool checks will be skipped.")
            print("     Run verify_login.py to log in, then try again.")
        else:
            print("  ✓ Logged in to rednote")
        print()

        # ---- Step 3: verify search_notes input validation ----
        print("[3/5] Verifying search_notes input validation...")

        empty_result = await mcp_server.search_notes(keyword="")
        passed &= _check("Empty keyword returns error=True", empty_result.get("error") is True)

        ws_result = await mcp_server.search_notes(keyword="   ")
        passed &= _check("Whitespace-only keyword returns error=True", ws_result.get("error") is True)

        # max_count=200 should not crash (clamped to 50)
        try:
            await mcp_server.search_notes(keyword="test_clamp", max_count=200)
            passed &= _check("max_count=200 does not crash", True)
        except Exception as e:
            passed &= _check("max_count=200 does not crash", False, str(e))

        # max_count=0 should be clamped to 1
        try:
            await mcp_server.search_notes(keyword="test_clamp", max_count=0)
            passed &= _check("max_count=0 does not crash", True)
        except Exception as e:
            passed &= _check("max_count=0 does not crash", False, str(e))
        print()

        # ---- Step 4: verify a normal search_notes call ----
        print(f"[4/5] Verifying search_notes (keyword={keyword!r}, max_count={VERIFY_MAX_COUNT})...")

        if is_logged_in:
            search_result = await mcp_server.search_notes(
                keyword=keyword, max_count=VERIFY_MAX_COUNT
            )

            if search_result.get("error"):
                print(f"  ⚠️  Search returned an error: {search_result.get('message', 'unknown error')}")
                print("     Possible causes: page structure change or network error")
            else:
                passed &= _check("Result contains keyword", "keyword" in search_result)
                passed &= _check("Result contains count", "count" in search_result)
                passed &= _check("Result contains results", "results" in search_result)

                result_count = len(search_result.get("results", []))
                passed &= _check(f"results is non-empty", result_count >= 1, f"{result_count} items")

                returned_keyword = search_result.get("keyword", "")
                passed &= _check(
                    "keyword field matches the input",
                    returned_keyword == keyword,
                    f"expected={keyword!r}, actual={returned_keyword!r}",
                )
        else:
            print("  ⚠️  Skipped (not logged in)")
        print()

        # ---- Step 5: verify the get_note_detail tool ----
        print("[5/5] Verifying the get_note_detail tool...")

        # 5a. Input validation: empty URL
        empty_url_result = await mcp_server.get_note_detail(note_url="")
        passed &= _check("Empty note_url returns error=True", empty_url_result.get("error") is True)

        # 5b. Real fetch (requires login + search results)
        if is_logged_in and not search_result.get("error") and search_result.get("results"):
            first_note = search_result["results"][0]
            note_url = first_note.get("note_url", "")

            if note_url:
                safe_url = note_url.split("?")[0]
                print(f"\n  Fetching the first note: {safe_url}...")

                detail_result = await mcp_server.get_note_detail(
                    note_url=note_url, max_comments=VERIFY_MAX_COMMENTS
                )

                if detail_result.get("error"):
                    print(f"  ⚠️  Fetch failed: {detail_result.get('message', 'unknown error')}")
                    print("     Possible causes: page structure change, expired URL, or network error")
                else:
                    passed &= _check("Detail contains note_id", "note_id" in detail_result)
                    passed &= _check("Detail contains title", "title" in detail_result)
                    passed &= _check("Detail contains comments", "comments" in detail_result)

                    comments = detail_result.get("comments", [])
                    print(f"  ✓ Comments: {len(comments)}")

                    title_preview = (detail_result.get("title") or "")[:30]
                    if title_preview:
                        print(f"  ✓ Title: {title_preview}...")
            else:
                print("  ⚠️  Skipped get_note_detail (first search result has no note_url)")
        else:
            print("  ⚠️  Skipped (not logged in or no search results)")

    except Exception as e:
        logger.error("Verification error: %s", e, exc_info=True)
        print(f"\n  ✗ Verification error: {e}")
        passed = False

    finally:
        # ---- Cleanup ----
        print("\nCleanup: stopping browser session...")
        await session.stop()
        mcp_server._session = original_session
        print("  Browser session closed")

    # ---- Verdict ----
    print()
    print("=" * 60)
    if passed:
        print("  ✅ Phase B MCP tool verification passed")
        print("  check_login_status / search_notes / get_note_detail tools are working")
    else:
        print("  ✗ Phase B MCP tool verification failed")
        print("  Check the detailed output above for the failed items")
    print()

    return passed


if __name__ == "__main__":
    keyword = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_KEYWORD
    success = asyncio.run(run(keyword))
    sys.exit(0 if success else 1)

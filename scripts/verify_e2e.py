"""
Phase 4 end-to-end verification script

Verifies the full crawl flow: keyword → search → details → comments → storage

  1. Check that the login state is ready
  2. Run a full single-keyword crawl with crawl_keyword() from main.py
  3. Verify that the output files exist and the data is complete
  4. Print a verification report

Usage:
    uv run python scripts/verify_e2e.py [keyword]

Examples:
    uv run python scripts/verify_e2e.py                  # use the default keyword
    uv run python scripts/verify_e2e.py "coffee"         # specify a keyword

Prerequisites:
    - Already logged in to rednote in your everyday Chrome
    - If not logged in, first run: uv run python scripts/verify_login.py
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.auth import is_logged_in
from src.browser import BrowserManager
from src.storage import Storage

# Reuse the crawl_keyword logic from main.py (direct import)
from main import crawl_keyword

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Default keyword for verification
DEFAULT_KEYWORD = "coffee"

# Use a small-scale config for end-to-end verification to keep it fast
VERIFY_CRAWLER_CFG = {
    "max_notes_per_keyword": 3,   # search for only 3 notes
    "max_comments_per_note": 5,   # up to 5 comments per note
    "scroll_pause": 1.5,
}

VERIFY_DELAY_CFG = {
    "between_notes": [2.0, 3.0],
    "between_searches": [3.0, 5.0],
    "scroll_interval": [1.0, 2.0],
}

VERIFY_STORAGE_CFG = {
    "output_dir": "data",
    "save_raw_json": True,
    "save_csv": True,
}


def _check_output_files(keyword: str) -> dict:
    """Check the files written by this crawl and return a summary of the results.

    Returns:
        A dict with the existence status and stats for each kind of file
    """
    data_dir = Path("data")
    raw_dir = data_dir / "raw"
    processed_dir = data_dir / "processed"

    # Sanitize the keyword (same logic as storage.py)
    import re
    safe_kw = re.sub(r'[\\/:*?"<>|\s]', "_", keyword)
    safe_kw = re.sub(r"_+", "_", safe_kw).strip("_") or "unnamed"

    result: dict = {
        "search_json": [],
        "notes_json": [],
        "search_csv": None,
        "notes_csv": None,
        "comments_csv": None,
    }

    if raw_dir.exists():
        # Search results JSON
        result["search_json"] = sorted(raw_dir.glob(f"{safe_kw}_*.json"))
        # Note details JSON
        result["notes_json"] = sorted(raw_dir.glob(f"notes_{safe_kw}_*.json"))

    if processed_dir.exists():
        search_csv = processed_dir / f"search_results_{safe_kw}.csv"
        notes_csv = processed_dir / f"notes_{safe_kw}.csv"
        comments_csv = processed_dir / f"comments_{safe_kw}.csv"
        result["search_csv"] = search_csv if search_csv.exists() else None
        result["notes_csv"] = notes_csv if notes_csv.exists() else None
        result["comments_csv"] = comments_csv if comments_csv.exists() else None

    return result


def _count_json_records(json_path: Path, key: str) -> int:
    """Read the length of the array under the given key in a JSON file."""
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get(key, [])
        return len(items)
    except Exception:
        return -1


def _count_csv_rows(csv_path: Path) -> int:
    """Count the data rows in a CSV file (excluding the header)."""
    try:
        lines = csv_path.read_text(encoding="utf-8-sig").splitlines()
        return max(0, len(lines) - 1)  # subtract the header
    except Exception:
        return -1


async def run(keyword: str) -> bool:
    """Run the Phase 4 end-to-end verification.

    Returns:
        True if verification passed, False if it failed
    """
    print("\n" + "=" * 60)
    print("  Phase 4 — end-to-end integration verification")
    print("=" * 60)
    print(f"  Keyword: {keyword}")
    print(f"  Crawl size: {VERIFY_CRAWLER_CFG['max_notes_per_keyword']} notes, "
          f"up to {VERIFY_CRAWLER_CFG['max_comments_per_note']} comments each")
    print()

    crawl_success = False

    async with BrowserManager() as bm:
        # ---- Step 2: Verify the login state is valid ----
        print("[1/3] Verifying login state...")
        page = await bm.new_page()
        logged_in = await is_logged_in(page)
        await page.close()

        if not logged_in:
            print("  ✗ Login state has expired; log in again (verify_login.py)")
            return False
        print("  ✓ Login state is valid\n")

        # ---- Step 3: Run the full crawl flow ----
        print(f"[2/3] Running the end-to-end crawl (keyword: {keyword!r})...")
        storage = Storage(VERIFY_STORAGE_CFG)
        try:
            await crawl_keyword(
                bm,
                keyword=keyword,
                crawler_cfg=VERIFY_CRAWLER_CFG,
                delay_cfg=VERIFY_DELAY_CFG,
                storage=storage,
            )
            crawl_success = True
            print("  ✓ Crawl complete\n")
        except Exception as e:
            logger.error("Crawl failed: %s", e, exc_info=True)
            print(f"  ✗ Crawl failed: {e}")
            return False

    if not crawl_success:
        return False

    # ---- Step 4: Verify the output files ----
    print("[3/3] Verifying output files...")
    files = _check_output_files(keyword)

    passed = True
    checks: list[tuple[str, bool, str]] = []

    # Check the search results JSON
    if files["search_json"]:
        latest_json = files["search_json"][-1]
        count = _count_json_records(latest_json, "results")
        ok = count >= 1
        checks.append((
            f"Search results JSON ({latest_json.name})",
            ok,
            f"{count} records" if count >= 0 else "failed to read",
        ))
    else:
        checks.append(("Search results JSON", False, "file not found"))
        passed = False

    # Check the note details JSON
    if files["notes_json"]:
        latest_json = files["notes_json"][-1]
        count = _count_json_records(latest_json, "notes")
        ok = count >= 1
        checks.append((
            f"Note details JSON ({latest_json.name})",
            ok,
            f"{count} records" if count >= 0 else "failed to read",
        ))
        if not ok:
            passed = False
    else:
        checks.append(("Note details JSON", False, "file not found"))
        passed = False

    # Check the search results CSV
    if files["search_csv"]:
        count = _count_csv_rows(files["search_csv"])
        ok = count >= 1
        checks.append((f"Search results CSV ({files['search_csv'].name})", ok, f"{count} rows"))
        if not ok:
            passed = False
    else:
        checks.append(("Search results CSV", False, "file not found"))
        passed = False

    # Check the note details CSV
    if files["notes_csv"]:
        count = _count_csv_rows(files["notes_csv"])
        ok = count >= 1
        checks.append((f"Note details CSV ({files['notes_csv'].name})", ok, f"{count} rows"))
        if not ok:
            passed = False
    else:
        checks.append(("Note details CSV", False, "file not found"))
        passed = False

    # Check the comments CSV (only required when there are comments)
    if files["comments_csv"]:
        count = _count_csv_rows(files["comments_csv"])
        checks.append((
            f"Comments CSV ({files['comments_csv'].name})",
            count >= 0,
            f"{count} rows",
        ))
    else:
        # A missing comments CSV may just mean the notes have no comments; record it but do not fail
        checks.append(("Comments CSV", True, "no comment data (the notes may have no comments)"))

    # Print the check results
    print()
    for name, ok, detail in checks:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}: {detail}")

    # ---- Verdict ----
    print()
    if passed:
        print(f"  ✅ Phase 4 end-to-end verification passed")
        print(f"     The full crawl flow for keyword [{keyword}] works correctly")
        print(f"     Data files were written to the data/ directory")
    else:
        print(f"  ✗ Phase 4 end-to-end verification failed")
        print("    Check the detailed log output for the failed items above")
    print()

    return passed


if __name__ == "__main__":
    keyword = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_KEYWORD
    success = asyncio.run(run(keyword))
    sys.exit(0 if success else 1)

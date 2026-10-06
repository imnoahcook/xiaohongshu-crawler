"""
Phase 2 search collection verification script

Verifies the full search collection pipeline:
  1. Reuse the existing login state (login must be completed first, see verify_login.py)
  2. Run a search by keyword and extract the list of note summaries
  3. Store the results as JSON and Excel files
  4. Print a verification report

How to run:
    uv run python scripts/verify_search.py [keyword]

Examples:
    uv run python scripts/verify_search.py                  # Use the default keyword
    uv run python scripts/verify_search.py "coffee"         # Specify a keyword

Prerequisites:
    - Login completed (auth_state/state.json exists)
    - If not logged in, first run: uv run python scripts/verify_login.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.auth import is_logged_in
from src.browser import BrowserManager
from src.search import search_notes
from src.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Default keyword for verification (can be overridden by a command-line argument)
DEFAULT_KEYWORD = "coffee"
# Number of notes to collect during verification (a few is enough)
VERIFY_MAX_COUNT = 5

# Minimum expected count (anything below this is treated as abnormal)
MIN_EXPECTED_COUNT = 1


async def run(keyword: str) -> bool:
    """Run the Phase 2 search collection verification.

    Returns:
        True if verification passed, False if it failed
    """
    print("\n" + "=" * 60)
    print("  Phase 2 — Search collection verification")
    print("=" * 60)
    print(f"  Keyword: {keyword}")
    print(f"  Target count: {VERIFY_MAX_COUNT}")
    print()

    # ---- Step 1: Check the login state ----
    auth_state = Path("auth_state/state.json")
    if not auth_state.exists():
        print("  ✗ Login state file not found, please run verify_login.py to log in first")
        return False

    # ---- Step 2: Run the search collection ----
    results: list[dict] = []
    async with BrowserManager(headless=False) as bm:
        print("[1/3] Verifying login state...")
        page = await bm.new_page()
        logged_in = await is_logged_in(page)
        await page.close()

        if not logged_in:
            print("  ✗ Login state has expired, please log in again")
            return False
        print("  ✓ Login state is valid\n")

        print(f"[2/3] Searching keyword: {keyword!r}, target {VERIFY_MAX_COUNT} notes...")
        results = await search_notes(
            bm,
            keyword=keyword,
            max_count=VERIFY_MAX_COUNT,
            scroll_pause=1.5,
            scroll_interval=(1.0, 2.5),
        )

    # ---- Step 3: Print a summary of the results ----
    print(f"\n  Collected {len(results)} notes:")
    print("-" * 60)
    for i, note in enumerate(results, start=1):
        title = note.get("title") or "(no title)"
        author = note.get("author") or "(unknown author)"
        likes = note.get("likes", 0)
        note_type = note.get("note_type", "image")
        note_id = note.get("note_id", "")
        print(f"  [{i:02d}] {title[:30]:<30}  Author:{author:<12}  Likes:{likes:<6}  Type:{note_type}  ID:{note_id}")
    print("-" * 60)

    # ---- Step 4: Store the results ----
    print(f"\n[3/3] Storing results...")
    if results:
        storage_config = {
            "output_dir": "data",
            "save_raw_json": True,
            "save_xlsx": True,
        }
        storage = Storage(storage_config)
        storage.save_all(keyword, results, [])

        json_dir = Path("data/raw")
        xlsx_dir = Path("data/processed")
        json_files = list(json_dir.glob(f"*{keyword[:4]}*.json"))
        xlsx_files = list(xlsx_dir.glob("*.xlsx"))
        print(f"  data/raw/       {len(json_files)} JSON file(s)")
        print(f"  data/processed/ {len(xlsx_files)} Excel file(s)")

    # ---- Verification verdict ----
    print()
    passed = len(results) >= MIN_EXPECTED_COUNT
    if passed:
        print(f"  ✅ Phase 2 search collection verification passed ({len(results)} notes collected)")
    else:
        print(f"  ✗ Verification failed: not enough results (expected >= {MIN_EXPECTED_COUNT}, got {len(results)})")
        print("    Possible causes:")
        print("    1. The card selectors are out of date (rednote page redesign)")
        print("    2. A network problem prevented the page from loading properly")
        print("    3. A broken login state caused a redirect")
        print("    Suggestion: inspect the page DOM structure manually in headless=False mode")
    print()

    return passed


if __name__ == "__main__":
    keyword = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_KEYWORD
    success = asyncio.run(run(keyword))
    sys.exit(0 if success else 1)

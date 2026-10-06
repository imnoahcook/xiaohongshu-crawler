"""
Phase 3 note detail + comment collection verification script

Verifies the full detail collection pipeline:
  1. Reuse the existing login state (login must be completed first)
  2. Search by keyword and take a few note URLs
  3. Open each note detail page and collect details + comments
  4. Store the results as JSON and Excel files
  5. Print a verification report

How to run:
    uv run python scripts/verify_note.py [keyword]

Examples:
    uv run python scripts/verify_note.py                  # Use the default keyword
    uv run python scripts/verify_note.py "coffee"         # Specify a keyword

Prerequisites:
    - Login completed to rednote in your everyday Chrome
    - If not logged in, first run: uv run python scripts/verify_login.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.auth import is_logged_in
from src.browser import BrowserManager
from src.note import fetch_note_details
from src.search import search_notes
from src.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Default keyword for verification
DEFAULT_KEYWORD = "coffee"
# Number of search results during verification (a few is enough)
VERIFY_SEARCH_COUNT = 3
# Maximum comments per note during verification
VERIFY_MAX_COMMENTS = 5


async def run(keyword: str) -> bool:
    """Run the Phase 3 note detail + comment collection verification.

    Returns:
        True if verification passed, False if it failed
    """
    print("\n" + "=" * 60)
    print("  Phase 3 — Note detail + comment collection verification")
    print("=" * 60)
    print(f"  Keyword: {keyword}")
    print(f"  Search count: {VERIFY_SEARCH_COUNT}")
    print(f"  Max comments per note: {VERIFY_MAX_COMMENTS}")
    print()

    note_details: list[dict] = []

    async with BrowserManager() as bm:
        # ---- Step 2: Verify the login state ----
        print("[1/4] Verifying login state...")
        page = await bm.new_page()
        logged_in = await is_logged_in(page)
        await page.close()

        if not logged_in:
            print("  ✗ Login state has expired, please log in again")
            return False
        print("  ✓ Login state is valid\n")

        # ---- Step 3: Search to get note URLs ----
        print(f"[2/4] Searching keyword: {keyword!r}, target {VERIFY_SEARCH_COUNT} notes...")
        search_results = await search_notes(
            bm,
            keyword=keyword,
            max_count=VERIFY_SEARCH_COUNT,
            scroll_pause=1.5,
            scroll_interval=(1.0, 2.5),
        )

        if not search_results:
            print("  ✗ Search results are empty, cannot continue verification")
            return False

        print(f"  ✓ Found {len(search_results)} notes\n")

        # ---- Step 4: Collect note details + comments ----
        print(f"[3/4] Collecting note details + comments...")
        note_details = await fetch_note_details(
            bm,
            search_results=search_results,
            max_comments=VERIFY_MAX_COMMENTS,
            delay_range=(2.0, 4.0),
        )

    # ---- Step 5: Print a summary of the results ----
    print(f"\n  Collected {len(note_details)} note details:")
    print("-" * 70)
    for i, note in enumerate(note_details, start=1):
        title = note.get("title") or "(no title)"
        author = note.get("author") or "(unknown author)"
        likes = note.get("likes", 0)
        collects = note.get("collects", 0)
        comments = note.get("comments", [])
        content_preview = (note.get("content") or "")[:40]
        tags = note.get("tags", [])

        print(f"  [{i:02d}] {title[:35]}")
        print(f"       Author: {author}  Likes:{likes}  Collects:{collects}  Comments:{len(comments)}")
        if content_preview:
            print(f"       Content: {content_preview}...")
        if tags:
            print(f"       Tags: {', '.join(tags[:5])}")

        # Print a summary of the first 3 comments
        for j, c in enumerate(comments[:3], start=1):
            user = c.get("user_name", "anonymous")
            text = (c.get("content") or "")[:30]
            print(f"         Comment {j}: [{user}] {text}")

        print()
    print("-" * 70)

    # ---- Step 6: Store the results ----
    print("[4/4] Storing results...")
    if note_details:
        storage_config = {
            "output_dir": "data",
            "save_raw_json": True,
            "save_xlsx": True,
        }
        storage = Storage(storage_config)
        storage.save_all(keyword, search_results, note_details)

        json_dir = Path("data/raw")
        xlsx_dir = Path("data/processed")
        json_files = list(json_dir.glob(f"notes_*.json"))
        xlsx_files = list(xlsx_dir.glob("*.xlsx"))
        print(f"  data/raw/       {len(json_files)} note JSON file(s)")
        print(f"  data/processed/ {len(xlsx_files)} Excel file(s)")

    # ---- Verification verdict ----
    print()
    passed = len(note_details) >= 1
    total_comments = sum(len(n.get("comments", [])) for n in note_details)

    if passed:
        print(f"  ✅ Phase 3 verification passed ({len(note_details)} notes, {total_comments} comments)")
    else:
        print(f"  ✗ Verification failed: note detail collection failed")
        print("    Possible causes:")
        print("    1. The detail page DOM selectors are out of date (rednote page redesign)")
        print("    2. Page load timeout or network error")
        print("    3. A broken login state caused a redirect")
    print()

    return passed


if __name__ == "__main__":
    keyword = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_KEYWORD
    success = asyncio.run(run(keyword))
    sys.exit(0 if success else 1)

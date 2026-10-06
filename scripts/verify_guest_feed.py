"""
Guest feed smoke test (no login required).

rednote.com shows the explore feed on its home page to logged-out visitors,
and the feed uses the same note cards as the search results page. This script
loads the home page and runs the search-card parser over those cards, which
checks the browser stack, the card selectors and the parser against the live
site without needing an account.

Search, note details and comments all require login; verify those with
verify_search.py / verify_note.py after running verify_login.py.

Usage:
    uv run python scripts/verify_guest_feed.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.browser import BrowserManager
from src.parser import parse_search_card
from src.site import HOME_URL

CARD_SELECTOR = "section.note-item"
SAMPLE_SIZE = 5


async def run() -> bool:
    async with BrowserManager() as bm:
        page = await bm.new_page()
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_selector(CARD_SELECTOR, timeout=30_000)

        cards = await page.query_selector_all(CARD_SELECTOR)
        parsed = [await parse_search_card(card) for card in cards]
        notes = [note for note in parsed if note]

    print(f"{HOME_URL}: {len(cards)} cards found, {len(notes)} parsed")
    print(json.dumps(notes[:SAMPLE_SIZE], ensure_ascii=False, indent=2))

    complete = [n for n in notes if n["note_id"] and n["author"] and n["cover_url"]]
    ok = len(notes) > 0 and len(complete) == len(notes)
    print("PASS" if ok else "FAIL: some cards are missing note_id / author / cover_url")
    return ok


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run()) else 1)

"""
Login state verification script

Verifies two scenarios:
  Scenario A — first login: when auth_state/state.json does not exist, guide a manual login and save the login state
  Scenario B — reuse the login state: when auth_state/state.json exists, load it and check that it is still valid

Usage:
    uv run python scripts/verify_login.py

To force a fresh login (clearing the existing login state):
    rm auth_state/state.json
    uv run python scripts/verify_login.py
"""

import asyncio
import datetime
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.auth import is_logged_in, wait_for_manual_login
from src.browser import AUTH_STATE_PATH, BrowserManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def run() -> None:
    print("\n" + "=" * 60)
    print("  Login state verification")
    print("=" * 60)

    state_exists = AUTH_STATE_PATH.exists()

    if state_exists:
        mtime = AUTH_STATE_PATH.stat().st_mtime
        ts = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  Found an existing login state file: {AUTH_STATE_PATH}")
        print(f"  File modified at: {ts}")
        print(f"\n  Scenario B — verify login state reuse\n")
    else:
        print(f"  Login state file not found: {AUTH_STATE_PATH}")
        print(f"\n  Scenario A — guided manual first login\n")

    async with BrowserManager(headless=False) as bm:
        page = await bm.new_page()

        if state_exists:
            # Scenario B: check whether the existing login state is still valid
            logged_in = await is_logged_in(page)
            if logged_in:
                print("\n  ✓ Login state reused successfully; no need to log in again")
                print(f"    Current page: {page.url}")

                # Try to extract the current user's profile path (the profile link in the sidebar)
                try:
                    user_el = await page.query_selector("a[href*='/user/profile']:not([href*='explore_feed'])")
                    href = await user_el.get_attribute("href") if user_el else None
                    if href:
                        print(f"    User profile path: {href.split('?')[0]}")
                except Exception:
                    pass
            else:
                print("\n  ✗ Login state has expired (cookies expired or the account changed)")
                print("    Delete auth_state/state.json and rerun this script to log in manually")

        else:
            # Scenario A: guide a manual login
            success = await wait_for_manual_login(page)
            if success:
                await asyncio.sleep(1)
                await bm.save_state()
                print(f"\n  ✓ First login succeeded")
                print(f"    Login state saved to: {AUTH_STATE_PATH}")
                print(f"    It will be reused automatically on the next run; no need to log in again")
            else:
                print(f"\n  ✗ Login timed out; login was not completed")

        await page.close()

    print()


if __name__ == "__main__":
    asyncio.run(run())

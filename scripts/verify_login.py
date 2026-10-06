"""
Login script

Checks whether the browser session is logged in to rednote; if it is not, opens
the login page and waits for you to log in (QR code or phone number + SMS code).

The crawler works in your everyday Chrome, so if you are already logged in to
rednote there, there is nothing to do.

Usage:
    uv run python scripts/verify_login.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.auth import is_logged_in, wait_for_manual_login
from src.browser import BrowserManager

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

    async with BrowserManager() as bm:
        page = await bm.new_page()

        if await is_logged_in(page):
            print("\n  ✓ Already logged in; no need to log in again")
        elif await wait_for_manual_login(page):
            await bm.save_state()
            print("\n  ✓ Login succeeded")
            print("    It will be reused automatically on the next run; no need to log in again")
        else:
            print("\n  ✗ Login was not completed")

        await page.close()

    print()


if __name__ == "__main__":
    asyncio.run(run())

"""
Login and session management module

Responsibilities:
  - Check whether the current login state is valid
  - Guide the user through manual login (QR code / phone number + SMS code)
  - Save storage_state after a successful login so later crawls can reuse it

Flow:
    Start → open the home page → check the login state
      ├── valid → return immediately
      └── invalid → open the login page → wait for manual login → confirm success → save the login state
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Page, Response

from src.browser import BrowserManager
from src.site import EXPLORE_URL, HOME_URL

logger = logging.getLogger(__name__)

REDNOTE_HOME = HOME_URL
REDNOTE_LOGIN = EXPLORE_URL

# The web app asks this endpoint who the current user is on every page load.
# Its "guest" field is the source of truth for the login state: the login button
# is not reliable, because the standalone /login page does not render it at all.
_USER_ME_PATH = "/api/sns/web/v2/user/me"

# Manual login wait timeout (seconds)
LOGIN_WAIT_TIMEOUT = 300

# How long to wait for the home page to report the login state (seconds)
_USER_ME_WAIT_SECONDS = 15


def _watch_login_state(page: Page) -> dict:
    """Record the login state reported by every user/me response on the page.

    Returns:
        A dict whose "logged_in" entry is None until a response arrives, then True / False
    """
    state: dict = {"logged_in": None}

    async def on_response(response: Response) -> None:
        if _USER_ME_PATH not in response.url:
            return
        try:
            data = (await response.json()).get("data") or {}
        except Exception:
            return
        if "guest" in data:
            state["logged_in"] = not data["guest"]

    page.on("response", on_response)
    return state


async def is_logged_in(page: Page) -> bool:
    """Open the home page and check whether the current context's login state is valid.

    Detection logic: the home page calls user/me while loading; the session is
    logged in when that response says the user is not a guest.
    """
    state = _watch_login_state(page)
    try:
        await page.goto(REDNOTE_HOME, wait_until="domcontentloaded", timeout=30_000)
        for _ in range(_USER_ME_WAIT_SECONDS * 2):
            if state["logged_in"] is not None:
                break
            await asyncio.sleep(0.5)

        if state["logged_in"] is None:
            logger.info("No user/me response seen; treating as logged out")
            return False

        logger.info("Login state is %s", "valid" if state["logged_in"] else "logged out")
        return state["logged_in"]

    except Exception as e:
        logger.warning("Login state check failed: %s", e)
        return False


async def wait_for_manual_login(page: Page) -> bool:
    """Open the login page and wait for the user to log in manually.

    Args:
        page: Playwright Page object

    Returns:
        True if login succeeded, False if it timed out
    """
    state = _watch_login_state(page)
    await page.goto(REDNOTE_LOGIN, wait_until="domcontentloaded", timeout=30_000)

    print("\n" + "=" * 60)
    print("Log in manually in the browser (scan the QR code with the rednote app, or use your phone number + SMS code)")
    print(f"Timeout: {LOGIN_WAIT_TIMEOUT} seconds")
    print("=" * 60 + "\n")

    # The app calls user/me again once the login goes through
    for _ in range(LOGIN_WAIT_TIMEOUT):
        if state["logged_in"]:
            logger.info("Manual login succeeded")
            return True
        if page.is_closed():
            logger.error("The login tab was closed before login completed")
            return False
        await asyncio.sleep(1)

    logger.error("Timed out waiting for manual login (%d seconds)", LOGIN_WAIT_TIMEOUT)
    return False


async def ensure_logged_in(bm: BrowserManager) -> bool:
    """Ensure the context in the BrowserManager has a valid login state.

    If the browser is already logged in, reuse that; otherwise guide a manual login.

    Args:
        bm: an initialized BrowserManager instance

    Returns:
        True if the login state is ready, False if login failed
    """
    page = await bm.new_page()

    try:
        if await is_logged_in(page):
            return True

        # Not logged in; guide a manual login
        if not await wait_for_manual_login(page):
            return False
        await bm.save_state()
        return True
    finally:
        await page.close()

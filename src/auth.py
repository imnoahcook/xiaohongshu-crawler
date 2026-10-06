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

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.browser import BrowserManager
from src.site import EXPLORE_URL, HOME_URL

logger = logging.getLogger(__name__)

REDNOTE_HOME = HOME_URL
REDNOTE_LOGIN = EXPLORE_URL

# Class of the "log in" button present on the page when logged out (visible after React renders)
# How to verify: open the home page headless; .side-bar-component.login-btn in the DOM means logged out
# If a rednote redesign breaks this selector, update it here
_LOGIN_BTN_SELECTOR = ".side-bar-component.login-btn"

# Manual login wait timeout (seconds)
LOGIN_WAIT_TIMEOUT = 300


async def is_logged_in(page: Page) -> bool:
    """Open the home page and check whether the current context's login state is valid.

    Detection logic:
      - Logged out → a .login-btn element exists after the page renders
      - Logged in → no .login-btn element exists
    """
    try:
        await page.goto(REDNOTE_HOME, wait_until="domcontentloaded", timeout=30_000)
        # Wait for React to finish the first render (the login button and the user info area both need JS)
        await asyncio.sleep(2)

        # If the page did not render (e.g. it was blocked), treat it as logged out
        body_len: int = await page.evaluate("document.body.innerText.length")
        if body_len < 100:
            logger.info("Page content is too short and may not have rendered; treating as logged out")
            return False

        login_btn = await page.query_selector(_LOGIN_BTN_SELECTOR)
        if login_btn is not None:
            logger.info("Login button found; not logged in")
            return False

        logger.info("No login button found; login state is valid")
        return True

    except Exception as e:
        logger.warning("Login state check failed: %s", e)
        return False


async def wait_for_manual_login(page: Page) -> bool:
    """Open the login page and wait for the user to log in manually.

    Args:
        page: Playwright Page object with the stealth patches applied

    Returns:
        True if login succeeded, False if it timed out
    """
    await page.goto(REDNOTE_LOGIN, wait_until="domcontentloaded", timeout=30_000)

    print("\n" + "=" * 60)
    print("Log in manually in the browser (scan the QR code with the rednote app, or use your phone number + SMS code)")
    print(f"Timeout: {LOGIN_WAIT_TIMEOUT} seconds")
    print("=" * 60 + "\n")

    try:
        # Wait for the login button to disappear: once it is gone, login is complete
        await page.wait_for_selector(
            _LOGIN_BTN_SELECTOR,
            state="hidden",
            timeout=LOGIN_WAIT_TIMEOUT * 1_000,
        )
        logger.info("Manual login succeeded")
        return True
    except PlaywrightTimeoutError:
        logger.error("Timed out waiting for manual login (%d seconds)", LOGIN_WAIT_TIMEOUT)
        return False


async def ensure_logged_in(bm: BrowserManager) -> bool:
    """Ensure the context in the BrowserManager has a valid login state.

    If a login state already exists, verify and reuse it; otherwise guide a manual login and save the login state.

    Args:
        bm: an initialized BrowserManager instance

    Returns:
        True if the login state is ready, False if login failed
    """
    page = await bm.new_page()

    try:
        if await is_logged_in(page):
            return True

        # Login state is invalid; guide a manual login
        success = await wait_for_manual_login(page)
        if not success:
            return False

        # Wait for the page to settle, then save the login state
        await asyncio.sleep(1)
        await bm.save_state()
        return True
    finally:
        await page.close()

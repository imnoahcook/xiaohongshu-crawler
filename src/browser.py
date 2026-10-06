"""
Browser management module

Responsibilities:
  - Provide the browser the crawler works in, behind one async context manager
  - Keep the rednote login available across runs

Two modes, selected with the REDNOTE_BROWSER environment variable:
  - "stealth" (default): launch a dedicated Chromium with a generated fingerprint
    and stealth patches. The login is saved to auth_state/state.json and reloaded
    on the next start. Set REDNOTE_HEADLESS=1 to hide the window.
  - "chrome": attach over CDP to the Chrome the user already has open and work in
    new tabs there (see src/chrome.py). Chrome asks the user to allow each new
    connection; the window and its other tabs are left alone on exit.

Usage:
    async with BrowserManager() as bm:
        page = await bm.new_page()
        # ... crawling logic
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Playwright,
    async_playwright,
)

from src.chrome import ChromeNotAvailableError, devtools_ws_url
from src.stealth import apply_stealth_to_page, build_stealth, generate_context_options

logger = logging.getLogger(__name__)

AUTH_STATE_PATH = Path(__file__).resolve().parent.parent / "auth_state" / "state.json"

# Chrome shows an "Allow remote debugging?" prompt on connect; leave time to click it
_CONNECT_TIMEOUT_MS = 120_000


def _attach_to_chrome() -> bool:
    return os.environ.get("REDNOTE_BROWSER", "stealth").lower() == "chrome"


class BrowserManager:
    """Browser lifecycle manager (async context manager)."""

    def __init__(self) -> None:
        self._attached = _attach_to_chrome()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._pages: list[Page] = []
        self._stealth = None

    async def __aenter__(self) -> "BrowserManager":
        self._playwright = await async_playwright().start()
        try:
            if self._attached:
                await self._attach()
            else:
                await self._launch()
        except BaseException:
            await self._playwright.stop()
            raise
        return self

    async def _attach(self) -> None:
        ws_url = devtools_ws_url()
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(
                ws_url, timeout=_CONNECT_TIMEOUT_MS
            )
        except PlaywrightError as e:
            raise ChromeNotAvailableError(
                f"Could not connect to Chrome at {ws_url}. Make sure Chrome is running "
                'and click "Allow" on its remote debugging prompt.'
            ) from e
        # The default context is the user's own profile, with their cookies and logins
        self._context = self._browser.contexts[0]
        logger.info("Attached to Chrome at %s", ws_url)

    async def _launch(self) -> None:
        headless = os.environ.get("REDNOTE_HEADLESS", "") not in ("", "0")
        # One fingerprint per launch, so it stays consistent within a session
        context_options = generate_context_options()
        fingerprint = context_options.pop("_fingerprint")
        self._stealth = build_stealth(fingerprint.navigator.userAgent)

        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        if AUTH_STATE_PATH.exists():
            logger.info("Loading saved login state: %s", AUTH_STATE_PATH)
            context_options["storage_state"] = str(AUTH_STATE_PATH)
        self._context = await self._browser.new_context(**context_options)
        logger.info("Browser started (headless=%s)", headless)

    async def __aexit__(self, *_args) -> None:
        if self._attached:
            # Close only the tabs this manager opened; Chrome itself stays open
            for page in self._pages:
                if not page.is_closed():
                    await page.close()
            logger.info("Detached from Chrome (window left open)")
        else:
            try:
                await self.save_state()
            except PlaywrightError as e:
                logger.warning("Could not save the login state: %s", e)
            await self._context.close()
            await self._browser.close()
            logger.info("Browser closed")
        await self._playwright.stop()

    async def new_page(self) -> Page:
        """Open and return a new tab."""
        page = await self._context.new_page()
        self._pages.append(page)
        if self._stealth is not None:
            await apply_stealth_to_page(page, self._stealth)
        return page

    async def save_state(self) -> None:
        """Persist the login (cookies / localStorage). A no-op when attached to Chrome, which keeps its own."""
        if self._attached:
            return
        AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(AUTH_STATE_PATH))
        logger.info("Login state saved: %s", AUTH_STATE_PATH)

    @property
    def context(self) -> Optional[BrowserContext]:
        return self._context

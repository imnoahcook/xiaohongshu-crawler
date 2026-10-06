"""
Browser management module

Responsibilities:
  - Attach Playwright to the Chrome the user already has open (see src/chrome.py)
  - Open the crawler's tabs in that Chrome's default context, so they share the
    user's existing rednote login
  - Provide a single async context manager interface

The crawler never launches or closes a browser. On exit it closes only the tabs
it opened; the Chrome window and every other tab are left alone.

Usage:
    async with BrowserManager() as bm:
        page = await bm.new_page()
        # ... crawling logic
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

# Chrome shows an "Allow remote debugging?" prompt on connect; leave time to click it
_CONNECT_TIMEOUT_MS = 60_000


class BrowserManager:
    """Connection to the user's everyday Chrome (async context manager)."""

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._pages: list[Page] = []

    async def __aenter__(self) -> "BrowserManager":
        ws_url = devtools_ws_url()
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(
                ws_url, timeout=_CONNECT_TIMEOUT_MS
            )
        except PlaywrightError as e:
            await self._playwright.stop()
            raise ChromeNotAvailableError(
                f"Could not connect to Chrome at {ws_url}. Make sure Chrome is running "
                'and click "Allow" on its remote debugging prompt.'
            ) from e

        # The default context is the user's own profile, with their cookies and logins
        self._context = self._browser.contexts[0]
        logger.info("Attached to Chrome at %s", ws_url)
        return self

    async def __aexit__(self, *_args) -> None:
        # Close only the tabs this manager opened; Chrome itself stays open
        for page in self._pages:
            if not page.is_closed():
                await page.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Detached from Chrome (window left open)")

    async def new_page(self) -> Page:
        """Open and return a new tab in the user's Chrome."""
        page = await self._context.new_page()
        self._pages.append(page)
        return page

    @property
    def context(self) -> Optional[BrowserContext]:
        return self._context

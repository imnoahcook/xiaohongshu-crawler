"""
Browser management module

Responsibilities:
  - Manage the lifecycle of the Playwright browser instance
  - Integrate stealth anti-detection (fingerprint injection + stealth patches)
  - Manage the browser context and saving/loading the login state
  - Provide a single async context manager interface

Usage:
    async with BrowserManager(headless=False) as bm:
        page = await bm.new_page()
        # ... crawling logic
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from src.stealth import apply_stealth_to_page, build_stealth, generate_context_options

logger = logging.getLogger(__name__)

AUTH_STATE_PATH = Path("auth_state/state.json")


class BrowserManager:
    """Playwright browser lifecycle manager (async context manager).

    Each instance generates a new browser fingerprint so the fingerprint never becomes fixed.
    """

    def __init__(self, headless: bool = False) -> None:
        self.headless = headless
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

        # Generate the fingerprint at construction time so it stays consistent within one session
        ctx_opts = generate_context_options()
        self._fingerprint = ctx_opts.pop("_fingerprint")
        self._context_options = ctx_opts
        self._stealth = build_stealth(self._fingerprint.navigator.userAgent)

    async def __aenter__(self) -> "BrowserManager":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        logger.info("Browser started (headless=%s)", self.headless)
        await self._create_context()
        return self

    async def __aexit__(self, *_args) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser closed")

    async def _create_context(self) -> None:
        """Create a browser context with the fingerprint injected, loading the saved login state if one exists."""
        if AUTH_STATE_PATH.exists():
            logger.info("Login state file found, loading: %s", AUTH_STATE_PATH)
            self._context = await self._browser.new_context(
                **self._context_options,
                storage_state=str(AUTH_STATE_PATH),
            )
        else:
            self._context = await self._browser.new_context(**self._context_options)

        # Stealth patches: applied automatically to every page opened later in this context
        self._context.on("page", self._on_new_page)

    async def _on_new_page(self, page: Page) -> None:
        """Apply the stealth patches automatically when a new page opens in the context."""
        await apply_stealth_to_page(page, self._stealth)

    async def new_page(self) -> Page:
        """Create and return a new page with the stealth patches applied."""
        page = await self._context.new_page()
        # The on("page") event only fires for context.new_page(); apply again explicitly here to be sure
        await apply_stealth_to_page(page, self._stealth)
        return page

    async def save_state(self) -> None:
        """Save the current context's cookies / localStorage to a file (persists the login state)."""
        AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(AUTH_STATE_PATH))
        logger.info("Login state saved: %s", AUTH_STATE_PATH)

    @property
    def context(self) -> Optional[BrowserContext]:
        return self._context

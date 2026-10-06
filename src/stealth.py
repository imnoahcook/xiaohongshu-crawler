"""
Anti-detection configuration module

Integrates playwright-stealth and browserforge for two layers of anti-detection:
  Layer 1 (environment) — playwright-stealth: removes automation traces such as navigator.webdriver
  Layer 2 (fingerprint) — browserforge: generates fingerprints consistent with a real browser
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from browserforge.fingerprints import Browser, FingerprintGenerator
from playwright_stealth import Stealth

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page


# Chrome 120+ fingerprints are close to the Chromium 145 used by Playwright 1.58, giving the best compatibility
_fingerprint_generator = FingerprintGenerator(
    browser=Browser(name="chrome", min_version=120),
    os="macos",
)


def build_stealth(user_agent: str) -> Stealth:
    """Build a Stealth instance from the fingerprint UA, overriding the default Win32 platform with MacIntel."""
    return Stealth(
        # Keep all default patches enabled
        navigator_platform_override="MacIntel",
        navigator_user_agent_override=user_agent,
        navigator_vendor_override="Google Inc.",
        # Disable the chrome_runtime patch: in headed mode Chrome Runtime already exists, so there is nothing to fake
        chrome_runtime=False,
    )


def generate_context_options() -> dict:
    """Generate browser context options containing a realistic browser fingerprint.

    Each call generates a new random fingerprint so a fixed fingerprint cannot be linked and tracked.

    Returns:
        A dict of arguments that can be passed straight to browser.new_context(**options).
    """
    fp = _fingerprint_generator.generate()

    return {
        "user_agent": fp.navigator.userAgent,
        "viewport": {
            "width": fp.screen.width,
            "height": fp.screen.height,
        },
        "screen": {
            "width": fp.screen.width,
            "height": fp.screen.height,
        },
        "locale": fp.navigator.language or "en-US",
        "color_scheme": "light",
        # Return the fingerprint itself so the UA can be reused when building Stealth
        "_fingerprint": fp,
    }


async def apply_stealth_to_page(page: "Page", stealth: Stealth) -> None:
    """Apply the stealth patches to a single page (must be called for every new page)."""
    await stealth.apply_stealth_async(page)

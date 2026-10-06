"""
Anti-detection verification script

Opens the bot.sannysoft.com detection site, extracts each test result, and prints a summary report.
Also saves a screenshot to data/verify_stealth.png for manual inspection.

Usage:
    uv run python scripts/verify_stealth.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add the project root to sys.path so this script can be run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.browser import BrowserManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

TEST_URL = "https://bot.sannysoft.com"
SCREENSHOT_PATH = Path("data/verify_stealth.png")

# DOM structure of each test item on bot.sannysoft.com:
#   <tr> <td>test name</td> <td class="result passed|result failed">result text</td> </tr>
# The class is "result passed" or "result failed" (a compound class with a space)
_RESULTS_SELECTOR = "tr:has(td.result)"


async def run() -> None:
    Path("data").mkdir(exist_ok=True)

    print("\n" + "=" * 60)
    print("  Anti-detection verification — bot.sannysoft.com")
    print("=" * 60)
    print(f"Target URL: {TEST_URL}")
    print(f"Screenshot: {SCREENSHOT_PATH}\n")

    async with BrowserManager(headless=False) as bm:
        page = await bm.new_page()

        logger.info("Opening %s …", TEST_URL)
        # Use load to avoid networkidle timing out on this site
        await page.goto(TEST_URL, wait_until="load", timeout=30_000)

        # Wait for all the in-page JS detection scripts to finish (the page fills in results dynamically via JS)
        await asyncio.sleep(5)

        # Screenshot
        await page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
        logger.info("Screenshot saved: %s", SCREENSHOT_PATH)

        # Extract the test results
        rows = await page.query_selector_all(_RESULTS_SELECTOR)
        results: list[dict] = []

        for row in rows:
            cells = await row.query_selector_all("td")
            if len(cells) < 2:
                continue

            name = (await cells[0].inner_text()).strip()
            value_el = cells[1]
            class_attr = (await value_el.get_attribute("class") or "").lower()
            value = (await value_el.inner_text()).strip()

            if "passed" in class_attr:
                status = "PASS"
            elif "failed" in class_attr:
                status = "FAIL"
            else:
                status = "INFO"

            results.append({"name": name, "value": value, "status": status})

        # Print the report
        _print_report(results)


def _print_report(results: list[dict]) -> None:
    if not results:
        print("\n[!] Could not extract any test results; check the screenshot manually\n")
        return

    passed = [r for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] == "FAIL"]
    info   = [r for r in results if r["status"] == "INFO"]

    print("\n─── Details " + "─" * 46)
    col_w = max(len(r["name"]) for r in results) + 2

    for r in results:
        icon = {"PASS": "✓", "FAIL": "✗", "INFO": "·"}[r["status"]]
        color = {"PASS": "\033[32m", "FAIL": "\033[31m", "INFO": "\033[0m"}[r["status"]]
        reset = "\033[0m"
        print(f"  {color}{icon}{reset}  {r['name']:<{col_w}} {r['value']}")

    print("\n─── Summary " + "─" * 50)
    print(f"  Passed: {len(passed)}  Failed: {len(failed)}  Info: {len(info)}")

    if failed:
        print("\n  ⚠ The following items failed and may be detected as automation:")
        for r in failed:
            print(f"    - {r['name']}: {r['value']}")
    else:
        print("\n  All checks passed; the stealth configuration works")

    print()


if __name__ == "__main__":
    asyncio.run(run())

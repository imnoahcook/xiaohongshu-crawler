"""
rednote data crawler — main entry point

Full crawl flow:
  1. Load the config (config/settings.yaml)
  2. Initialize the browser (BrowserManager + anti-detection)
  3. Make sure the login state is ready (reuse it or log in manually)
  4. Loop over the keyword list:
     a. Search → collect the list of note summaries
     b. Collect each note's details + comments
     c. Save all the data (JSON + Excel)
  5. Random delay between keywords to mimic human behavior

Usage:
    uv run python main.py
"""

from __future__ import annotations

import asyncio
import logging
import random
import sys
from pathlib import Path

import yaml

from src.auth import ensure_logged_in
from src.browser import BrowserManager
from src.note import fetch_note_details
from src.search import search_notes
from src.storage import Storage

# ---- Logging setup ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config/settings.yaml") -> dict:
    """Load the YAML config file.

    Args:
        path: config file path (relative to the project root)

    Returns:
        The config dict

    Raises:
        SystemExit: exits if the config file is missing or cannot be parsed
    """
    config_path = Path(path)
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)
    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        logger.info("Config file loaded: %s", config_path)
        return config
    except yaml.YAMLError as e:
        logger.error("Failed to parse config file: %s", e)
        sys.exit(1)


async def crawl_keyword(
    bm: BrowserManager,
    keyword: str,
    crawler_cfg: dict,
    delay_cfg: dict,
    storage: Storage,
) -> None:
    """Full crawl flow for a single keyword: search → details → comments → storage.

    Args:
        bm: an initialized, logged-in BrowserManager instance
        keyword: search keyword
        crawler_cfg: the crawler section of settings.yaml
        delay_cfg: the delay section of settings.yaml
        storage: Storage instance
    """
    logger.info("=" * 60)
    logger.info("Starting crawl for keyword: %s", keyword)
    logger.info("=" * 60)

    max_notes = crawler_cfg.get("max_notes_per_keyword", 20)
    max_comments = crawler_cfg.get("max_comments_per_note", 20)
    scroll_pause = crawler_cfg.get("scroll_pause", 1.5)
    scroll_interval = tuple(delay_cfg.get("scroll_interval", [1.0, 3.0]))
    between_notes = tuple(delay_cfg.get("between_notes", [2.0, 5.0]))

    # ---- Step 1: Search ----
    logger.info("[Step 1/2] Searching for notes (keyword: %s, target: %d)", keyword, max_notes)
    search_results = await search_notes(
        bm,
        keyword=keyword,
        max_count=max_notes,
        scroll_pause=scroll_pause,
        scroll_interval=scroll_interval,
    )

    if not search_results:
        logger.warning("No search results; skipping keyword: %s", keyword)
        return

    logger.info("Search complete: got %d note summaries", len(search_results))

    # ---- Step 2: Collect details + comments ----
    logger.info(
        "[Step 2/2] Collecting note details + comments (%d notes, up to %d comments each)",
        len(search_results),
        max_comments,
    )
    note_details = await fetch_note_details(
        bm,
        search_results=search_results,
        max_comments=max_comments,
        delay_range=between_notes,
        scroll_pause=scroll_pause,
        scroll_interval=scroll_interval,
    )

    # ---- Save the data (JSON + Excel) ----
    storage.save_all(keyword, search_results, note_details)

    # Tally the results of this crawl
    total_comments = sum(len(note.get("comments", [])) for note in note_details)
    logger.info(
        "Keyword [%s] done: %d notes, %d comments",
        keyword,
        len(note_details),
        total_comments,
    )


async def main() -> None:
    """Main function: load config → initialize → log in → crawl each keyword."""
    config = load_config()

    crawler_cfg: dict = config.get("crawler", {})
    delay_cfg: dict = config.get("delay", {})
    storage_cfg: dict = config.get("storage", {})

    keywords: list[str] = crawler_cfg.get("keywords", [])
    if not keywords:
        logger.error("No keywords set in the config file (crawler.keywords); exiting")
        sys.exit(1)

    between_searches = tuple(delay_cfg.get("between_searches", [3.0, 8.0]))

    logger.info("rednote data crawler starting")
    logger.info("Keywords (%d): %s", len(keywords), keywords)

    # Initialize storage
    storage = Storage(storage_cfg)

    # Initialize the browser
    async with BrowserManager() as bm:
        # Make sure the login state is ready
        logger.info("Checking login status...")
        logged_in = await ensure_logged_in(bm)
        if not logged_in:
            logger.error("Login failed; exiting")
            sys.exit(1)

        logger.info("Login state ready; starting the crawl")

        # Loop over the keywords
        for idx, keyword in enumerate(keywords):
            try:
                await crawl_keyword(
                    bm,
                    keyword=keyword,
                    crawler_cfg=crawler_cfg,
                    delay_cfg=delay_cfg,
                    storage=storage,
                )
            except Exception as e:
                logger.error("Keyword [%s] crawl failed: %s", keyword, e, exc_info=True)

            # Random delay between keywords (not needed after the last one)
            if idx < len(keywords) - 1:
                delay = random.uniform(*between_searches)
                logger.info(
                    "Waiting %.1f seconds before the next keyword [%s]...",
                    delay,
                    keywords[idx + 1],
                )
                await asyncio.sleep(delay)

    logger.info("=" * 60)
    logger.info("All keywords crawled! Processed %d keywords", len(keywords))
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

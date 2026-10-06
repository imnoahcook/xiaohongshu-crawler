"""
Data parsing module

Responsibilities:
  - Convert Playwright DOM elements into structured Python data
  - Normalize count formats ("1.2万" → 12000; rednote renders Chinese units even on the English UI)
  - Apply consistent defaults for missing fields
  - Clean text (strip extra whitespace)

Scope:
  - Search result card parsing (Phase 2)
  - Note detail page parsing (Phase 3)
  - Comment section parsing (Phase 3)
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import ElementHandle, Page

from src.site import BASE_URL

logger = logging.getLogger(__name__)

# URL prefix for rednote note detail pages
_NOTE_BASE_URL = BASE_URL


def normalize_count(text: str) -> int:
    """Convert count text to an integer.

    rednote renders counts with Chinese units ("万" = 10,000, "亿" = 100,000,000)
    even on the English UI, so those literals are matched here.

    Supported formats:
      - "1.2万" → 12000
      - "3.5w" → 35000
      - "324" → 324
      - "" / None → 0

    Args:
        text: Raw text string

    Returns:
        The integer value, or 0 if parsing fails
    """
    if not text:
        return 0

    text = text.strip().replace(",", "").rstrip("+")

    # Match "1.2万" or "1.2w" (case-insensitive); 万/w is the site's unit for 10,000
    match = re.match(r"^([\d.]+)\s*[万wW]$", text)
    if match:
        try:
            return int(float(match.group(1)) * 10_000)
        except ValueError:
            return 0

    # English suffixes used on rednote.com: "1.2K" / "3.4M" / "1B"
    match = re.match(r"^([\d.]+)\s*([kKmMbB])$", text)
    if match:
        multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[match.group(2).lower()]
        try:
            return int(float(match.group(1)) * multiplier)
        except ValueError:
            return 0

    # "1.2亿" → 120000000 (亿 is the site's unit for 100,000,000)
    match = re.match(r"^([\d.]+)\s*亿$", text)
    if match:
        try:
            return int(float(match.group(1)) * 100_000_000)
        except ValueError:
            return 0

    # Plain number
    try:
        return int(float(text))
    except ValueError:
        return 0


async def parse_search_card(card: "ElementHandle") -> dict | None:
    """Parse a search result card element into structured note summary data.

    Extracts from a single card DOM element:
      - note_id: unique note ID (last URL segment)
      - title: note title (may be empty for image-only notes)
      - author: author nickname
      - author_id: author ID (from the user profile URL)
      - cover_url: cover image URL
      - likes: like count (integer)
      - note_url: full note detail URL (prefers the /explore/ path)
      - note_type: note type ("video" / "image")
      - publish_time: publish time (e.g. "2025-12-05")

    Args:
        card: ElementHandle of a single search result card

    Returns:
        A dict with the fields above, or None if parsing fails
    """
    try:
        # ---- Note URL and ID ----
        # A card contains two kinds of links:
        #   1. A hidden <a href="/explore/{note_id}"> (no token; navigating to it directly 404s)
        #   2. The cover <a class="cover" href="/search_result/{note_id}?xsec_token=...">
        # Strategy: take note_id from the hidden link and xsec_token from the cover link,
        #        then build /explore/{note_id}?xsec_token=...&xsec_source=pc_search
        note_url: str = ""
        note_id: str = ""
        xsec_token: str = ""

        # Extract note_id from the hidden /explore/ link
        explore_anchor = await card.query_selector(
            'a[href*="/explore/"], a[href*="/discovery/item/"]'
        )
        if explore_anchor:
            href = await explore_anchor.get_attribute("href") or ""
            if href:
                note_id = href.split("?")[0].rstrip("/").split("/")[-1]

        # Extract xsec_token from the cover <a class="cover"> link
        cover_anchor = await card.query_selector("a.cover")
        if cover_anchor:
            cover_href = await cover_anchor.get_attribute("href") or ""
            # Format: /search_result/{note_id}?xsec_token=...&xsec_source=
            token_match = re.search(r"xsec_token=([^&]+)", cover_href)
            if token_match:
                xsec_token = token_match.group(1)
            # If the hidden link yielded no note_id, fall back to the cover link
            if not note_id:
                note_id = cover_href.split("?")[0].rstrip("/").split("/")[-1]

        if not note_id:
            logger.warning("Card has no note_id, skipping")
            return None

        # Build the full URL (with xsec_token to avoid 403/404 blocks)
        if xsec_token:
            note_url = (
                f"{_NOTE_BASE_URL}/explore/{note_id}"
                f"?xsec_token={xsec_token}&xsec_source=pc_search"
            )
        else:
            note_url = f"{_NOTE_BASE_URL}/explore/{note_id}"

        # ---- Cover image ----
        # The cover <img> is inside <a class="cover">; exclude the author avatar (.author-avatar)
        cover_url: str = ""
        img_el = await card.query_selector("a.cover img")
        if img_el is None:
            img_el = await card.query_selector("img:not(.author-avatar)")
        if img_el:
            cover_url = (
                await img_el.get_attribute("data-src")
                or await img_el.get_attribute("src")
                or ""
            )

        # ---- Title ----
        # Actual structure: .footer > a.title > span (image-only notes may have no title element)
        title: str = ""
        for sel in (
            ".footer a.title span",         # exact match: span under a.title inside footer
            ".footer a.title",               # text of a.title itself
            ".footer .title span",           # fallback: span under .title
            ".footer .title",                # fallback: .title itself
            "a.title span",                  # when there is no .footer wrapper
            "a.title",
        ):
            title_el = await card.query_selector(sel)
            if title_el:
                title = (await title_el.inner_text()).strip()
                if title:
                    break

        # ---- Author info ----
        # Actual structure: .card-bottom-wrapper > a.author > .name-time-wrapper > .name
        author: str = ""
        author_id: str = ""
        for sel in (
            ".card-bottom-wrapper .author .name",   # exact match
            ".card-bottom-wrapper .name",            # fallback
            ".author-wrapper .name",                 # legacy structure
            ".author .name",                         # generic fallback
        ):
            author_el = await card.query_selector(sel)
            if author_el:
                author = (await author_el.inner_text()).strip()
                if author:
                    break

        # Extract author_id from the user profile link
        # Actual structure: a.author[href*='/user/profile/{id}?...']
        for sel in (
            ".card-bottom-wrapper a.author[href*='/user/profile/']",
            "a.author[href*='/user/profile/']",
            "a[href*='/user/profile/']",
        ):
            user_anchor = await card.query_selector(sel)
            if user_anchor:
                user_href = await user_anchor.get_attribute("href") or ""
                parts = user_href.split("/user/profile/")
                if len(parts) == 2:
                    author_id = parts[1].split("?")[0].rstrip("/")
                    break

        # ---- Publish time ----
        # Actual structure: .name-time-wrapper > .time
        publish_time: str = ""
        for sel in (".name-time-wrapper .time", ".time"):
            time_el = await card.query_selector(sel)
            if time_el:
                publish_time = (await time_el.inner_text()).strip()
                if publish_time:
                    break

        # ---- Like count ----
        likes: int = 0
        for sel in (".like-wrapper .count", ".likes .count", ".count"):
            like_el = await card.query_selector(sel)
            if like_el:
                likes_text = (await like_el.inner_text()).strip()
                likes = normalize_count(likes_text)
                break

        # ---- Note type ----
        note_type: str = "image"
        video_marker = await card.query_selector(
            ".video-icon, .type-video, [class*='play-icon']"
        )
        if video_marker:
            note_type = "video"

        return {
            "note_id": note_id,
            "title": title,
            "author": author,
            "author_id": author_id,
            "cover_url": cover_url,
            "likes": likes,
            "note_url": note_url,
            "note_type": note_type,
            "publish_time": publish_time,
        }

    except Exception as e:
        logger.warning("Failed to parse search card: %s", e, exc_info=True)
        return None


# ---------- Note detail page parsing (Phase 3) ----------

# Candidate selectors for each note detail field (in priority order)
# Real DOM: #noteContainer > .interaction-container > .note-scroller > .note-content
_DETAIL_TITLE_SELECTORS = [
    "#detail-title",
    ".note-content .title",
]

_DETAIL_CONTENT_SELECTORS = [
    "#detail-desc .note-text",
    "#detail-desc",
    ".note-content .desc",
]

# Real DOM: .interaction-container > .author-container > .author-wrapper > .info > .username
_DETAIL_AUTHOR_SELECTORS = [
    ".author-container .username",
    ".interaction-container .username",
    ".author-wrapper .username",
]

_DETAIL_AUTHOR_LINK_SELECTORS = [
    ".author-container a[href*='/user/profile/']",
    ".interaction-container a[href*='/user/profile/']",
]

# Real DOM: .note-content > .bottom-container > span.date
_DETAIL_TIME_SELECTORS = [
    ".note-content .bottom-container .date",
    ".bottom-container .date",
]

# Real DOM: #detail-desc a#hash-tag.tag
_DETAIL_TAG_SELECTOR = "#detail-desc a.tag"

# Real DOM: .swiper-slide img
_DETAIL_IMAGE_SELECTORS = [
    ".swiper-slide img",
    ".media-container img",
]

_DETAIL_VIDEO_SELECTORS = [
    ".player-container video source",
    "video source",
    ".player-container video",
    "video",
]


async def _query_text(page: "Page", selectors: list[str]) -> str:
    """Try selectors on the page in priority order and return the first non-empty text."""
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            text = (await el.inner_text()).strip()
            if text:
                return text
    return ""


async def parse_note_detail(page: "Page", note_id: str) -> dict | None:
    """Parse a note detail page into structured data.

    Extracts from the currently loaded note detail page:
      - note_id / title / content / author / author_id
      - publish_time / likes / collects / comments_count / shares
      - tags / images / note_type / video_url

    Args:
        page: Playwright Page with the note detail page loaded
        note_id: Note ID (supplied by the caller)

    Returns:
        A dict with the fields above, or None if parsing fails
    """
    try:
        # ---- Title ----
        title = await _query_text(page, _DETAIL_TITLE_SELECTORS)

        # ---- Body content ----
        content = await _query_text(page, _DETAIL_CONTENT_SELECTORS)

        # ---- Author nickname ----
        author = await _query_text(page, _DETAIL_AUTHOR_SELECTORS)

        # ---- Author ID ----
        author_id = ""
        for sel in _DETAIL_AUTHOR_LINK_SELECTORS:
            anchor = await page.query_selector(sel)
            if anchor:
                href = await anchor.get_attribute("href") or ""
                parts = href.split("/user/profile/")
                if len(parts) == 2:
                    author_id = parts[1].split("?")[0].rstrip("/")
                    break

        # ---- Publish time ----
        publish_time = await _query_text(page, _DETAIL_TIME_SELECTORS)

        # ---- Interaction counts ----
        # Real DOM: .interact-container holds .like-wrapper / .collect-wrapper / .chat-wrapper
        # Each wrapper has a span.count showing the number
        likes = await _parse_interact_count(page, [
            ".interact-container .like-wrapper .count",
            ".engage-bar .like-wrapper .count",
            ".like-wrapper .count",
        ])
        collects = await _parse_interact_count(page, [
            ".interact-container .collect-wrapper .count",
            ".engage-bar .collect-wrapper .count",
            ".collect-wrapper .count",
        ])
        comments_count = await _parse_interact_count(page, [
            ".interact-container .chat-wrapper .count",
            ".engage-bar .chat-wrapper .count",
            ".chat-wrapper .count",
        ])
        shares = await _parse_interact_count(page, [
            ".interact-container .share-wrapper .count",
            ".engage-bar .share-wrapper .count",
            ".share-wrapper .count",
        ])

        # ---- Tags ----
        tags: list[str] = []
        tag_els = await page.query_selector_all(_DETAIL_TAG_SELECTOR)
        for tag_el in tag_els:
            tag_text = (await tag_el.inner_text()).strip().lstrip("#")
            if tag_text:
                tags.append(tag_text)

        # ---- Image list ----
        images: list[str] = []
        for sel in _DETAIL_IMAGE_SELECTORS:
            img_els = await page.query_selector_all(sel)
            if img_els:
                for img_el in img_els:
                    src = (
                        await img_el.get_attribute("data-src")
                        or await img_el.get_attribute("src")
                        or ""
                    )
                    if src and src not in images:
                        images.append(src)
                break  # Use only the first selector that matches

        # ---- Video URL and note type ----
        video_url = ""
        note_type = "image"
        for sel in _DETAIL_VIDEO_SELECTORS:
            video_el = await page.query_selector(sel)
            if video_el:
                video_url = (
                    await video_el.get_attribute("src")
                    or await video_el.get_attribute("data-src")
                    or ""
                )
                note_type = "video"
                break

        return {
            "note_id": note_id,
            "title": title,
            "content": content,
            "author": author,
            "author_id": author_id,
            "publish_time": publish_time,
            "likes": likes,
            "collects": collects,
            "comments_count": comments_count,
            "shares": shares,
            "tags": tags,
            "images": images,
            "note_type": note_type,
            "video_url": video_url,
        }

    except Exception as e:
        logger.warning("Failed to parse note detail (note_id=%s): %s", note_id, e, exc_info=True)
        return None


async def _parse_interact_count(page: "Page", selectors: list[str]) -> int:
    """Try selectors on the page in priority order to extract an interaction count."""
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            text = (await el.inner_text()).strip()
            if text:
                return normalize_count(text)
    return 0


# ---------- Comment parsing (Phase 3) ----------

# Candidate selectors for each comment field
# Real DOM: .comment-item > .comment-inner-container > .right > ...
_COMMENT_USER_SELECTORS = [
    ".right .author-wrapper .author a.name",  # exact path
    ".right .author a.name",
    ".author a.name",
    "a.name",
]

_COMMENT_USER_LINK_SELECTORS = [
    ".right .author-wrapper a[href*='/user/profile/']",
    "a[href*='/user/profile/']",
]

_COMMENT_CONTENT_SELECTORS = [
    ".right .content .note-text",
    ".right .content",
]

# Real DOM: .right > .info > .interactions > .like (inner_text is a number, or the Chinese placeholder "赞" when there are no likes)
_COMMENT_LIKE_SELECTORS = [
    ".right .info .interactions .like",
    ".info .like",
]

# Real DOM: .right > .info > .date > span:first-child (excluding .location)
# Note: .date's inner_text is date + IP location run together (e.g. "01-15广东",
# the location is rendered in Chinese), so the two are extracted separately
_COMMENT_TIME_SELECTOR = ".right .info .date"

# Real DOM: .right > .info > .date > span.location
_COMMENT_LOCATION_SELECTORS = [
    ".right .info .date .location",
    ".info .location",
    ".location",
]


async def parse_comment(comment_el: "ElementHandle", note_id: str) -> dict | None:
    """Parse a single comment element into structured data.

    Real DOM structure:
      .comment-item#comment-{id}
        .comment-inner-container
          .avatar
          .right
            .author-wrapper > .author > a.name
            .content > span.note-text
            .info
              .date > span (time) + span.location (IP location)
              .interactions > .like (like count)

    Args:
        comment_el: ElementHandle of a single comment (the .comment-item element)
        note_id: ID of the note the comment belongs to

    Returns:
        A dict with comment_id / note_id / user_name / user_id /
        content / likes / time / ip_location, or None on failure
    """
    try:
        # ---- Comment ID ----
        # In the real DOM the id looks like "comment-{hex_id}"; strip the prefix
        raw_id = await comment_el.get_attribute("id") or ""
        comment_id = raw_id.removeprefix("comment-") if raw_id else ""

        # ---- Commenter nickname ----
        user_name = ""
        for sel in _COMMENT_USER_SELECTORS:
            el = await comment_el.query_selector(sel)
            if el:
                user_name = (await el.inner_text()).strip()
                if user_name:
                    break

        # ---- Commenter ID ----
        user_id = ""
        for sel in _COMMENT_USER_LINK_SELECTORS:
            anchor = await comment_el.query_selector(sel)
            if anchor:
                href = await anchor.get_attribute("href") or ""
                parts = href.split("/user/profile/")
                if len(parts) == 2:
                    user_id = parts[1].split("?")[0].rstrip("/")
                    break

        # ---- Comment content ----
        content = ""
        for sel in _COMMENT_CONTENT_SELECTORS:
            el = await comment_el.query_selector(sel)
            if el:
                content = (await el.inner_text()).strip()
                if content:
                    break

        # ---- Like count ----
        # .like's inner_text is a number (e.g. "10") or "赞" (the Chinese "like" label the
        # site shows as a placeholder when a comment has zero likes)
        likes = 0
        for sel in _COMMENT_LIKE_SELECTORS:
            el = await comment_el.query_selector(sel)
            if el:
                text = (await el.inner_text()).strip()
                if text and text != "赞":
                    likes = normalize_count(text)
                break

        # ---- Comment time & IP location ----
        # Inside the .date container: <span>01-15</span><span class="location">广东</span>
        # (the IP location is rendered in Chinese)
        time_text = ""
        ip_location = ""

        # Extract the IP location first
        for sel in _COMMENT_LOCATION_SELECTORS:
            loc_el = await comment_el.query_selector(sel)
            if loc_el:
                ip_location = (await loc_el.inner_text()).strip()
                break

        # Take the full text of the .date container and strip the location to get the time
        date_el = await comment_el.query_selector(_COMMENT_TIME_SELECTOR)
        if date_el:
            full_date = (await date_el.inner_text()).strip()
            if ip_location and full_date.endswith(ip_location):
                time_text = full_date[: -len(ip_location)].strip()
            else:
                time_text = full_date

        return {
            "comment_id": comment_id,
            "note_id": note_id,
            "user_name": user_name,
            "user_id": user_id,
            "content": content,
            "likes": likes,
            "time": time_text,
            "ip_location": ip_location,
        }

    except Exception as e:
        logger.warning("Failed to parse comment (note_id=%s): %s", note_id, e, exc_info=True)
        return None

"""
Bulk export job

Runs a plan of search queries, then collects every distinct note they return
(full caption, tags, counts, publish date, top comments, all image slides) into
one folder:

    <out_dir>/
      queries.json        one entry per query + sort: when it ran, how many notes, errors
      search_index.json   every search hit, including notes that were not fetched
      notes.jsonl         one JSON object per fetched note
      images/<note_id>/01.jpg, 02.jpg, ...
      crawl.log

Unlike the DOM-based crawler in src/, this reads the web app's own state
(window.__INITIAL_STATE__) and its comment API responses, which carry exact
counts, timestamps and image URLs.

The job is resumable: rerun the same command and it skips finished queries and
notes. It stops by itself after several consecutive failures, which usually
means rednote is rate-limiting the account.

Plan file (JSON):
    {
      "per_query": 20,
      "sorts": ["general", "most_saved"],        (also: newest, most_liked, most_commented)
      "max_comments": 20,
      "min_collected": 0,
      "interleave": false,
      "workers": 1,
      "categories": [{"category": "Food", "phase": 1, "queries": ["..."]}]
    }

Usage:
    uv run python rednote.py export plan.json ~/rednote-exports/my-trip --phase 1
    uv run python rednote.py export-status

    # or without the daemon (attaches to Chrome itself):
    uv run python export_job.py plan.json ~/rednote-exports/my-trip --phase 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from playwright.async_api import Page, Response

from src.browser import BrowserManager
from src.parser import normalize_count
from src.site import BASE_URL, SEARCH_URL

logger = logging.getLogger("export_job")

# Unwraps a Vue ref from the page's state object
_UNWRAP = "const u = v => (v && v._rawValue !== undefined) ? v._rawValue : ((v && v.__v_isRef) ? v.value : v);"

_SEARCH_FEEDS_JS = "() => {" + _UNWRAP + """
  const search = window.__INITIAL_STATE__.search;
  const feeds = u(search.feeds) || [];
  const sortFilter = (u(search.filterParams) || []).find(f => f.type === 'sort_type');
  return {
    sort: sortFilter ? sortFilter.tags[0] : 'general',
    hasMore: u(search.hasMore),
    notes: feeds.filter(f => f.modelType === 'note' && f.noteCard).map(f => ({
      id: f.id,
      xsecToken: f.xsecToken,
      title: f.noteCard.displayTitle || '',
      type: f.noteCard.type || '',
      author: (f.noteCard.user || {}).nickname || (f.noteCard.user || {}).nickName || '',
      interact: f.noteCard.interactInfo || {},
    })),
  };
}"""

_NOTE_JS = "(id) => {" + _UNWRAP + """
  const map = u(window.__INITIAL_STATE__.note.noteDetailMap) || {};
  const entry = map[id];
  if (!entry || !entry.note || !entry.note.noteId) return null;
  return JSON.parse(JSON.stringify(entry.note));
}"""

# Options in the search filter panel. Each visible option has an invisible decoy
# copy next to it (no data-hp-bound attribute); a real user can never click
# those, so the crawler must not either.
_SORT_OPTION = ".filter-panel .tags[data-hp-bound]"

# Plan sort name → (label of the option in the panel, sort tag the site then reports)
_SORTS = {
    "newest": (re.compile(r"^\s*(最新|newest|latest)\s*$", re.I), "time_descending"),
    "most_liked": (re.compile(r"^\s*(最多点赞|most liked)\s*$", re.I), "popularity_descending"),
    "most_commented": (re.compile(r"^\s*(最多评论|most comment(s|ed))\s*$", re.I), "comment_descending"),
    "most_saved": (re.compile(r"^\s*(最多收藏|most (saved|collected|favou?rited))\s*$", re.I), "collect_descending"),
}

_SEARCH_DELAY = (10.0, 20.0)
# After a failed search, wait this long before the next one (seconds). rednote
# blocks search for a while after a burst of queries; pushing on only extends it.
_SEARCH_BACKOFF = 300
_MAX_CONSECUTIVE_SEARCH_FAILURES = 3
_NOTE_DELAY = (6.0, 12.0)
_MAX_SCROLL_ROUNDS = 8
_MAX_CONSECUTIVE_FAILURES = 4
_NOTE_READY_SECONDS = 15
_COMMENT_PAGE_PATH = "/comment/page"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


class ExportJob:
    def __init__(self, plan: dict, out_dir: Path, phase: int | None) -> None:
        self.plan = plan
        self.out_dir = out_dir
        self.phase = phase
        self.per_query: int = plan.get("per_query", 20)
        self.sorts: list[str] = plan.get("sorts", ["general"])
        self.max_comments: int = plan.get("max_comments", 20)
        self.min_collected: int = plan.get("min_collected", 0)
        # Fetch each search's notes before running the next search. Searches then
        # happen minutes apart, which avoids the block a burst of searches triggers.
        self.interleave: bool = plan.get("interleave", False)
        # Number of tabs fetching notes at the same time
        self.workers: int = plan.get("workers", 1)

        self.queries_path = out_dir / "queries.json"
        self.index_path = out_dir / "search_index.json"
        self.notes_path = out_dir / "notes.jsonl"
        self.images_dir = out_dir / "images"

        self.query_log: list[dict] = _read_json(self.queries_path, [])
        self.index: dict[str, dict] = _read_json(self.index_path, {})
        # note id → comment API pages seen while that note's page is open
        self._comment_pages: dict[str, list[dict]] = {}

    # ---------- Stage 1: searches ----------

    def _planned_searches(self) -> list[dict]:
        searches = []
        for group in self.plan["categories"]:
            if self.phase is not None and group.get("phase") != self.phase:
                continue
            for query in group["queries"]:
                for sort in self.sorts:
                    searches.append(
                        {"query": query, "category": group["category"], "phase": group.get("phase"), "sort": sort}
                    )
        return searches

    def _search_done(self, search: dict) -> bool:
        return any(
            entry["query"] == search["query"] and entry["sort"] == search["sort"] and not entry.get("error")
            for entry in self.query_log
        )

    async def _apply_sort(self, page: Page, sort: str) -> str | None:
        """Switch the search to another sort order. Returns an error message, or None."""
        if sort not in _SORTS:
            return f"unknown sort {sort!r}; use general or one of {sorted(_SORTS)}"
        label, sort_tag = _SORTS[sort]
        # The filter panel opens on hover
        await page.locator(".filter").first.hover()
        await asyncio.sleep(1.2)
        option = page.locator(_SORT_OPTION, has_text=label).first
        box = await option.bounding_box() if await option.count() else None
        if box is None:
            return f"{sort} option not found in the filter panel"

        # A real mouse click on the option itself; moving in steps keeps the hover panel open
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        await page.mouse.move(x, y, steps=10)
        await asyncio.sleep(0.4)
        await page.mouse.click(x, y)

        for _ in range(20):
            await asyncio.sleep(0.5)
            state = await page.evaluate(_SEARCH_FEEDS_JS)
            if state["sort"] == sort_tag and state["notes"]:
                await page.mouse.move(300, 500, steps=10)
                return None
        return f"sort did not change after clicking the {sort} option"

    async def _run_search(self, page: Page, search: dict) -> dict:
        entry = {**search, "ran_at": _now(), "returned": 0, "error": None}
        try:
            await page.goto(
                SEARCH_URL.format(keyword=quote(search["query"])), wait_until="domcontentloaded", timeout=30_000
            )
            await page.wait_for_selector("section.note-item", timeout=20_000)
            await asyncio.sleep(1.5)

            if search["sort"] != "general":
                error = await self._apply_sort(page, search["sort"])
                if error:
                    entry["error"] = error
                    return entry

            state = await page.evaluate(_SEARCH_FEEDS_JS)
            for _ in range(_MAX_SCROLL_ROUNDS):
                if len(state["notes"]) >= self.per_query or state["hasMore"] is False:
                    break
                await page.mouse.wheel(0, random.randint(1200, 2000))
                await asyncio.sleep(random.uniform(1.5, 3.0))
                state = await page.evaluate(_SEARCH_FEEDS_JS)

            entry["site_sort"] = state["sort"]
            notes = state["notes"][: self.per_query]
            entry["returned"] = len(notes)
            for rank, note in enumerate(notes, start=1):
                hit = self.index.setdefault(note["id"], {"hits": []})
                interact = note["interact"]
                hit.update(
                    xsec_token=note["xsecToken"],
                    title=note["title"],
                    author=note["author"],
                    type=note["type"],
                    liked=normalize_count(interact.get("likedCount", "")),
                    collected=normalize_count(interact.get("collectedCount", "")),
                    comments=normalize_count(interact.get("commentCount", "")),
                    shared=normalize_count(interact.get("sharedCount", "")),
                )
                hit["hits"].append(
                    {"query": search["query"], "category": search["category"], "sort": search["sort"], "rank": rank}
                )
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}".splitlines()[0]
            entry["page_text"] = await self._page_text(page)
        return entry

    @staticmethod
    async def _page_text(page: Page) -> str:
        """What the page shows, to tell a block or captcha apart from an empty result."""
        try:
            return (await page.evaluate("document.body.innerText"))[:300]
        except Exception:
            return ""

    async def run_searches(self, page: Page, after_each=None) -> bool:
        """Run pending searches. Returns False if search looks blocked and the stage gave up.

        Args:
            after_each: optional coroutine function awaited after every successful search
        """
        pending = [s for s in self._planned_searches() if not self._search_done(s)]
        logger.info("Stage 1: %d searches to run", len(pending))
        failures = 0
        for i, search in enumerate(pending, start=1):
            entry = await self._run_search(page, search)
            # A rerun replaces the earlier failed attempt
            self.query_log = [
                e for e in self.query_log if not (e["query"] == entry["query"] and e["sort"] == entry["sort"])
            ]
            self.query_log.append(entry)
            _write_json(self.queries_path, self.query_log)
            _write_json(self.index_path, self.index)
            logger.info(
                "[search %d/%d] %s (%s): %d notes%s",
                i, len(pending), search["query"], search["sort"], entry["returned"],
                f" — ERROR {entry['error']}" if entry["error"] else "",
            )
            if entry["error"]:
                failures += 1
                if failures >= _MAX_CONSECUTIVE_SEARCH_FAILURES:
                    logger.error("%d searches in a row failed; search looks blocked, leaving the rest for a rerun", failures)
                    return False
                logger.info("Backing off %d seconds before the next search", _SEARCH_BACKOFF)
                await asyncio.sleep(_SEARCH_BACKOFF)
            else:
                failures = 0
                await asyncio.sleep(random.uniform(*_SEARCH_DELAY))
                if after_each is not None and await after_each() is False:
                    logger.error("Note fetching stopped; leaving the remaining searches for a rerun")
                    return False
        return True

    # ---------- Stage 2: note details ----------

    def _fetched_ids(self) -> set[str]:
        if not self.notes_path.exists():
            return set()
        fetched = set()
        # Split on "\n" only: captions can contain other Unicode line separators
        for line in self.notes_path.read_text().split("\n"):
            try:
                fetched.add(json.loads(line)["note_id"])
            except (json.JSONDecodeError, KeyError):
                # A line cut off when an earlier run was stopped mid-write; that note is fetched again
                continue
        return fetched

    def _pending_notes(self) -> list[str]:
        """Notes hit by this phase's queries and not fetched yet, most saved first."""
        phase_queries = {s["query"] for s in self._planned_searches()}
        fetched = self._fetched_ids()
        pending = [
            note_id
            for note_id, hit in self.index.items()
            if note_id not in fetched
            and hit.get("collected", 0) >= self.min_collected
            and any(h["query"] in phase_queries for h in hit["hits"])
        ]
        return sorted(pending, key=lambda note_id: self.index[note_id].get("collected", 0), reverse=True)

    async def _download_image(self, page: Page, folder: Path, number: int, image: dict) -> str | None:
        url = (image.get("urlDefault") or "").replace("http://", "https://")
        if not url:
            return None
        try:
            response = await page.context.request.get(url, headers={"Referer": BASE_URL + "/"})
            if response.status != 200:
                logger.warning("Image %s #%d: HTTP %d", folder.name, number, response.status)
                return None
            target = folder / f"{number:02d}.webp"
            target.write_bytes(await response.body())
            saved = await asyncio.to_thread(_to_jpeg, target)
            return str(saved.relative_to(self.out_dir))
        except Exception as e:
            logger.warning("Image %s #%d failed: %s", folder.name, number, e)
            return None

    async def _download_images(self, page: Page, note_id: str, image_list: list[dict]) -> list[str]:
        """Download every slide, in order. These are CDN requests, so they run concurrently."""
        folder = self.images_dir / note_id
        folder.mkdir(parents=True, exist_ok=True)
        paths = await asyncio.gather(
            *(self._download_image(page, folder, number, image) for number, image in enumerate(image_list, start=1))
        )
        return [path for path in paths if path]

    async def _collect_comments(self, page: Page, pages: list[dict]) -> list[dict]:
        """Wait for the comment API responses the note page triggers; scroll for more if needed."""
        for _ in range(16):
            if pages:
                break
            await asyncio.sleep(0.5)
        for _ in range(3):
            count = sum(len(p.get("comments") or []) for p in pages)
            if not pages or count >= self.max_comments or not pages[-1].get("has_more"):
                break
            seen = len(pages)
            await page.evaluate(
                "() => { const s = document.querySelector('.note-scroller'); if (s) s.scrollTop = s.scrollHeight; }"
            )
            for _ in range(8):
                if len(pages) > seen:
                    break
                await asyncio.sleep(0.5)

        comments = [c for p in pages for c in (p.get("comments") or [])][: self.max_comments]
        return [
            {
                **_comment_fields(comment),
                "replies": [_comment_fields(reply) for reply in comment.get("sub_comments") or []],
            }
            for comment in comments
        ]

    async def _fetch_note(self, page: Page, note_id: str, comment_pages: dict[str, list[dict]]) -> dict | None:
        hit = self.index[note_id]
        url = f"{BASE_URL}/explore/{note_id}?xsec_token={hit['xsec_token']}&xsec_source=pc_search"
        comment_pages[note_id] = []
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        note = None
        for _ in range(_NOTE_READY_SECONDS * 2):
            note = await page.evaluate(_NOTE_JS, note_id)
            if note:
                break
            await asyncio.sleep(0.5)
        if not note:
            logger.warning("Note %s did not load (ended at %s)", note_id, page.url.split("?")[0])
            return None

        # Slides first: the page requests its comments a few seconds after it loads
        images = await self._download_images(page, note_id, note.get("imageList") or [])
        # No point waiting for the comment request of a note the search says has none
        has_comments = hit.get("comments", 1) > 0 and self.max_comments > 0
        top_comments = await self._collect_comments(page, comment_pages[note_id]) if has_comments else []
        interact = note.get("interactInfo") or {}
        translation = note.get("noteTranslation") or {}
        user = note.get("user") or {}
        hits = hit["hits"]

        return {
            "note_id": note_id,
            "url": url,
            "queries": sorted({h["query"] for h in hits}),
            "category": hits[0]["category"],
            "categories": sorted({h["category"] for h in hits}),
            "title": note.get("title", ""),
            "desc": note.get("desc", ""),
            "title_en": translation.get("titleTrans", ""),
            "desc_en": translation.get("descTrans", ""),
            "tags": [tag["name"] for tag in note.get("tagList") or [] if tag.get("name")],
            # rednote's web state carries no location/POI object for notes
            "poi": note.get("poi") or None,
            "published_at": _iso(note.get("time")),
            "updated_at": _iso(note.get("lastUpdateTime")),
            "liked": normalize_count(interact.get("likedCount", "")),
            "collected": normalize_count(interact.get("collectedCount", "")),
            "comments": normalize_count(interact.get("commentCount", "")),
            "shared": normalize_count(interact.get("shareCount", "")),
            "author": user.get("nickname", ""),
            "author_id": user.get("userId", ""),
            "ip_location": note.get("ipLocation", ""),
            "type": note.get("type", ""),
            "images": images,
            "image_text": [],
            "top_comments": top_comments,
            "fetched_at": _now(),
        }

    async def run_notes(self, page: Page, limit: int | None = None) -> bool:
        """Fetch pending notes. Returns False if the job stopped early on repeated failures."""
        pending = self._pending_notes()[:limit]
        total = len(pending)
        logger.info("Stage 2: %d notes to fetch", total)

        # Extra tabs for the other workers; the first worker uses the job's own tab
        pages = [page]
        for _ in range(min(self.workers, total) - 1):
            extra = await page.context.new_page()
            extra.on("response", self._on_response)
            pages.append(extra)

        queue = list(enumerate(pending, start=1))
        state = {"failures": 0, "stopped": False}

        async def worker(tab: Page) -> None:
            while queue and not state["stopped"]:
                number, note_id = queue.pop(0)
                try:
                    record = await self._fetch_note(tab, note_id, self._comment_pages)
                except Exception as e:
                    logger.warning("Note %s failed: %s", note_id, f"{type(e).__name__}: {e}".splitlines()[0])
                    record = None
                self._comment_pages.pop(note_id, None)

                if record is None:
                    state["failures"] += 1
                    if state["failures"] >= _MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            "%d notes in a row failed; stopping to keep the account safe", state["failures"]
                        )
                        state["stopped"] = True
                else:
                    state["failures"] = 0
                    with self.notes_path.open("a") as f:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    logger.info(
                        "[note %d/%d] %s — saved %d, %d images, %d comments",
                        number, total, record["title"][:30], record["collected"],
                        len(record["images"]), len(record["top_comments"]),
                    )
                await asyncio.sleep(random.uniform(*_NOTE_DELAY))

        try:
            await asyncio.gather(*(worker(tab) for tab in pages))
        finally:
            for extra in pages[1:]:
                if not extra.is_closed():
                    await extra.close()
        return not state["stopped"]

    async def _on_response(self, response: Response) -> None:
        """Collect the comment API responses of the note currently being fetched."""
        if _COMMENT_PAGE_PATH not in response.url:
            return
        note_id = parse_qs(urlparse(response.url).query).get("note_id", [""])[0]
        if note_id not in self._comment_pages:
            return
        try:
            self._comment_pages[note_id].append((await response.json()).get("data") or {})
        except Exception:
            pass

    async def run_in(self, bm: BrowserManager, limit_notes: int | None = None) -> bool:
        """Run the job in a new tab of an already attached browser."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        page = await bm.new_page()
        page.on("response", self._on_response)
        try:
            if self.interleave:
                state = {"ok": True}

                async def fetch_batch() -> bool:
                    state["ok"] = await self.run_notes(page, self.per_query)
                    return state["ok"]

                searches_finished = await self.run_searches(page, after_each=fetch_batch)
                if not state["ok"]:
                    return False
            else:
                searches_finished = await self.run_searches(page)
            # Notes from the searches that did work are still fetched
            notes_finished = await self.run_notes(page, limit_notes)
            return searches_finished and notes_finished
        finally:
            if not page.is_closed():
                await page.close()

    async def run(self, limit_notes: int | None) -> bool:
        async with BrowserManager() as bm:
            return await self.run_in(bm, limit_notes)


def _iso(milliseconds: int | None) -> str | None:
    if not milliseconds:
        return None
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def _comment_fields(comment: dict) -> dict:
    return {
        "text": comment.get("content", ""),
        "text_en": comment.get("content_translation", ""),
        "likes": normalize_count(str(comment.get("like_count", ""))),
        "is_author": "is_author" in (comment.get("show_tags") or []),
        "user": (comment.get("user_info") or {}).get("nickname", ""),
    }


def _to_jpeg(webp_path: Path) -> Path:
    """Convert a downloaded slide to JPEG with macOS sips; keep the WebP if that is not possible."""
    if shutil.which("sips") is None:
        return webp_path
    jpeg_path = webp_path.with_suffix(".jpg")
    result = subprocess.run(
        ["sips", "-s", "format", "jpeg", str(webp_path), "--out", str(jpeg_path)],
        capture_output=True,
    )
    if result.returncode != 0 or not jpeg_path.exists():
        return webp_path
    webp_path.unlink()
    return jpeg_path


def configure_file_log(out_dir: Path) -> None:
    """Send the job's log to <out_dir>/crawl.log."""
    out_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(out_dir / "crawl.log")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.handlers = [h for h in logger.handlers if not isinstance(h, logging.FileHandler)]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk rednote export job")
    parser.add_argument("plan", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--phase", type=int, default=None, help="only run categories with this phase")
    parser.add_argument("--limit-notes", type=int, default=None, help="fetch at most this many notes")
    args = parser.parse_args()

    out_dir = args.out_dir.expanduser()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    configure_file_log(out_dir)

    job = ExportJob(json.loads(args.plan.expanduser().read_text()), out_dir, args.phase)
    finished = asyncio.run(job.run(args.limit_notes))
    logger.info("Job %s", "finished" if finished else "stopped early; rerun the same command to resume")
    return 0 if finished else 1


if __name__ == "__main__":
    sys.exit(main())

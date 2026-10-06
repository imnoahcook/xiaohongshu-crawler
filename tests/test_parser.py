"""
Unit tests for the parser module

Test strategy:
  - normalize_count: synchronous pure function, tested directly across input formats
  - Async parsing functions: use AsyncMock to mock Playwright ElementHandle / Page;
    no real browser needed, runs entirely in-process
  - Coverage: happy path, fallback paths (selector misses), and error-handling paths
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.parser import (
    _parse_interact_count,
    _query_text,
    normalize_count,
    parse_comment,
    parse_note_detail,
    parse_search_card,
)


# ============================================================
# normalize_count
# ============================================================


class TestNormalizeCount:
    """Test count text → integer conversion.

    The Chinese units ("万", "亿") are kept on purpose: rednote renders counts
    that way even on the English UI.
    """

    def test_empty_string_returns_zero(self):
        assert normalize_count("") == 0

    def test_none_returns_zero(self):
        assert normalize_count(None) == 0

    def test_wan_notation(self):
        assert normalize_count("1.2万") == 12000

    def test_w_notation_lowercase(self):
        assert normalize_count("3.5w") == 35000

    def test_w_notation_uppercase(self):
        assert normalize_count("3.5W") == 35000

    def test_integer_string(self):
        assert normalize_count("324") == 324

    def test_zero_string(self):
        assert normalize_count("0") == 0

    def test_comma_separated_number(self):
        assert normalize_count("3,240") == 3240

    def test_k_notation(self):
        assert normalize_count("1.2K") == 1200

    def test_m_notation(self):
        assert normalize_count("3.4M") == 3400000

    def test_yi_notation(self):
        assert normalize_count("1.2亿") == 120000000

    def test_plus_suffix(self):
        assert normalize_count("10万+") == 100000

    def test_whole_wan_unit(self):
        assert normalize_count("2万") == 20000

    def test_invalid_text_returns_zero(self):
        assert normalize_count("赞") == 0

    def test_strips_leading_and_trailing_whitespace(self):
        assert normalize_count("  500  ") == 500

    def test_float_truncated_to_int(self):
        """Floats should be truncated to an integer (not rounded)."""
        assert normalize_count("1.9") == 1

    def test_wan_with_space_between_number_and_unit(self):
        """A space between the number and the unit should still parse correctly."""
        assert normalize_count("1.2 万") == 12000


# ============================================================
# _query_text (helper)
# ============================================================


class TestQueryText:
    """Test that _query_text tries selectors in priority order."""

    async def test_returns_text_from_first_matching_selector(self):
        """The first matching selector should return its text."""
        mock_page = AsyncMock()
        el = AsyncMock()
        el.inner_text = AsyncMock(return_value="  Title text  ")

        async def qs(sel):
            return el if sel == ".title" else None

        mock_page.query_selector = qs
        result = await _query_text(mock_page, [".other", ".title"])
        assert result == "Title text"

    async def test_falls_back_when_first_selector_returns_none(self):
        """Should move on to the next selector when the first one misses."""
        mock_page = AsyncMock()
        backup_el = AsyncMock()
        backup_el.inner_text = AsyncMock(return_value="Backup text")

        async def qs(sel):
            return backup_el if sel == ".backup" else None

        mock_page.query_selector = qs
        result = await _query_text(mock_page, [".primary", ".backup"])
        assert result == "Backup text"

    async def test_returns_empty_when_no_selector_matches(self):
        """Should return an empty string when no selector matches."""
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=None)
        result = await _query_text(mock_page, [".a", ".b"])
        assert result == ""

    async def test_skips_element_with_empty_text(self):
        """Should move on to the next selector when the element exists but its text is empty."""
        mock_page = AsyncMock()
        empty_el = AsyncMock()
        empty_el.inner_text = AsyncMock(return_value="   ")
        real_el = AsyncMock()
        real_el.inner_text = AsyncMock(return_value="Real content")
        call_count = 0

        async def qs(sel):
            nonlocal call_count
            call_count += 1
            return empty_el if call_count == 1 else real_el

        mock_page.query_selector = qs
        result = await _query_text(mock_page, [".empty", ".real"])
        assert result == "Real content"


# ============================================================
# _parse_interact_count (helper)
# ============================================================


class TestParseInteractCount:
    """Test interaction count extraction in _parse_interact_count."""

    async def test_returns_parsed_count_from_matching_selector(self):
        """Should return the parsed integer count once a selector matches."""
        mock_page = AsyncMock()
        el = AsyncMock()
        el.inner_text = AsyncMock(return_value="1.2万")
        mock_page.query_selector = AsyncMock(return_value=el)
        result = await _parse_interact_count(mock_page, [".likes"])
        assert result == 12000

    async def test_returns_zero_when_no_selector_matches(self):
        """Should return 0 when no selector matches."""
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=None)
        result = await _parse_interact_count(mock_page, [".a", ".b"])
        assert result == 0

    async def test_returns_zero_for_empty_text(self):
        """Should return 0 when the element exists but its text is empty."""
        mock_page = AsyncMock()
        el = AsyncMock()
        el.inner_text = AsyncMock(return_value="  ")
        mock_page.query_selector = AsyncMock(return_value=el)
        result = await _parse_interact_count(mock_page, [".count"])
        assert result == 0


# ============================================================
# parse_search_card
# ============================================================


def _make_text_el(text: str) -> AsyncMock:
    """Create a mock element with fixed text."""
    el = AsyncMock()
    el.inner_text = AsyncMock(return_value=text)
    return el


def _make_attr_el(attr_value: str) -> AsyncMock:
    """Create a mock element whose get_attribute returns a fixed value."""
    el = AsyncMock()
    el.get_attribute = AsyncMock(return_value=attr_value)
    return el


def _make_search_card(
    explore_href: str = "/explore/abc123",
    cover_href: str = "/search_result/abc123?xsec_token=TOKEN123&xsec_source=pc_search",
    img_data_src: str = "https://example.com/cover.jpg",
    title: str = "Test title",
    author: str = "Test author",
    user_href: str = "/user/profile/user001?x=1",
    publish_time: str = "2025-01-15",
    likes_text: str = "1.2万",
    is_video: bool = False,
    has_explore_anchor: bool = True,
) -> AsyncMock:
    """Create a configurable mock search result card ElementHandle."""
    explore_anchor = _make_attr_el(explore_href) if has_explore_anchor else None
    cover_anchor = _make_attr_el(cover_href)

    async def img_get_attr(name):
        if name == "data-src":
            return img_data_src
        return None

    img_el = AsyncMock()
    img_el.get_attribute = img_get_attr

    title_el = _make_text_el(title)
    author_el = _make_text_el(author)
    user_anchor = _make_attr_el(user_href)
    time_el = _make_text_el(publish_time)
    like_el = _make_text_el(likes_text)
    video_el = AsyncMock() if is_video else None

    async def query_selector(sel: str):
        if 'a[href*="/explore/"]' in sel:
            return explore_anchor
        if sel == "a.cover":
            return cover_anchor
        if sel == "a.cover img":
            return img_el
        if ".footer a.title span" in sel or ".footer a.title" in sel:
            return title_el
        if ".card-bottom-wrapper .author .name" in sel:
            return author_el
        if "a.author[href*='/user/profile/']" in sel:
            return user_anchor
        if ".name-time-wrapper .time" in sel:
            return time_el
        if ".like-wrapper .count" in sel:
            return like_el
        if "video-icon" in sel or "type-video" in sel or "play-icon" in sel:
            return video_el
        return None

    card = AsyncMock()
    card.query_selector = query_selector
    return card


class TestParseSearchCard:
    """Test search result card parsing."""

    async def test_extracts_note_id_from_explore_href(self):
        """Should extract note_id from the last segment of the /explore/ link."""
        card = _make_search_card(explore_href="/explore/abc123def456")
        result = await parse_search_card(card)
        assert result is not None
        assert result["note_id"] == "abc123def456"

    async def test_builds_url_with_xsec_token(self):
        """Should build a full note_url that includes xsec_token."""
        card = _make_search_card(
            cover_href="/search_result/abc123?xsec_token=MYTOKEN&xsec_source=pc_search"
        )
        result = await parse_search_card(card)
        assert result is not None
        assert "xsec_token=MYTOKEN" in result["note_url"]
        assert "rednote.com" in result["note_url"]

    async def test_builds_url_without_xsec_token(self):
        """Should use a token-less URL when the cover link has no xsec_token."""
        card = _make_search_card(cover_href="/search_result/abc123")
        result = await parse_search_card(card)
        assert result is not None
        # URL format without a token: /explore/{note_id}
        assert "xsec_token" not in result["note_url"]

    async def test_falls_back_to_cover_anchor_for_note_id(self):
        """Should extract note_id from the cover link when there is no /explore/ link."""
        card = _make_search_card(
            has_explore_anchor=False,
            cover_href="/search_result/fallback123?xsec_token=T",
        )
        result = await parse_search_card(card)
        assert result is not None
        assert result["note_id"] == "fallback123"

    async def test_returns_none_when_no_note_id(self):
        """Should return None when note_id cannot be extracted."""
        card = AsyncMock()
        card.query_selector = AsyncMock(return_value=None)
        result = await parse_search_card(card)
        assert result is None

    async def test_parses_title(self):
        """Should extract the title text correctly."""
        card = _make_search_card(title="Advanced Python tips")
        result = await parse_search_card(card)
        assert result is not None
        assert result["title"] == "Advanced Python tips"

    async def test_parses_author(self):
        """Should extract the author nickname correctly."""
        card = _make_search_card(author="Test username")
        result = await parse_search_card(card)
        assert result is not None
        assert result["author"] == "Test username"

    async def test_parses_author_id_from_user_profile_href(self):
        """Should extract author_id from the user profile link."""
        card = _make_search_card(user_href="/user/profile/UserID001?extra=x")
        result = await parse_search_card(card)
        assert result is not None
        assert result["author_id"] == "UserID001"

    async def test_parses_likes_count(self):
        """Should parse like-count text correctly (including the Chinese 万 unit the site renders)."""
        card = _make_search_card(likes_text="3.5万")
        result = await parse_search_card(card)
        assert result is not None
        assert result["likes"] == 35000

    async def test_note_type_image_by_default(self):
        """Note type should be 'image' when there is no video marker."""
        card = _make_search_card(is_video=False)
        result = await parse_search_card(card)
        assert result is not None
        assert result["note_type"] == "image"

    async def test_note_type_video_when_video_marker_present(self):
        """Note type should be 'video' when a video marker is present."""
        card = _make_search_card(is_video=True)
        result = await parse_search_card(card)
        assert result is not None
        assert result["note_type"] == "video"

    async def test_result_contains_all_required_keys(self):
        """The returned dict should contain all required keys."""
        card = _make_search_card()
        result = await parse_search_card(card)
        assert result is not None
        required = {
            "note_id", "title", "author", "author_id",
            "cover_url", "likes", "note_url", "note_type", "publish_time",
        }
        assert required.issubset(set(result.keys()))

    async def test_returns_none_on_exception(self):
        """Exceptions during parsing should be caught and None returned."""
        card = AsyncMock()
        card.query_selector = AsyncMock(side_effect=Exception("DOM error"))
        result = await parse_search_card(card)
        assert result is None

    async def test_cover_url_from_img_src_fallback(self):
        """Should fall back to the src attribute when the cover image has no data-src."""
        # Create an img element with src but no data-src
        async def img_get_attr(name):
            if name == "src":
                return "https://example.com/via-src.jpg"
            return None  # data-src is None

        img_el = AsyncMock()
        img_el.get_attribute = img_get_attr

        explore_anchor = _make_attr_el("/explore/abc123")
        cover_anchor = _make_attr_el("/search_result/abc123?xsec_token=T")
        title_el = _make_text_el("Title")
        author_el = _make_text_el("Author")
        user_anchor = _make_attr_el("/user/profile/u1")
        time_el = _make_text_el("2025-01-15")
        like_el = _make_text_el("100")

        async def qs(sel):
            if 'a[href*="/explore/"]' in sel:
                return explore_anchor
            if sel == "a.cover":
                return cover_anchor
            if sel == "a.cover img":
                return img_el
            if ".footer a.title span" in sel:
                return title_el
            if ".card-bottom-wrapper .author .name" in sel:
                return author_el
            if "a.author[href*='/user/profile/']" in sel:
                return user_anchor
            if ".name-time-wrapper .time" in sel:
                return time_el
            if ".like-wrapper .count" in sel:
                return like_el
            return None

        card = AsyncMock()
        card.query_selector = qs
        result = await parse_search_card(card)
        assert result is not None
        assert result["cover_url"] == "https://example.com/via-src.jpg"


# ============================================================
# parse_note_detail
# ============================================================


def _make_note_page(
    title: str = "Note title",
    content: str = "Note body content",
    author: str = "Author nickname",
    author_id: str = "user001",
    publish_time: str = "2025-01-15",
    likes: int = 1200,
    collects: int = 300,
    comments_count: int = 50,
    shares: int = 10,
    tags: list[str] | None = None,
    images: list[str] | None = None,
) -> AsyncMock:
    """Create a mock note detail Page."""
    tags = tags or ["#Python", "#tutorial"]
    images = images or ["https://example.com/img1.jpg"]

    def make_el(text):
        el = AsyncMock()
        el.inner_text = AsyncMock(return_value=text)
        return el

    title_el = make_el(title)
    content_el = make_el(content)
    author_el = make_el(author)
    time_el = make_el(publish_time)
    likes_el = make_el(str(likes))
    collects_el = make_el(str(collects))
    comments_el = make_el(str(comments_count))
    shares_el = make_el(str(shares))

    author_link = AsyncMock()
    author_link.get_attribute = AsyncMock(return_value=f"/user/profile/{author_id}?x=1")

    async def query_selector(sel: str):
        if sel == "#detail-title":
            return title_el
        if sel == "#detail-desc .note-text":
            return content_el
        if sel == ".author-container .username":
            return author_el
        if sel == ".note-content .bottom-container .date":
            return time_el
        if ".author-container a[href*='/user/profile/']" in sel:
            return author_link
        if ".like-wrapper .count" in sel:
            return likes_el
        if ".collect-wrapper .count" in sel:
            return collects_el
        if ".chat-wrapper .count" in sel:
            return comments_el
        if ".share-wrapper .count" in sel:
            return shares_el
        return None

    # Image mocks
    img_els = []
    for src in images:
        img_el = AsyncMock()

        async def get_attr_fn(name, _src=src):
            if name == "data-src":
                return _src
            return None

        img_el.get_attribute = get_attr_fn
        img_els.append(img_el)

    async def query_selector_all(sel: str):
        if sel == "#detail-desc a.tag":
            return [make_el(tag) for tag in tags]
        if ".swiper-slide img" in sel:
            return img_els
        return []

    mock_page = AsyncMock()
    mock_page.query_selector = query_selector
    mock_page.query_selector_all = query_selector_all
    return mock_page


class TestParseNoteDetail:
    """Test note detail page parsing."""

    async def test_parses_title_and_content(self):
        """Should parse the title and body correctly."""
        page = _make_note_page(title="Python tutorial", content="Detailed content")
        result = await parse_note_detail(page, "note123")
        assert result is not None
        assert result["title"] == "Python tutorial"
        assert result["content"] == "Detailed content"

    async def test_preserves_passed_note_id(self):
        """note_id should be the value supplied by the caller."""
        page = _make_note_page()
        result = await parse_note_detail(page, "my_note_id")
        assert result is not None
        assert result["note_id"] == "my_note_id"

    async def test_parses_author_and_author_id(self):
        """Should parse the author nickname and ID correctly."""
        page = _make_note_page(author="Blogger Zhang San", author_id="ZhangSan007")
        result = await parse_note_detail(page, "note123")
        assert result is not None
        assert result["author"] == "Blogger Zhang San"
        assert result["author_id"] == "ZhangSan007"

    async def test_parses_interaction_counts(self):
        """Should parse like, collect, comment, and share counts correctly."""
        page = _make_note_page(likes=5000, collects=200, comments_count=88, shares=15)
        result = await parse_note_detail(page, "note123")
        assert result is not None
        assert result["likes"] == 5000
        assert result["collects"] == 200
        assert result["comments_count"] == 88
        assert result["shares"] == 15

    async def test_parses_tags_strips_hash(self):
        """Tags should have the # prefix stripped."""
        page = _make_note_page(tags=["#Python", "#MachineLearning"])
        result = await parse_note_detail(page, "note123")
        assert result is not None
        assert "Python" in result["tags"]
        assert "MachineLearning" in result["tags"]
        # The original # must not appear
        for tag in result["tags"]:
            assert not tag.startswith("#")

    async def test_parses_images(self):
        """Should extract the image URL list correctly."""
        images = ["https://example.com/a.jpg", "https://example.com/b.jpg"]
        page = _make_note_page(images=images)
        result = await parse_note_detail(page, "note123")
        assert result is not None
        assert set(result["images"]) == set(images)

    async def test_result_contains_all_required_keys(self):
        """The returned dict should contain all required keys."""
        page = _make_note_page()
        result = await parse_note_detail(page, "note123")
        assert result is not None
        required = {
            "note_id", "title", "content", "author", "author_id",
            "publish_time", "likes", "collects", "comments_count",
            "shares", "tags", "images", "note_type", "video_url",
        }
        assert required.issubset(set(result.keys()))

    async def test_returns_none_on_exception(self):
        """Exceptions during parsing should be caught and None returned."""
        page = AsyncMock()
        page.query_selector = AsyncMock(side_effect=Exception("parse error"))
        page.query_selector_all = AsyncMock(side_effect=Exception("parse error"))
        result = await parse_note_detail(page, "note123")
        assert result is None


# ============================================================
# parse_comment
# ============================================================


def _make_comment_el(
    comment_id: str = "comment-abc123",
    user_name: str = "Commenter",
    user_id: str = "usr001",
    content: str = "Test comment content",
    likes_text: str = "10",
    time_date: str = "01-15",
    ip_location: str = "广东",
    no_location: bool = False,
) -> AsyncMock:
    """Create a mock comment ElementHandle."""
    comment_el = AsyncMock()
    comment_el.get_attribute = AsyncMock(return_value=comment_id)

    def make_el(text):
        el = AsyncMock()
        el.inner_text = AsyncMock(return_value=text)
        return el

    user_name_el = make_el(user_name)
    user_link = AsyncMock()
    user_link.get_attribute = AsyncMock(return_value=f"/user/profile/{user_id}?x=1")
    content_el = make_el(content)
    like_el = make_el(likes_text)
    loc_el = make_el(ip_location) if not no_location else None
    # date holds time + IP location, if any (the site renders e.g. "01-15广东", location in Chinese)
    full_date = f"{time_date}{ip_location}" if ip_location and not no_location else time_date
    date_el = make_el(full_date)

    async def query_selector(sel: str):
        if ".right .author-wrapper .author a.name" in sel:
            return user_name_el
        if ".right .author-wrapper a[href*='/user/profile/']" in sel:
            return user_link
        if ".right .content .note-text" in sel:
            return content_el
        if ".right .info .interactions .like" in sel:
            return like_el
        if ".right .info .date .location" in sel:
            return loc_el
        if sel == ".right .info .date":
            return date_el
        return None

    comment_el.query_selector = query_selector
    return comment_el


class TestParseComment:
    """Test single comment parsing."""

    async def test_strips_comment_prefix_from_id(self):
        """Should strip the 'comment-' prefix and keep the bare ID."""
        el = _make_comment_el(comment_id="comment-xyz789")
        result = await parse_comment(el, "note123")
        assert result is not None
        assert result["comment_id"] == "xyz789"

    async def test_parses_user_name(self):
        """Should extract the commenter nickname correctly."""
        el = _make_comment_el(user_name="Li Si")
        result = await parse_comment(el, "note123")
        assert result is not None
        assert result["user_name"] == "Li Si"

    async def test_parses_user_id(self):
        """Should extract user_id from the user profile link."""
        el = _make_comment_el(user_id="UserXYZ")
        result = await parse_comment(el, "note123")
        assert result is not None
        assert result["user_id"] == "UserXYZ"

    async def test_parses_content(self):
        """Should extract the comment body correctly."""
        el = _make_comment_el(content="This comment is really helpful")
        result = await parse_comment(el, "note123")
        assert result is not None
        assert result["content"] == "This comment is really helpful"

    async def test_parses_likes_count(self):
        """Should parse the like count correctly."""
        el = _make_comment_el(likes_text="500")
        result = await parse_comment(el, "note123")
        assert result is not None
        assert result["likes"] == 500

    async def test_likes_zero_when_text_is_zan(self):
        """Should return 0 when the like text is '赞' (the site's Chinese placeholder for zero likes)."""
        el = _make_comment_el(likes_text="赞")
        result = await parse_comment(el, "note123")
        assert result is not None
        assert result["likes"] == 0

    async def test_strips_ip_location_from_time(self):
        """The time field should have the trailing IP location stripped."""
        el = _make_comment_el(time_date="01-15", ip_location="广东")
        result = await parse_comment(el, "note123")
        assert result is not None
        assert result["time"] == "01-15"
        assert result["ip_location"] == "广东"

    async def test_time_preserved_when_no_ip_location(self):
        """Without an IP location, the time field should be the full text of the .date container."""
        el = _make_comment_el(time_date="01-20", no_location=True)
        result = await parse_comment(el, "note123")
        assert result is not None
        assert result["time"] == "01-20"
        assert result["ip_location"] == ""

    async def test_note_id_preserved(self):
        """note_id should be preserved as passed in."""
        el = _make_comment_el()
        result = await parse_comment(el, "parent_note_999")
        assert result is not None
        assert result["note_id"] == "parent_note_999"

    async def test_result_contains_all_required_keys(self):
        """The returned dict should contain all required keys."""
        el = _make_comment_el()
        result = await parse_comment(el, "note123")
        assert result is not None
        required = {
            "comment_id", "note_id", "user_name", "user_id",
            "content", "likes", "time", "ip_location",
        }
        assert required.issubset(set(result.keys()))

    async def test_returns_none_on_exception(self):
        """Parsing exceptions should be caught and None returned."""
        el = AsyncMock()
        el.get_attribute = AsyncMock(side_effect=Exception("DOM error"))
        result = await parse_comment(el, "note123")
        assert result is None

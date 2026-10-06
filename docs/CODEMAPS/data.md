<!-- Generated: 2026-10-06 | Files scanned: 3 | Token estimate: ~700 -->

# Data Models & Storage — rednote-crawler

## Data Models

### Search Result (9 fields)
```python
{
    "note_id": str,          # extracted from URL
    "title": str,
    "author": str,
    "author_id": str,        # extracted from profile URL
    "cover_url": str,
    "likes": int,            # normalized ("1.2万" → 12000)
    "note_url": str,         # full URL (https://www.rednote.com/explore/{id}?...)
    "note_type": "image" | "video",
    "publish_time": str,
}
```

### Note Detail (14 fields)
```python
{
    "note_id": str,
    "title": str,
    "content": str,          # full text body
    "author": str,
    "author_id": str,
    "publish_time": str,
    "likes": int,
    "collects": int,
    "comments_count": int,
    "shares": int,
    "tags": list[str],       # hashtags
    "images": list[str],     # image URLs
    "note_type": "image" | "video",
    "video_url": str,
    "comments": list[dict],  # nested Comment objects
}
```

### Comment (8 fields)
```python
{
    "comment_id": str,
    "note_id": str,          # parent note reference
    "user_name": str,
    "user_id": str,
    "content": str,
    "likes": int,
    "time": str,
    "ip_location": str,
}
```

## Storage Format

### File Structure
```
data/
├── raw/
│   ├── {keyword}_{timestamp}.json          # search results
│   └── notes_{keyword}_{timestamp}.json    # note details + comments
└── processed/
    └── {keyword}_{timestamp}.xlsx          # 3-sheet workbook
```

### JSON Output
- UTF-8 encoding, `ensure_ascii=False`
- 2-space indent
- Includes metadata wrapper with keyword and timestamp

### Excel Output (openpyxl)
```
Sheet 1: "Search Results" — 8 columns (search fields minus cover_url)
Sheet 2: "Note Details"   — 13 columns (detail fields, tags joined with ";", nested removed)
Sheet 3: "Comments"       — 8 columns (all comments flattened)
```

Excel features:
- Frozen header row (row 1)
- Auto-filter on all columns
- Auto-width with CJK character handling (×2.1 factor)
- Filename sanitized (invalid chars removed)

### Field Mappings (Excel columns)

```
_SEARCH_FIELDS = [
    "note_id", "title", "author", "author_id",
    "likes", "note_type", "note_url", "publish_time",
]

_NOTE_FIELDS = [
    "note_id", "title", "content", "author", "author_id", "publish_time",
    "likes", "collects", "comments_count", "shares", "tags",
    "note_type", "note_url",
]

_COMMENT_FIELDS = [
    "comment_id", "note_id", "user_name", "user_id",
    "content", "likes", "time", "ip_location",
]
```

## Configuration (config/settings.yaml)

```yaml
crawler:
  keywords: [...]             # search terms
  max_notes_per_keyword: 20
  max_comments_per_note: 20
  scroll_pause: 1.5
  page_load_timeout: 30

delay:
  between_notes: [2, 5]       # random range (seconds)
  between_searches: [3, 8]
  scroll_interval: [1, 3]

storage:
  output_dir: "data"
  save_raw_json: true
  save_xlsx: true
```

## Persistent State

The crawler persists no login state: the rednote login lives in the user's own Chrome profile, which the crawler attaches to over CDP.

```
logs/daemon.pid      — pid of the background daemon (rednote.py start)
logs/daemon.log      — daemon stdout/stderr
logs/mcp_server.log  — rotating MCP server log
                       All gitignored
```

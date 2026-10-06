# rednote Data Crawler — Technical Plan

> Playwright-based browser automation that collects search result lists, note details, and comments (top 20)

## 1. Project Overview

### 1.1 Goals

Log in to rednote (https://www.rednote.com) with your own account and collect the following data through browser automation:

| Target | Description |
|----------|------|
| Search result list | Search by keyword and extract note summaries across multiple pages |
| Note details | Open the note page and extract the full content and engagement data |
| Comments (top 20) | Extract the top 20 comments under a note |

### 1.2 Technology Choices

| Component | Choice | Rationale |
|------|------|------|
| Language | Python 3.10 | Already configured in the project |
| Package manager | uv | Already configured in the project |
| Browser automation | Playwright | Real browser environment, async API |
| Anti-detection (stealth) | playwright-stealth | Removes automation traces such as `navigator.webdriver` |
| Anti-detection (fingerprint) | browserforge | Generates realistic browser fingerprints (UA, WebGL, Canvas, etc.) |
| Data storage | JSON + CSV | Flexible, easy to analyze later |
| Configuration | YAML | Externalizes search keywords and crawl parameters |
| Target site | `src/site.py` | `BASE_URL` defaults to `https://www.rednote.com`; override with the `REDNOTE_BASE_URL` env var (e.g. `https://www.xiaohongshu.com`, which serves the same web app) |

### 1.3 Anti-Detection Options and Selection

> **Core problem**: stock Playwright uses a real Chromium, but still exposes several detectable automation signals.

#### Detectable signals

| Signal | Description |
|------|------|
| `navigator.webdriver = true` | Set by Playwright by default; the most basic detection point |
| `HeadlessChrome` in UA | The User-Agent contains this marker in headless mode |
| WebGL fingerprint | An automated browser's rendering fingerprint differs from a real browser's |
| Canvas fingerprint | Canvas rendering output can be extracted for fingerprinting |
| Chrome DevTools Protocol | The CDP connection itself can be detected |
| `window.chrome.runtime` | Missing in automated browsers |
| Permissions API | Permission queries behave abnormally in automated browsers |

#### Comparison

| Option | Anti-detection strength | Ease of use | Maintenance | Best for |
|------|-----------|--------|----------|----------|
| **Stock Playwright** | Low — several signals are detectable | High | Active | Sites without anti-bot measures |
| **playwright-stealth** | Medium — covers the basic detection points | High (one line to integrate) | Active | Light to moderate anti-bot measures |
| **browserforge** | Medium-high — realistic fingerprint generation | High (injected into the context) | Active | Fingerprint detection |
| **stealth + browserforge** | **High** — two layers of protection | **High** | Active | **Recommended combination** |
| **Camoufox** | Very high — patched Firefox | Medium | Stalled | Heavy anti-bot measures |
| **Crawlee** | High — browserforge built in | Medium (heavier framework) | Active | Large-scale crawling |

#### Final choice: `playwright-stealth` + `browserforge`

**Rationale**:
1. **playwright-stealth** removes the basic automation traces (webdriver property, UA marker, Chrome Runtime, etc.)
2. **browserforge** generates fingerprints consistent with a real browser (UA, screen resolution, WebGL, Canvas, etc.), avoiding fingerprint-level detection
3. The two combine with little intrusion and no need to switch browser engines
4. For a personal account crawling at low to moderate frequency, this combination is stable enough

---

## 2. Project Structure

```
rednote-crawler/
├── .plan/                      # Planning documents
├── config/
│   └── settings.yaml           # Crawl config (keywords, page counts, delays, etc.)
├── src/
│   ├── __init__.py
│   ├── site.py                 # Target site config (BASE_URL / REDNOTE_BASE_URL)
│   ├── browser.py              # Browser management (launch, anti-detection, login state, persistence)
│   ├── stealth.py              # Anti-detection config (stealth + browserforge integration)
│   ├── auth.py                 # Login and session management
│   ├── search.py               # Search result collection
│   ├── note.py                 # Note detail collection
│   ├── comment.py              # Comment collection
│   ├── parser.py               # Page data parsing (DOM → structured data)
│   └── storage.py              # Data storage (JSON / CSV)
├── data/                       # Output directory for collected data
│   ├── raw/                    # Raw JSON data
│   └── processed/              # Processed CSV data
├── auth_state/                 # Stored browser login state (.gitignore)
├── main.py                     # Entry point
├── pyproject.toml
└── README.md
```

---

## 3. Detailed Module Design

### 3.1 Anti-Detection Config Module — `stealth.py`

**Responsibility**: integrate playwright-stealth and browserforge to provide anti-detection

**How it works**:

```
                  ┌────────────────────────────────────────┐
                  │              stealth.py                │
                  │                                        │
                  │  ┌──────────────────────────────────┐  │
                  │  │   browserforge                   │  │
                  │  │   Generates a real fingerprint   │  │
                  │  │   - User-Agent (matches OS/ver.) │  │
                  │  │   - Screen resolution            │  │
                  │  │   - WebGL rendering parameters   │  │
                  │  │   - Canvas fingerprint           │  │
                  │  │   - Language / platform          │  │
                  │  └────────────────┬─────────────────┘  │
                  │                   │                    │
                  │                   ▼                    │
                  │  ┌──────────────────────────────────┐  │
                  │  │   playwright-stealth             │  │
                  │  │   Removes automation traces      │  │
                  │  │   - Deletes navigator.webdriver  │  │
                  │  │   - Patches chrome.runtime       │  │
                  │  │   - Spoofs the Permissions API   │  │
                  │  │   - Strips HeadlessChrome UA     │  │
                  │  │   - Patches iframe contentWindow │  │
                  │  └────────────────┬─────────────────┘  │
                  │                   │                    │
                  │                   ▼                    │
                  │     Returns the configured context     │
                  └────────────────────────────────────────┘
```

**Interface design**:

```python
from browserforge.fingerprints import FingerprintGenerator
from playwright_stealth import stealth_async

class StealthConfig:
    """Anti-detection configuration manager"""

    def __init__(self):
        self.fingerprint_generator = FingerprintGenerator(
            browser="chrome",
            os="macos",          # match the local OS
        )

    def generate_fingerprint(self) -> dict:
        """Generate a realistic browser fingerprint"""
        return self.fingerprint_generator.generate()

    async def apply_stealth(self, page: Page) -> None:
        """Apply the stealth patches to a page"""
        await stealth_async(page)

    def get_context_options(self) -> dict:
        """Return browser context options with the fingerprint injected"""
        fingerprint = self.generate_fingerprint()
        return {
            "user_agent": fingerprint.navigator.userAgent,
            "viewport": {
                "width": fingerprint.screen.width,
                "height": fingerprint.screen.height,
            },
            "locale": fingerprint.navigator.language or "en-US",
            # no timezone_id: the context keeps the system timezone
            # other fingerprint parameters injected by browserforge
        }
```

**Key points**:
- A new fingerprint is generated on every browser launch, so a fixed fingerprint cannot be used to link sessions
- The fingerprint's browser version must match the actual Chromium version (otherwise the mismatch is detectable)
- The stealth patches are applied automatically whenever a new page opens
- The context does not pin a timezone (previously `Asia/Shanghai`); the locale falls back to `en-US`

### 3.2 Browser Management Module — `browser.py`

**Responsibility**: manage the lifecycle of the Playwright browser instance, with anti-detection integrated

- Launch the Chromium browser (switchable between headed and headless)
- Inject the fingerprint and stealth patches via `StealthConfig`
- Load saved login state (`storage_state`)
- Provide a single `BrowserManager` context manager

```python
class BrowserManager:
    """
    Usage:
        async with BrowserManager(headless=False) as bm:
            page = await bm.new_page()
            ...
    """
    def __init__(self, headless: bool = False):
        self.stealth = StealthConfig()

    async def __aenter__(self) -> "BrowserManager"
    async def __aexit__(self, *args) -> None
    async def new_page(self) -> Page:
        # 1. Create the context with the stealth fingerprint
        # 2. Create the page
        # 3. Apply the stealth patches to the page
        # 4. Return the page
        ...
    async def save_state(self) -> None      # save login state to auth_state/
    async def load_state(self) -> bool       # load existing login state
```

### 3.3 Login and Session Management Module — `auth.py`

**Responsibility**: handle first-time login and reuse of login state

**Flow**:

```
Start → check whether auth_state/state.json exists
  ├── Exists → load state → visit the home page → check whether it is still valid
  │     ├── Valid → continue crawling
  │     └── Expired → enter the manual login flow
  └── Missing → enter the manual login flow

Manual login flow:
  1. Open the rednote login page (headed mode)
  2. Prompt the user in the console to log in manually: scan the QR code
     with the rednote app, or use phone number + SMS code
  3. Detect a successful login (URL change or a specific element appearing)
  4. Save storage_state to auth_state/state.json
```

**Key design decisions**:
- Login state file path: `auth_state/state.json`
- Login success detection: wait for an element that marks the logged-in state to appear
- Timeout: wait 120 seconds for manual login

### 3.4 Search Result Collection Module — `search.py`

**Responsibility**: search by keyword and collect the result list

**Collection flow**:

```
1. Navigate to the rednote search page
2. Enter the keyword and trigger the search
3. Wait for the search results to load
4. Scroll the page to load more results (up to the configured pages/count)
5. Parse each search result card
6. Collect the list of note URLs for the detail collection step
```

**Fields collected**:

| Field | Description |
|------|------|
| `note_id` | Note ID (extracted from the URL) |
| `title` | Note title |
| `author` | Author nickname |
| `author_id` | Author ID |
| `cover_url` | Cover image URL |
| `likes` | Like count |
| `note_url` | Note detail page URL |
| `note_type` | Note type (image/video) |

**Pagination strategy**:
- rednote search results are a waterfall feed (infinite scroll)
- Simulate scrolling with `page.mouse.wheel()` or `page.evaluate("window.scrollBy()")`
- After each scroll, wait for new content to load (watch for changes in the DOM element count)
- Stop when the target count is reached or no new content appears

### 3.5 Note Detail Collection Module — `note.py`

**Responsibility**: open the note detail page and collect the full information

**Fields collected**:

| Field | Description |
|------|------|
| `note_id` | Note ID |
| `title` | Title |
| `content` | Body text (plain text) |
| `author` | Author nickname |
| `author_id` | Author ID |
| `publish_time` | Publish time |
| `likes` | Like count |
| `collects` | Collect (save) count |
| `comments_count` | Comment count |
| `shares` | Share count |
| `tags` | List of tags |
| `images` | List of image URLs |
| `note_type` | Image / video |
| `video_url` | Video URL (video notes) |

**Accepted note URLs**: `/explore/{id}`, `/discovery/item/{id}`, `/search_result/{id}` (the note ID is extracted from any of these paths).

**Collection flow**:

```
1. Open the note detail page URL
2. Wait for the core page content to finish loading
3. Parse the page DOM and extract the fields above
4. Trigger comment collection (call the comment module)
5. Move on to the next note after a random delay
```

### 3.6 Comment Collection Module — `comment.py`

**Responsibility**: collect the top 20 comments on the note detail page

**Fields collected**:

| Field | Description |
|------|------|
| `comment_id` | Comment ID |
| `note_id` | ID of the parent note |
| `user_name` | Commenter nickname |
| `user_id` | Commenter ID |
| `content` | Comment text |
| `likes` | Comment like count |
| `time` | Comment time |
| `ip_location` | IP location |

**Collection flow**:

```
1. Locate the comment section on the note detail page
2. Scroll the comment section to load more (if fewer than 20)
3. Extract the first 20 comments in order
4. Parse each comment's DOM element
```

### 3.7 Data Parsing Module — `parser.py`

**Responsibility**: convert page DOM elements into structured data

- Provide parsing functions for each page type
- Convert number formats (e.g. "1.2万" → 12000)
- Fill in defaults for missing fields
- Clean text content (strip extra whitespace and special characters)

```python
def parse_search_card(element: ElementHandle) -> dict
def parse_note_detail(page: Page) -> dict
def parse_comment(element: ElementHandle) -> dict
def normalize_count(text: str) -> int          # "1.2万" → 12000
```

### 3.8 Data Storage Module — `storage.py`

**Responsibility**: persist collected results locally

**Storage format**:

```
data/
├── raw/
│   └── {keyword}_{timestamp}.json          # complete raw data
└── processed/
    ├── search_results_{keyword}.csv         # search result summary
    ├── notes_{keyword}.csv                  # note detail summary
    └── comments_{keyword}.csv               # comment summary
```

- JSON: keeps the full structure, easy for programs to read
- CSV: flattened tables, easy to analyze with Excel / Pandas

> Implementation note: the shipped `storage.py` writes one Excel workbook (`processed/{keyword}_{timestamp}.xlsx`) instead of CSV files, with three sheets named "Search Results", "Note Details", and "Comments".

---

## 4. Configuration File Design

`config/settings.yaml`:

```yaml
# Crawl settings
crawler:
  keywords:                     # list of search keywords
    - "keyword 1"
    - "keyword 2"
  max_notes_per_keyword: 20     # max notes to collect per keyword
  max_comments_per_note: 20     # max comments to collect per note
  scroll_pause: 1.5             # wait after each scroll (seconds)
  page_load_timeout: 30         # page load timeout (seconds)

# Delay settings (mimic human behaviour to reduce risk)
delay:
  between_notes: [2, 5]         # random delay range between notes (seconds)
  between_searches: [3, 8]      # random delay range between searches (seconds)
  scroll_interval: [1, 3]       # random delay range between scrolls (seconds)

# Browser settings
browser:
  headless: false               # headless mode (false recommended while debugging)
  viewport_width: 1280
  viewport_height: 800

# Storage settings
storage:
  output_dir: "data"
  save_raw_json: true           # save raw JSON
  save_csv: true                # save CSV
```

---

## 5. Main Crawl Flow

```
┌───────────────┐
│ Start program │
└───────┬───────┘
        │
        ▼
┌───────────────┐     ┌──────────────┐
│  Load config  │────▶│ Init browser │
└───────────────┘     └──────┬───────┘
                             │
                             ▼
                    ┌──────────────────┐   fail    ┌───────────────────┐
                    │ Load login state │──────────▶│ Manual login flow │
                    └────────┬─────────┘           └─────────┬─────────┘
                             │ ok                            │
                             ▼                               │
                    ┌──────────────────┐◀────────────────────┘
                    │ Save login state │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌───────────┐  ┌───────────┐  ┌───────────┐
        │ Keyword 1 │  │ Keyword 2 │  │ Keyword N │
        └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
              │              │              │
              ▼              ▼              ▼
        ┌─────────────────────────────────────────┐
        │     Search → scroll → collect list      │
        └────────────────────┬────────────────────┘
                             │
                             ▼
        ┌─────────────────────────────────────────┐
        │ For each note URL → details + comments  │
        │ (random delay between notes)            │
        └────────────────────┬────────────────────┘
                             │
                             ▼
        ┌─────────────────────────────────────────┐
        │        Data storage (JSON + CSV)        │
        └─────────────────────────────────────────┘
```

---

## 6. Anti-Bot and Stability Strategy

### 6.1 Anti-Detection Layers (three layers)

```
┌──────────────────────────────────────────────────────┐
│  Layer 3: Behaviour                                  │
│  - Random delays (mimic a human pace)                │
│  - Random scroll distances (not fixed pixels)        │
│  - Mouse movement paths (no teleporting)             │
│  - Small random viewport adjustments                 │
├──────────────────────────────────────────────────────┤
│  Layer 2: Fingerprint — browserforge                 │
│  - Realistic User-Agent (matches OS + browser ver.)  │
│  - Screen resolution / colour depth / pixel ratio    │
│  - WebGL renderer / vendor information               │
│  - Canvas fingerprint consistency                    │
│  - Language / platform properties                    │
├──────────────────────────────────────────────────────┤
│  Layer 1: Environment — playwright-stealth           │
│  - Deletes navigator.webdriver                       │
│  - Patches chrome.runtime                            │
│  - Spoofs the Permissions API                        │
│  - Strips the HeadlessChrome UA marker               │
│  - Patches iframe contentWindow                      │
│  - Patches navigator.plugins                         │
└──────────────────────────────────────────────────────┘
```

### 6.2 Stability Strategy

| Strategy | Implementation |
|------|----------|
| Random delays | Add a `random.uniform(min, max)` delay between operations |
| Fingerprint rotation | Generate a new fingerprint on each browser launch to avoid linkage and tracking |
| Login state reuse | Persist `storage_state` to avoid frequent logins |
| Retry on error | Retry failed page loads twice; beyond that, skip and log |
| Failure recovery | Data already collected is not lost if a crawl is interrupted (written as it goes) |
| Rate control | Configurable delay parameters to tune crawl speed as needed |
| Detection awareness | Pause and notify the user on a CAPTCHA / risk-control page |

---

## 7. Implementation Steps (development order)

### Phase 1: Foundation + Anti-Detection
- [x] Initialize project dependencies (playwright, playwright-stealth, browserforge, pyyaml)
- [x] Implement `stealth.py` — anti-detection config (stealth patches + fingerprint generation)
- [x] Implement `browser.py` — browser lifecycle management (stealth integrated)
- [x] Implement `auth.py` — login and session persistence
- [x] Verify: the browser passes an anti-detection test site (e.g. bot.sannysoft.com) — `scripts/verify_stealth.py`
- [x] Verify: manual login works and login state can be saved/reused — `scripts/verify_login.py`

### Phase 2: Search Collection
- [x] Implement `search.py` — search result list collection
- [x] Implement `parser.py` — search card parsing
- [x] Implement `storage.py` — JSON / CSV storage
- [x] Verify: can search by keyword and export the search results

### Phase 3: Details and Comments
- [x] Implement `note.py` — note detail collection
- [x] Implement `comment.py` — comment collection
- [x] Extend `parser.py` — detail page and comment parsing
- [x] Extend `storage.py` — note detail and comment storage
- [x] Verify: can collect full note details + top 20 comments — `scripts/verify_note.py`

### Phase 4: Integration and Polish
- [x] Implement `main.py` — wire up the full crawl pipeline
- [x] Implement config file loading (`settings.yaml`)
- [x] Add logging (crawl progress, error messages)
- [x] End-to-end test: keyword → search → details → comments → export (`scripts/verify_e2e.py`)

---

## 8. Dependency List

```
playwright              # browser automation core
playwright-stealth      # anti-detection: removes automation traces
browserforge            # anti-detection: realistic browser fingerprint generation
pyyaml                  # config file parsing
```

Install commands:

```bash
uv add playwright playwright-stealth browserforge pyyaml
uv run playwright install chromium
```

---

## 9. Notes

1. **Personal use only** — this tool is only for collecting data with a personal account, not for commercial use or large-scale scraping
2. **Reasonable frequency** — control the crawl speed with the delay settings to avoid putting load on the platform
3. **Login state security** — the `auth_state/` directory is in `.gitignore` and will not be committed
4. **Data security** — the `data/` directory should also be added to `.gitignore`

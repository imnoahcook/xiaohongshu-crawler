"""
Target site configuration.

rednote.com is the international web frontend of Xiaohongshu. It serves the
same web app as xiaohongshu.com (same routes and DOM), so the crawler only
needs to know which origin to talk to.

Set REDNOTE_BASE_URL to point the crawler at another origin, e.g.
    REDNOTE_BASE_URL=https://www.rednote.com
"""

from __future__ import annotations

import os

BASE_URL = os.environ.get("REDNOTE_BASE_URL", "https://www.rednote.com").rstrip("/")

HOME_URL = BASE_URL
EXPLORE_URL = f"{BASE_URL}/explore"
SEARCH_URL = BASE_URL + "/search_result?keyword={keyword}&type=51"

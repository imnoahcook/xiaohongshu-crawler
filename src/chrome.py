"""
Everyday Chrome connection

The crawler does not launch a browser. It attaches to the Google Chrome you
already have open, over the Chrome DevTools Protocol, and works in new tabs
there. That way it uses your existing rednote login and your real browser.

One-time setup: open chrome://inspect/#remote-debugging in Chrome and turn on
"Allow remote debugging for this browser instance". Chrome then writes its
DevTools port to a DevToolsActivePort file in its user data directory, which is
what this module reads. Chrome asks you to allow each incoming connection.

Environment variables:
    REDNOTE_CHROME_USER_DATA_DIR   Chrome user data directory, if it is not in
                                   the default location for your OS
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SETUP_HINT = (
    "Open chrome://inspect/#remote-debugging in Chrome and turn on "
    '"Allow remote debugging for this browser instance", then retry.'
)


class ChromeNotAvailableError(RuntimeError):
    """Chrome is not running, or remote debugging is not enabled in it."""


def user_data_dir() -> Path:
    """Return the user data directory of the everyday Chrome."""
    override = os.environ.get("REDNOTE_CHROME_USER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Google/Chrome"
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "Google/Chrome/User Data"
    return Path.home() / ".config/google-chrome"


def devtools_ws_url() -> str:
    """Return the DevTools WebSocket URL of the running everyday Chrome.

    Raises:
        ChromeNotAvailableError: remote debugging is not enabled, or Chrome is not running
    """
    port_file = user_data_dir() / "DevToolsActivePort"
    try:
        # Two lines: the port, then the browser target path
        port, path = port_file.read_text().split()
    except (OSError, ValueError) as e:
        raise ChromeNotAvailableError(
            f"Could not read {port_file}. Is Chrome running? {_SETUP_HINT}"
        ) from e
    return f"ws://127.0.0.1:{port}{path}"

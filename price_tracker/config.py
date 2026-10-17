"""Central place for default settings, so nothing important is hard-coded elsewhere."""

from __future__ import annotations

import os
from pathlib import Path

from price_tracker import __version__

#: Root of the site we scrape. books.toscrape.com is a sandbox built for scraping practice.
BASE_URL = "https://books.toscrape.com/"

#: Identify ourselves honestly so the site owner knows who is calling.
#: Override with the PRICE_TRACKER_USER_AGENT environment variable to add your contact details.
USER_AGENT = os.environ.get(
    "PRICE_TRACKER_USER_AGENT",
    f"price-tracker/{__version__} (polite price-monitoring bot; contact: you@example.com)",
)

#: Seconds to wait between requests (raised automatically if robots.txt asks for more).
REQUEST_DELAY = 0.5

#: How many times to retry a failed request before giving up on it.
MAX_RETRIES = 3

#: First retry waits this long; each further retry doubles it (1s, 2s, 4s...).
BACKOFF_BASE = 1.0

#: Per-request timeout in seconds.
TIMEOUT = 20.0

#: Default folders, relative to the current working directory.
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_DB_PATH = Path("data") / "price_history.db"
DEFAULT_LOG_DIR = Path("logs")

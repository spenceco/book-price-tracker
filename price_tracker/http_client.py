"""A small, polite HTTP client built on httpx.

"Polite" means it:
* reads robots.txt once and refuses to fetch disallowed URLs,
* waits a fixed delay between requests (or the robots.txt Crawl-delay, if longer),
* retries temporary failures (network errors, HTTP 429 and 5xx) with
  exponential backoff, honouring a ``Retry-After`` header when present,
* sends a descriptive User-Agent so the site owner knows who is visiting.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Self
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import httpx

from price_tracker import config

log = logging.getLogger(__name__)

#: Status codes worth retrying: rate limiting and server-side errors.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RobotsDisallowedError(Exception):
    """Raised when robots.txt forbids fetching a URL."""


class FetchError(Exception):
    """Raised when a URL still fails after all retries."""


class PoliteClient:
    """Fetch pages one at a time, with delays, retries and robots.txt checks.

    Use it as a context manager so the connection pool is closed afterwards::

        with PoliteClient("https://books.toscrape.com/") as client:
            html = client.get_html("https://books.toscrape.com/index.html")
    """

    def __init__(
        self,
        base_url: str = config.BASE_URL,
        *,
        user_agent: str = config.USER_AGENT,
        delay: float = config.REQUEST_DELAY,
        max_retries: int = config.MAX_RETRIES,
        backoff_base: float = config.BACKOFF_BASE,
        timeout: float = config.TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # ``transport`` and ``sleep`` exist so tests can fake the network and
        # skip real waiting; normal callers never pass them.
        self.base_url = base_url
        self.user_agent = user_agent
        self.delay = delay
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._sleep = sleep
        self._last_request: float | None = None
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._robots = self._load_robots()

    # -- context manager -------------------------------------------------
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    # -- robots.txt ------------------------------------------------------
    def _load_robots(self) -> RobotFileParser:
        """Download and parse robots.txt, following the usual conventions.

        * 404 (no robots.txt) -> everything is allowed.
        * 401/403            -> treat the whole site as off-limits.
        * anything else bad  -> raise, rather than guess.
        """
        robots_url = urljoin(self.base_url, "/robots.txt")
        parser = RobotFileParser(robots_url)
        response = self._request(robots_url)
        if response.status_code in (401, 403):
            log.warning("robots.txt returned %s; treating site as disallowed", response.status_code)
            parser.parse(["User-agent: *", "Disallow: /"])
        elif 400 <= response.status_code < 500:
            log.info("No robots.txt found (HTTP %s); all paths allowed", response.status_code)
            parser.parse([])  # no rules = everything allowed
        else:
            parser.parse(response.text.splitlines())
            crawl_delay = parser.crawl_delay(self.user_agent)
            if crawl_delay and float(crawl_delay) > self.delay:
                log.info("robots.txt asks for a %ss crawl delay; using it", crawl_delay)
                self.delay = float(crawl_delay)
        return parser

    def is_allowed(self, url: str) -> bool:
        """True if robots.txt lets our User-Agent fetch ``url``."""
        return self._robots.can_fetch(self.user_agent, url)

    # -- fetching --------------------------------------------------------
    def _wait_for_turn(self) -> None:
        """Sleep just long enough to keep ``delay`` seconds between requests."""
        if self._last_request is not None:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.delay:
                self._sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def _backoff_seconds(self, attempt: int, response: httpx.Response | None) -> float:
        """How long to wait before retry number ``attempt`` (1-based)."""
        if response is not None:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                return float(retry_after)
        return self.backoff_base * 2 ** (attempt - 1)

    def _request(self, url: str) -> httpx.Response:
        """GET ``url`` with delay + retries. Returns the final response.

        Non-retryable responses (e.g. 404) are returned as-is for the caller
        to judge; retryable ones are retried and finally raise ``FetchError``.
        """
        last_problem = ""
        for attempt in range(1, self.max_retries + 2):  # first try + retries
            self._wait_for_turn()
            response: httpx.Response | None = None
            try:
                response = self._client.get(url)
                if response.status_code not in RETRYABLE_STATUS:
                    return response
                last_problem = f"HTTP {response.status_code}"
            except httpx.TransportError as exc:  # timeouts, DNS, connection resets
                last_problem = f"{type(exc).__name__}: {exc}"

            if attempt > self.max_retries:
                break
            wait = self._backoff_seconds(attempt, response)
            log.warning(
                "Request failed (%s) for %s; retry %d/%d in %.1fs",
                last_problem, url, attempt, self.max_retries, wait,
            )
            self._sleep(wait)
        raise FetchError(f"Giving up on {url} after {self.max_retries} retries ({last_problem})")

    def get_html(self, url: str) -> bytes:
        """Fetch a page and return its raw bytes (BeautifulSoup detects the encoding).

        Raises ``RobotsDisallowedError`` or ``FetchError``.
        """
        if not self.is_allowed(url):
            raise RobotsDisallowedError(f"robots.txt disallows {url}")
        response = self._request(url)
        if response.is_error:
            raise FetchError(f"HTTP {response.status_code} for {url}")
        log.debug("Fetched %s (%d bytes)", url, len(response.content))
        return response.content

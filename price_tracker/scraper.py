"""Walk the site category by category and collect every book.

Scraping by category (instead of the single 50-page catalogue) means each
book's category comes straight from the listing page, so we never have to
open 1,000 individual product pages. A full run is about 70 requests.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from price_tracker import config, parser
from price_tracker.http_client import FetchError, PoliteClient, RobotsDisallowedError
from price_tracker.models import Category, ScrapeResult

log = logging.getLogger(__name__)


class UnknownCategoryError(ValueError):
    """Raised when ``--category`` names a category the site doesn't have."""


def select_categories(available: list[Category], wanted: list[str] | None) -> list[Category]:
    """Filter the site's categories down to the ones the user asked for.

    Matching is case-insensitive. ``None`` or an empty list means "all".
    """
    if not wanted:
        return available
    by_name = {category.name.lower(): category for category in available}
    unknown = [name for name in wanted if name.lower() not in by_name]
    if unknown:
        names = ", ".join(sorted(c.name for c in available))
        raise UnknownCategoryError(
            f"Unknown category: {', '.join(unknown)}. Available categories: {names}"
        )
    return [by_name[name.lower()] for name in wanted]


def scrape(
    client: PoliteClient,
    categories: list[str] | None = None,
    max_pages: int | None = None,
    base_url: str = config.BASE_URL,
) -> ScrapeResult:
    """Scrape books from the chosen categories.

    Args:
        client: an open :class:`PoliteClient`.
        categories: category names to include (``None`` = all of them).
        max_pages: stop after this many listing pages *per category*.
        base_url: the site's home page.

    Problems with individual pages are logged and counted in
    ``result.errors`` rather than stopping the run.
    """
    result = ScrapeResult()
    scraped_at = datetime.now(UTC).replace(microsecond=0)

    home_url = base_url.rstrip("/") + "/index.html"
    all_categories = parser.parse_categories(client.get_html(home_url), home_url)
    log.info("Found %d categories on the site", len(all_categories))
    selected = select_categories(all_categories, categories)

    for number, category in enumerate(selected, start=1):
        url: str | None = category.url
        page = 0
        complete = True
        before = len(result.books)
        while url:
            if max_pages is not None and page >= max_pages:
                complete = False  # we deliberately skipped pages
                break
            page += 1
            try:
                html = client.get_html(url)
                result.books.extend(
                    parser.parse_book_list(html, url, category.name, scraped_at)
                )
                url = parser.parse_next_page(html, url)
            except (FetchError, RobotsDisallowedError, ValueError) as exc:
                message = f"{category.name} page {page}: {exc}"
                log.error(message)
                result.errors.append(message)
                complete = False
                break  # without this page we can't find the next one
        if complete:
            result.complete_categories.add(category.name)
        log.info(
            "[%*d/%d] %-20s %3d books from %d page(s)",
            len(str(len(selected))), number, len(selected), category.name, len(result.books) - before, page,
        )

    return result

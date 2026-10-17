"""Turn raw HTML from books.toscrape.com into Python objects.

Every function here is *pure*: it takes HTML text and returns data, with no
network access. That makes the parsing logic easy to unit-test against saved
HTML files in ``tests/fixtures``.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from price_tracker.models import Book, Category

#: The site shows ratings as a CSS class word, e.g. <p class="star-rating Three">.
RATING_WORDS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}

_PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _soup(html: str | bytes) -> BeautifulSoup:
    """Parse HTML with the fast lxml parser."""
    return BeautifulSoup(html, "lxml")


def _attr(tag: Tag, name: str) -> str:
    """Read an HTML attribute as a plain string ("" if absent)."""
    value = tag.get(name)
    return " ".join(value) if isinstance(value, list) else (value or "")


def parse_price(text: str) -> float:
    """Extract the number from a price string such as ``'£51.77'``.

    Raises ``ValueError`` if no number is present, so bad data is never
    silently stored as 0.
    """
    match = _PRICE_RE.search(text.replace(",", ""))
    if not match:
        raise ValueError(f"No price found in {text!r}")
    return float(match.group(1))


def parse_rating(tag: Tag | None) -> int:
    """Convert ``<p class="star-rating Four">`` into ``4`` (0 if missing)."""
    if tag is None:
        return 0
    for css_class in tag.get("class", []):
        if css_class in RATING_WORDS:
            return RATING_WORDS[css_class]
    return 0


def parse_categories(html: str | bytes, page_url: str) -> list[Category]:
    """Read the category list from the sidebar of the home page.

    The sidebar has a top-level "Books" link with the real categories nested
    beneath it; we only return the nested ones.
    """
    soup = _soup(html)
    links = soup.select("div.side_categories ul.nav-list > li > ul > li > a")
    return [
        Category(name=link.get_text(strip=True), url=urljoin(page_url, _attr(link, "href")))
        for link in links
    ]


def parse_category_name(html: str | bytes) -> str:
    """Return the category heading (the ``<h1>``) of a listing page."""
    heading = _soup(html).select_one("div.page-header h1")
    return heading.get_text(strip=True) if heading else "Unknown"


def parse_book_list(
    html: str | bytes, page_url: str, category: str, scraped_at: datetime
) -> list[Book]:
    """Extract every book card (``article.product_pod``) on a listing page.

    ``page_url`` is needed to turn the relative product links into full URLs.
    """
    soup = _soup(html)
    books: list[Book] = []
    for card in soup.select("article.product_pod"):
        link = card.select_one("h3 a")
        price = card.select_one("p.price_color")
        if link is None or price is None:
            # A malformed card should not break the whole page.
            continue
        availability = card.select_one("p.availability")
        stock_text = availability.get_text(" ", strip=True).lower() if availability else ""
        books.append(
            Book(
                # The visible text is truncated ("A Light in the ..."), the
                # title attribute holds the full title.
                title=_attr(link, "title") or link.get_text(strip=True),
                price=parse_price(price.get_text()),
                rating=parse_rating(card.select_one("p.star-rating")),
                in_stock="in stock" in stock_text,
                category=category,
                url=urljoin(page_url, _attr(link, "href")),
                scraped_at=scraped_at,
            )
        )
    return books


def parse_next_page(html: str | bytes, page_url: str) -> str | None:
    """Return the absolute URL of the "next" page, or ``None`` on the last page."""
    next_link = _soup(html).select_one("ul.pager li.next a")
    return urljoin(page_url, _attr(next_link, "href")) if next_link else None

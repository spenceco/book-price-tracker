"""Shared pytest fixtures: saved HTML pages and sample data."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from price_tracker.models import Book

FIXTURES = Path(__file__).parent / "fixtures"

#: The URLs the saved pages were downloaded from (needed to resolve relative links).
HOME_URL = "https://books.toscrape.com/index.html"
MYSTERY_P1_URL = "https://books.toscrape.com/catalogue/category/books/mystery_3/index.html"
MYSTERY_P2_URL = "https://books.toscrape.com/catalogue/category/books/mystery_3/page-2.html"

SCRAPED_AT = datetime(2026, 10, 17, 6, 0, tzinfo=UTC)


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def home_html() -> bytes:
    return load("index.html")


@pytest.fixture
def mystery_page1() -> bytes:
    return load("category_page1.html")


@pytest.fixture
def mystery_page2() -> bytes:
    return load("category_page2.html")


def make_book(title: str = "Test Book", price: float = 10.0, category: str = "Mystery",
              url: str | None = None, **kwargs: object) -> Book:
    """Build a Book with sensible defaults so tests only state what matters."""
    defaults = {"rating": 3, "in_stock": True, "scraped_at": SCRAPED_AT}
    defaults.update(kwargs)
    return Book(title=title, price=price, category=category,
                url=url or f"https://books.toscrape.com/catalogue/{title.lower().replace(' ', '-')}/index.html",
                **defaults)  # type: ignore[arg-type]

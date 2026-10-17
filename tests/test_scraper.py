"""End-to-end scraper test: the saved pages are served by a fake client."""

from __future__ import annotations

import pytest

from price_tracker import scraper
from price_tracker.http_client import FetchError
from tests.conftest import HOME_URL, MYSTERY_P1_URL, MYSTERY_P2_URL, load


class FakeClient:
    """Stands in for PoliteClient, returning fixture HTML by URL."""

    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def get_html(self, url: str) -> bytes:
        self.requested.append(url)
        if url not in self.pages:
            raise FetchError(f"HTTP 404 for {url}")
        return self.pages[url]


@pytest.fixture
def client() -> FakeClient:
    return FakeClient({
        HOME_URL: load("index.html"),
        MYSTERY_P1_URL: load("category_page1.html"),
        MYSTERY_P2_URL: load("category_page2.html"),
    })


def test_follows_pagination(client: FakeClient) -> None:
    result = scraper.scrape(client, ["mystery"])  # case-insensitive
    assert len(result.books) == 32
    assert {b.category for b in result.books} == {"Mystery"}
    assert result.complete_categories == {"Mystery"}
    assert result.errors == []


def test_max_pages_limits_and_marks_incomplete(client: FakeClient) -> None:
    result = scraper.scrape(client, ["Mystery"], max_pages=1)
    assert len(result.books) == 20
    assert MYSTERY_P2_URL not in client.requested
    assert result.complete_categories == set()


def test_page_failure_is_recorded_not_fatal(client: FakeClient) -> None:
    del client.pages[MYSTERY_P2_URL]
    result = scraper.scrape(client, ["Mystery"])
    assert len(result.books) == 20
    assert len(result.errors) == 1 and "Mystery page 2" in result.errors[0]
    assert result.complete_categories == set()


def test_unknown_category_lists_valid_names(client: FakeClient) -> None:
    with pytest.raises(scraper.UnknownCategoryError, match="Available categories: .*Mystery"):
        scraper.scrape(client, ["Cookbooks"])

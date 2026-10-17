"""Parsing tests against real pages saved from books.toscrape.com (no network)."""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from price_tracker import parser
from tests.conftest import HOME_URL, MYSTERY_P1_URL, MYSTERY_P2_URL, SCRAPED_AT


class TestParsePrice:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("£51.77", 51.77), ("Â£13.99", 13.99), ("  £1,234.50 ", 1234.50), ("£10", 10.0)],
    )
    def test_valid_prices(self, text: str, expected: float) -> None:
        assert parser.parse_price(text) == expected

    def test_missing_price_raises(self) -> None:
        with pytest.raises(ValueError):
            parser.parse_price("Price on request")


class TestParseRating:
    @pytest.mark.parametrize(("word", "stars"), [("One", 1), ("Three", 3), ("Five", 5)])
    def test_rating_words(self, word: str, stars: int) -> None:
        tag = BeautifulSoup(f'<p class="star-rating {word}"></p>', "lxml").p
        assert parser.parse_rating(tag) == stars

    def test_missing_rating_is_zero(self) -> None:
        assert parser.parse_rating(None) == 0
        tag = BeautifulSoup('<p class="star-rating"></p>', "lxml").p
        assert parser.parse_rating(tag) == 0


class TestParseCategories:
    def test_finds_all_50_categories(self, home_html: bytes) -> None:
        categories = parser.parse_categories(home_html, HOME_URL)
        assert len(categories) == 50

    def test_excludes_top_level_books_link(self, home_html: bytes) -> None:
        names = [c.name for c in parser.parse_categories(home_html, HOME_URL)]
        assert "Books" not in names
        assert names[0] == "Travel"
        assert "Mystery" in names

    def test_urls_are_absolute(self, home_html: bytes) -> None:
        mystery = next(c for c in parser.parse_categories(home_html, HOME_URL) if c.name == "Mystery")
        assert mystery.url == MYSTERY_P1_URL


class TestParseBookList:
    def test_first_page_has_20_books(self, mystery_page1: bytes) -> None:
        books = parser.parse_book_list(mystery_page1, MYSTERY_P1_URL, "Mystery", SCRAPED_AT)
        assert len(books) == 20

    def test_last_page_has_remaining_books(self, mystery_page2: bytes) -> None:
        books = parser.parse_book_list(mystery_page2, MYSTERY_P2_URL, "Mystery", SCRAPED_AT)
        assert len(books) == 12  # 32 mystery books in total

    def test_first_book_fields(self, mystery_page1: bytes) -> None:
        book = parser.parse_book_list(mystery_page1, MYSTERY_P1_URL, "Mystery", SCRAPED_AT)[0]
        assert book.title == "Sharp Objects"
        assert book.price == 47.82
        assert book.rating == 4
        assert book.in_stock is True
        assert book.stock_status == "In stock"
        assert book.category == "Mystery"
        assert book.url == "https://books.toscrape.com/catalogue/sharp-objects_997/index.html"
        assert book.scraped_at == SCRAPED_AT

    def test_uses_full_title_not_truncated_text(self, mystery_page1: bytes) -> None:
        books = parser.parse_book_list(mystery_page1, MYSTERY_P1_URL, "Mystery", SCRAPED_AT)
        assert not any(b.title.endswith("...") for b in books)

    def test_all_books_valid(self, mystery_page1: bytes, mystery_page2: bytes) -> None:
        books = parser.parse_book_list(mystery_page1, MYSTERY_P1_URL, "Mystery", SCRAPED_AT)
        books += parser.parse_book_list(mystery_page2, MYSTERY_P2_URL, "Mystery", SCRAPED_AT)
        assert all(b.price > 0 for b in books)
        assert all(1 <= b.rating <= 5 for b in books)
        assert len({b.url for b in books}) == len(books)  # no duplicates

    def test_out_of_stock_and_malformed_cards(self) -> None:
        html = """
        <article class="product_pod">
          <p class="star-rating Two"></p>
          <h3><a href="../../x_1/index.html" title="Gone Book">Gone...</a></h3>
          <p class="price_color">£5.00</p>
          <p class="availability">Out of stock</p>
        </article>
        <article class="product_pod"><h3>No link or price</h3></article>
        """
        books = parser.parse_book_list(html, MYSTERY_P1_URL, "Mystery", SCRAPED_AT)
        assert len(books) == 1
        assert books[0].in_stock is False
        assert books[0].stock_status == "Out of stock"

    def test_empty_page(self) -> None:
        assert parser.parse_book_list("<html></html>", MYSTERY_P1_URL, "X", SCRAPED_AT) == []


class TestPagination:
    def test_next_page_link(self, mystery_page1: bytes) -> None:
        assert parser.parse_next_page(mystery_page1, MYSTERY_P1_URL) == MYSTERY_P2_URL

    def test_last_page_has_no_next(self, mystery_page2: bytes) -> None:
        assert parser.parse_next_page(mystery_page2, MYSTERY_P2_URL) is None

    def test_category_heading(self, mystery_page1: bytes) -> None:
        assert parser.parse_category_name(mystery_page1) == "Mystery"

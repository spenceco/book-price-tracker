"""Plain data containers shared by the scraper, database and exporters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class Category:
    """A book category from the site's sidebar, e.g. ``Mystery``."""

    name: str
    url: str


@dataclass(frozen=True)
class Book:
    """One book as seen on one scrape.

    The product URL is unique per book, so it is used as the book's ID.
    """

    title: str
    price: float  # in GBP
    rating: int  # 1-5 stars (0 if the page had no rating)
    in_stock: bool
    category: str
    url: str
    scraped_at: datetime

    @property
    def stock_status(self) -> str:
        """Human-friendly stock label for reports."""
        return "In stock" if self.in_stock else "Out of stock"


class ChangeType(str, Enum):
    """Kinds of differences detected between two runs."""

    NEW = "New book"
    REMOVED = "Removed"
    PRICE_UP = "Price increase"
    PRICE_DOWN = "Price decrease"


@dataclass(frozen=True)
class Change:
    """A single difference between this run and the stored history."""

    change_type: ChangeType
    title: str
    category: str
    url: str
    old_price: float | None = None
    new_price: float | None = None

    @property
    def difference(self) -> float | None:
        """Absolute price change (new - old), when both prices are known."""
        if self.old_price is None or self.new_price is None:
            return None
        return round(self.new_price - self.old_price, 2)

    @property
    def percent_change(self) -> float | None:
        """Price change as a fraction of the old price (0.1 == +10%)."""
        if self.difference is None or not self.old_price:
            return None
        return self.difference / self.old_price


@dataclass
class ScrapeResult:
    """Everything one scrape produced, including what went wrong."""

    books: list[Book] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: Categories whose every page was fetched successfully. Only these are
    #: safe to use for "removed book" detection.
    complete_categories: set[str] = field(default_factory=set)

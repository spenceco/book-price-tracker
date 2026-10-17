"""SQLite storage for price history, and the logic that spots changes.

Tables
------
books          one row per book (keyed by product URL) with its latest data
price_history  one row per book per run: the full price time series
runs           one row per run with its summary numbers
changes        every detected change, so past runs can be reviewed later
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from price_tracker.models import Book, Change, ChangeType, ScrapeResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    books_scraped INTEGER DEFAULT 0,
    new_books     INTEGER DEFAULT 0,
    removed_books INTEGER DEFAULT 0,
    price_changes INTEGER DEFAULT 0,
    errors        INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS books (
    url           TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    category      TEXT NOT NULL,
    price         REAL NOT NULL,
    rating        INTEGER,
    in_stock      INTEGER,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1   -- 0 once the book disappears
);
CREATE TABLE IF NOT EXISTS price_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT NOT NULL REFERENCES books(url),
    run_id     INTEGER NOT NULL REFERENCES runs(id),
    price      REAL NOT NULL,
    scraped_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_url ON price_history(url);
CREATE TABLE IF NOT EXISTS changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    url         TEXT NOT NULL,
    change_type TEXT NOT NULL,
    old_price   REAL,
    new_price   REAL
);
"""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class PriceDatabase:
    """Thin wrapper around a SQLite file holding the price history."""

    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- runs ------------------------------------------------------------
    def start_run(self) -> int:
        """Create a run record and return its ID."""
        with self.conn:
            cursor = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def finish_run(self, run_id: int, books: int, changes: list[Change], errors: int) -> None:
        """Store the run's summary numbers."""
        counts = count_changes(changes)
        with self.conn:
            self.conn.execute(
                """UPDATE runs SET finished_at=?, books_scraped=?, new_books=?,
                   removed_books=?, price_changes=?, errors=? WHERE id=?""",
                (_now(), books, counts["new"], counts["removed"], counts["price"], errors, run_id),
            )

    # -- the main job: compare and save ----------------------------------
    def record_scrape(self, run_id: int, result: ScrapeResult) -> list[Change]:
        """Compare a scrape with what we knew before, save it, and return the changes.

        Rules:
        * **New book** - a URL we've never seen, in a category we already
          track. (The first time a category is scraped is a *baseline*, so
          its books aren't all reported as "new".)
        * **Price change** - a known book whose price differs from last time.
        * **Removed** - an active book in a *fully* scraped category that
          didn't appear this time. Partial categories (``--max-pages`` or a
          failed page) are skipped, so we never report false removals.
        """
        known = {row["url"]: row for row in self.conn.execute("SELECT * FROM books")}
        tracked_categories = {row["category"] for row in known.values()}
        changes: list[Change] = []
        seen: set[str] = set()

        with self.conn:  # one transaction: all-or-nothing
            for book in result.books:
                if book.url in seen:  # same book listed twice on the site
                    continue
                seen.add(book.url)
                old = known.get(book.url)
                if old is None:
                    if book.category in tracked_categories:
                        changes.append(_change(ChangeType.NEW, book, new_price=book.price))
                    self._insert_book(book)
                else:
                    if not old["active"]:  # it came back after being removed
                        changes.append(_change(ChangeType.NEW, book, new_price=book.price))
                    elif round(old["price"], 2) != round(book.price, 2):
                        kind = ChangeType.PRICE_UP if book.price > old["price"] else ChangeType.PRICE_DOWN
                        changes.append(_change(kind, book, old["price"], book.price))
                    self._update_book(book)
                self.conn.execute(
                    "INSERT INTO price_history (url, run_id, price, scraped_at) VALUES (?,?,?,?)",
                    (book.url, run_id, book.price, book.scraped_at.isoformat()),
                )

            for url, row in known.items():
                if (
                    row["active"]
                    and url not in seen
                    and row["category"] in result.complete_categories
                ):
                    changes.append(
                        Change(ChangeType.REMOVED, row["title"], row["category"], url,
                               old_price=row["price"])
                    )
                    self.conn.execute("UPDATE books SET active=0 WHERE url=?", (url,))

            self.conn.executemany(
                "INSERT INTO changes (run_id, url, change_type, old_price, new_price) VALUES (?,?,?,?,?)",
                [(run_id, c.url, c.change_type.value, c.old_price, c.new_price) for c in changes],
            )
        return changes

    def _insert_book(self, book: Book) -> None:
        stamp = book.scraped_at.isoformat()
        self.conn.execute(
            """INSERT INTO books (url, title, category, price, rating, in_stock,
               first_seen, last_seen, active) VALUES (?,?,?,?,?,?,?,?,1)""",
            (book.url, book.title, book.category, book.price, book.rating,
             int(book.in_stock), stamp, stamp),
        )

    def _update_book(self, book: Book) -> None:
        self.conn.execute(
            """UPDATE books SET title=?, category=?, price=?, rating=?, in_stock=?,
               last_seen=?, active=1 WHERE url=?""",
            (book.title, book.category, book.price, book.rating, int(book.in_stock),
             book.scraped_at.isoformat(), book.url),
        )

    def price_history(self, url: str) -> list[tuple[str, float]]:
        """Return ``(timestamp, price)`` pairs for one book, oldest first."""
        rows = self.conn.execute(
            "SELECT scraped_at, price FROM price_history WHERE url=? ORDER BY id", (url,)
        )
        return [(row["scraped_at"], row["price"]) for row in rows]


def _change(kind: ChangeType, book: Book, old_price: float | None = None,
            new_price: float | None = None) -> Change:
    return Change(kind, book.title, book.category, book.url, old_price, new_price)


def count_changes(changes: Iterable[Change]) -> dict[str, int]:
    """Count changes by headline bucket: new, removed and price."""
    counts = {"new": 0, "removed": 0, "price": 0}
    for change in changes:
        if change.change_type is ChangeType.NEW:
            counts["new"] += 1
        elif change.change_type is ChangeType.REMOVED:
            counts["removed"] += 1
        else:
            counts["price"] += 1
    return counts

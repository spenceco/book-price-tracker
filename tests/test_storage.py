"""Change-detection tests using an in-memory SQLite database."""

from __future__ import annotations

from price_tracker.models import ChangeType, ScrapeResult
from price_tracker.storage import PriceDatabase, count_changes
from tests.conftest import make_book


def run(db: PriceDatabase, books: list, complete: set[str] | None = None) -> list:
    """Record one scrape; by default every category in it counts as complete."""
    result = ScrapeResult(books=books, complete_categories=complete if complete is not None
                          else {b.category for b in books})
    run_id = db.start_run()
    changes = db.record_scrape(run_id, result)
    db.finish_run(run_id, len(books), changes, 0)
    return changes


def test_first_run_is_baseline_with_no_changes() -> None:
    with PriceDatabase(":memory:") as db:
        assert run(db, [make_book("A"), make_book("B")]) == []


def test_detects_price_increase_and_decrease() -> None:
    with PriceDatabase(":memory:") as db:
        run(db, [make_book("A", 10.0), make_book("B", 20.0), make_book("C", 30.0)])
        changes = run(db, [make_book("A", 12.5), make_book("B", 15.0), make_book("C", 30.0)])
    by_title = {c.title: c for c in changes}
    assert set(by_title) == {"A", "B"}
    assert by_title["A"].change_type is ChangeType.PRICE_UP
    assert by_title["A"].difference == 2.5
    assert by_title["A"].percent_change == 0.25
    assert by_title["B"].change_type is ChangeType.PRICE_DOWN
    assert by_title["B"].old_price == 20.0 and by_title["B"].new_price == 15.0


def test_detects_new_and_removed_books() -> None:
    with PriceDatabase(":memory:") as db:
        run(db, [make_book("A"), make_book("B")])
        changes = run(db, [make_book("A"), make_book("C")])
    kinds = {(c.change_type, c.title) for c in changes}
    assert kinds == {(ChangeType.NEW, "C"), (ChangeType.REMOVED, "B")}


def test_no_false_removals_for_partial_categories() -> None:
    """With --max-pages a category is incomplete, so missing books aren't 'removed'."""
    with PriceDatabase(":memory:") as db:
        run(db, [make_book("A"), make_book("B")])
        changes = run(db, [make_book("A")], complete=set())
    assert changes == []


def test_unscraped_categories_are_left_alone() -> None:
    with PriceDatabase(":memory:") as db:
        run(db, [make_book("A", category="Mystery"), make_book("P", category="Poetry")])
        changes = run(db, [make_book("A", category="Mystery")])  # Poetry not scraped
    assert changes == []


def test_first_scrape_of_a_new_category_is_baseline() -> None:
    with PriceDatabase(":memory:") as db:
        run(db, [make_book("A", category="Mystery")])
        changes = run(db, [make_book("A", category="Mystery"), make_book("P", category="Poetry")])
    assert changes == []


def test_returning_book_is_reported_as_new() -> None:
    with PriceDatabase(":memory:") as db:
        run(db, [make_book("A"), make_book("B")])
        run(db, [make_book("A")])
        changes = run(db, [make_book("A"), make_book("B")])
    assert [(c.change_type, c.title) for c in changes] == [(ChangeType.NEW, "B")]


def test_price_history_and_run_summary_are_stored() -> None:
    with PriceDatabase(":memory:") as db:
        run(db, [make_book("A", 10.0)])
        run(db, [make_book("A", 11.0)])
        history = db.price_history(make_book("A").url)
        last_run = db.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        logged = db.conn.execute("SELECT change_type FROM changes").fetchall()
    assert [price for _, price in history] == [10.0, 11.0]
    assert last_run["price_changes"] == 1 and last_run["books_scraped"] == 1
    assert [row[0] for row in logged] == [ChangeType.PRICE_UP.value]


def test_count_changes() -> None:
    with PriceDatabase(":memory:") as db:
        run(db, [make_book("A", 1.0), make_book("B")])
        changes = run(db, [make_book("A", 2.0), make_book("C")])
    assert count_changes(changes) == {"new": 1, "removed": 1, "price": 1}

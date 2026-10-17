"""Command-line entry point: parse options, run the scrape, save, export, summarise.

Example::

    python -m price_tracker --category Mystery --max-pages 1 --output-dir reports
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from price_tracker import __version__, config, exporter, scraper
from price_tracker.http_client import PoliteClient
from price_tracker.logging_setup import setup_logging
from price_tracker.models import Change, ChangeType
from price_tracker.storage import PriceDatabase, count_changes

log = logging.getLogger("price_tracker")


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line options."""
    parser = argparse.ArgumentParser(
        prog="price-tracker",
        description="Scrape books.toscrape.com, track price history and export Excel/CSV reports.",
    )
    parser.add_argument(
        "--category", action="append", metavar="NAME",
        help="Only scrape this category (case-insensitive). Repeat for several. Default: all.",
    )
    parser.add_argument(
        "--max-pages", type=_positive_int, metavar="N",
        help="Maximum listing pages per category (20 books each). Default: no limit.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=config.DEFAULT_OUTPUT_DIR,
        help=f"Where to write the Excel and CSV files. Default: {config.DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--db", type=Path, default=config.DEFAULT_DB_PATH,
        help=f"SQLite price-history database. Default: {config.DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--log-dir", type=Path, default=config.DEFAULT_LOG_DIR,
        help=f"Folder for the log file. Default: {config.DEFAULT_LOG_DIR}",
    )
    parser.add_argument(
        "--delay", type=float, default=config.REQUEST_DELAY,
        help=f"Seconds between requests. Default: {config.REQUEST_DELAY}",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Show debug messages.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def main(argv: list[str] | None = None) -> int:
    """Run the tracker. Returns a process exit code (0 = success)."""
    args = build_parser().parse_args(argv)
    log_file = setup_logging(args.log_dir, args.verbose)
    started = time.monotonic()
    log.info("price-tracker %s starting (log file: %s)", __version__, log_file)

    try:
        with PoliteClient(delay=args.delay) as client:
            result = scraper.scrape(client, args.category, args.max_pages)
    except scraper.UnknownCategoryError as exc:
        log.error("%s", exc)
        return 2
    except Exception:  # robots.txt or home page unreachable: nothing to do
        log.exception("Scrape failed before any books were collected")
        return 1

    if not result.books:
        log.error("No books were scraped; nothing saved (%d errors)", len(result.errors))
        return 1

    with PriceDatabase(args.db) as db:
        is_baseline = db.conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0
        run_id = db.start_run()
        changes = db.record_scrape(run_id, result)
        db.finish_run(run_id, len(result.books), changes, len(result.errors))

    stamp = datetime.now(UTC)
    xlsx_path, csv_path = exporter.output_paths(args.output_dir, stamp)
    exporter.write_excel(result.books, changes, xlsx_path, baseline=is_baseline)
    exporter.write_csv(result.books, csv_path)
    log.info("Excel report: %s", xlsx_path)
    log.info("CSV export:   %s", csv_path)

    if args.max_pages:
        log.info("--max-pages was set, so removed-book detection was skipped for partial categories")
    if is_baseline:
        log.info("First run: this scrape is the baseline that future runs compare against")
    print_summary(len(result.books), changes, result.errors, time.monotonic() - started)
    return 0 if not result.errors else 3


def print_summary(book_count: int, changes: list[Change], errors: list[str], seconds: float) -> None:
    """Log a short list of changes, then the one-line headline as the very last line."""
    if changes:
        order = list(ChangeType)
        shown = sorted(changes, key=lambda c: (order.index(c.change_type), c.title))
        limit = len(shown) if len(shown) <= 15 else 10
        log.info("Changes since the previous run:")
        for change in shown[:limit]:
            log.info("  %-15s %-42s %s", change.change_type.value, _shorten(change.title, 42),
                     _price_note(change))
        if len(shown) > limit:
            log.info("  ... and %d more (see the Changes sheet)", len(shown) - limit)
    for error in errors:
        log.warning("Error: %s", error)

    counts = count_changes(changes)
    log.info("-" * 72)
    log.info(
        "SUMMARY: %d books scraped, %d new, %d removed, %d price changes, %d errors (%.0fs)",
        book_count, counts["new"], counts["removed"], counts["price"], len(errors), seconds,
    )


def _shorten(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _price_note(change: Change) -> str:
    """'£9.27 -> £10.90 (+17.6%)' for price changes, a single price otherwise."""
    if change.difference is not None and change.percent_change is not None:
        return f"£{change.old_price:.2f} -> £{change.new_price:.2f} ({change.percent_change:+.1%})"
    if change.change_type is ChangeType.REMOVED:
        return f"(was £{change.old_price:.2f})"
    return f"£{change.new_price:.2f}"

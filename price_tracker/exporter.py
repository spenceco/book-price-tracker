"""Write a run's results to a formatted Excel workbook and a CSV file."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

from price_tracker.models import Book, Change, ChangeType

GBP_FORMAT = '"£"#,##0.00'
PERCENT_FORMAT = "+0.0%;-0.0%;0.0%"

BOOK_COLUMNS = ["Title", "Price", "Rating", "Stock", "Category", "Product URL", "Scraped At (UTC)"]
CHANGE_COLUMNS = ["Change", "Title", "Category", "Old Price", "New Price", "Difference", "% Change", "Product URL"]

HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")  # dark blue
#: Light background colours so each kind of change is easy to spot.
CHANGE_FILLS = {
    ChangeType.NEW: PatternFill("solid", fgColor="E2EFDA"),         # green
    ChangeType.REMOVED: PatternFill("solid", fgColor="EDEDED"),     # grey
    ChangeType.PRICE_UP: PatternFill("solid", fgColor="FCE4D6"),    # red-ish
    ChangeType.PRICE_DOWN: PatternFill("solid", fgColor="DDEBF7"),  # blue
}
MAX_COLUMN_WIDTH = 60


def output_paths(output_dir: Path, stamp: datetime) -> tuple[Path, Path]:
    """Build timestamped file names, e.g. ``books_2026-10-17_060000.xlsx``."""
    name = f"books_{stamp:%Y-%m-%d_%H%M%S}"
    return output_dir / f"{name}.xlsx", output_dir / f"{name}.csv"


def _style_header(sheet: Worksheet) -> None:
    """Bold, coloured header row that stays visible while scrolling."""
    for cell in sheet[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.freeze_panes = "A2"  # freeze the top row
    sheet.auto_filter.ref = sheet.dimensions  # filter dropdowns on every column


def _autofit_columns(sheet: Worksheet) -> None:
    """Size each column to its longest value (Excel has no auto-fit on save)."""
    for column_cells in sheet.columns:
        longest = max(len(_display_text(cell.value, cell.number_format)) for cell in column_cells)
        letter = get_column_letter(column_cells[0].column or 1)
        sheet.column_dimensions[letter].width = min(longest + 3, MAX_COLUMN_WIDTH)


def _display_text(value: object, number_format: str) -> str:
    """Approximate how a value will look in Excel, for width calculation."""
    if value is None:
        return ""
    if isinstance(value, float) and "£" in number_format:
        return f"£{value:,.2f}"
    if isinstance(value, float) and "%" in number_format:
        return f"{value:+.1%}"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _setup_printing(sheet: Worksheet) -> None:
    """Landscape, fit to page width, header repeated on every printed page."""
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    sheet.print_title_rows = "1:1"
    sheet.print_area = sheet.dimensions  # don't print long URLs spilling into empty columns


def write_excel(books: list[Book], changes: list[Change], path: Path, baseline: bool = False) -> Path:
    """Create the two-sheet workbook: "Books" and "Changes"."""
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()

    # --- Sheet 1: every book from this run ---
    books_sheet = workbook.create_sheet("Books")
    workbook.remove(workbook["Sheet"])  # drop the default empty sheet
    books_sheet.append(BOOK_COLUMNS)
    for book in books:
        books_sheet.append([
            book.title,
            book.price,
            book.rating,
            book.stock_status,
            book.category,
            book.url,
            # Excel can't store time zones; all timestamps are UTC (see header).
            book.scraped_at.replace(tzinfo=None),
        ])
    for row in books_sheet.iter_rows(min_row=2):
        row[1].number_format = GBP_FORMAT
        row[2].alignment = Alignment(horizontal="center")
        row[5].hyperlink = row[5].value
        row[5].style = "Hyperlink"
        row[6].number_format = "yyyy-mm-dd hh:mm:ss"
    _style_header(books_sheet)
    _autofit_columns(books_sheet)
    _setup_printing(books_sheet)

    # --- Sheet 2: what changed since the previous run ---
    changes_sheet = workbook.create_sheet("Changes")
    changes_sheet.append(CHANGE_COLUMNS)
    order = list(ChangeType)
    for change in sorted(changes, key=lambda c: (order.index(c.change_type), c.category, c.title)):
        changes_sheet.append([
            change.change_type.value,
            change.title,
            change.category,
            change.old_price,
            change.new_price,
            change.difference,
            change.percent_change,
            change.url,
        ])
        row = changes_sheet[changes_sheet.max_row]
        row[0].fill = CHANGE_FILLS[change.change_type]
        for cell in row[3:6]:
            cell.number_format = GBP_FORMAT
        row[6].number_format = PERCENT_FORMAT
        row[7].hyperlink = change.url
        row[7].style = "Hyperlink"
    if not changes:
        note = (
            "Baseline run: no previous data to compare against yet."
            if baseline else "No changes since the previous run."
        )
        changes_sheet.append([note])
        changes_sheet["A2"].font = Font(italic=True, color="595959")
    _style_header(changes_sheet)
    _autofit_columns(changes_sheet)
    if not changes:  # don't let the note stretch column A
        changes_sheet.column_dimensions["A"].width = 18
    _setup_printing(changes_sheet)

    workbook.save(path)
    return path


def write_csv(books: list[Book], path: Path) -> Path:
    """Write the books as plain CSV (UTF-8 with BOM so Excel shows '£' correctly)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["title", "price_gbp", "rating", "stock_status", "category",
                         "product_url", "scraped_at_utc"])
        for book in books:
            writer.writerow([book.title, f"{book.price:.2f}", book.rating, book.stock_status,
                             book.category, book.url, book.scraped_at.isoformat()])
    return path

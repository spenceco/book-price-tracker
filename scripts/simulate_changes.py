"""DEMO ONLY: edit the price-history database so the next run reports changes.

books.toscrape.com is a static sandbox, so its prices never really change.
To show change detection working, this script rewinds a few stored prices,
"forgets" a few books and invents a couple of books that no longer exist.
The next real scrape then reports price changes, new books and removals.

Usage:
    python scripts/simulate_changes.py [--db data/price_history.db]
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path("data/price_history.db"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    conn = sqlite3.connect(args.db)
    urls = [row[0] for row in conn.execute("SELECT url FROM books WHERE active=1 ORDER BY url")]
    if len(urls) < 20:
        raise SystemExit("Run the tracker once first so there is history to edit.")
    picked = rng.sample(urls, 9)

    with conn:
        # 1) Pretend 6 books used to cost a different price (+/- up to 25%).
        for url in picked[:6]:
            factor = rng.choice([0.8, 0.85, 0.9, 1.1, 1.15, 1.25])
            conn.execute("UPDATE books SET price=ROUND(price*?, 2) WHERE url=?", (factor, url))
        # 2) Forget 3 books, so they show up as "New book" next time.
        conn.executemany("DELETE FROM books WHERE url=?", [(u,) for u in picked[6:]])
        # 3) Add 2 books the site doesn't have, so they show up as "Removed".
        for title, category in [("The Vanishing Paperback", "Mystery"),
                                ("Out of Print: A Memoir", "Poetry")]:
            slug = title.lower().replace(" ", "-").replace(":", "")
            conn.execute(
                """INSERT OR REPLACE INTO books VALUES (?,?,?,?,?,?,?,?,1)""",
                (f"https://books.toscrape.com/catalogue/{slug}_9999/index.html", title, category,
                 19.99, 3, 1, "2026-10-16T06:00:00+00:00", "2026-10-16T06:00:00+00:00"),
            )
    print("Demo changes planted: 6 price changes, 3 new, 2 removed. Now run the tracker again.")


if __name__ == "__main__":
    main()

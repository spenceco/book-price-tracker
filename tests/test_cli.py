"""Run the whole command end-to-end with the network replaced by a stub."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Self

import pytest

from price_tracker import cli
from price_tracker.models import ScrapeResult
from tests.conftest import make_book


class DummyClient:
    def __init__(self, **kwargs: object) -> None: ...
    def __enter__(self) -> Self:
        return self
    def __exit__(self, *exc: object) -> None: ...


def test_full_run_writes_reports_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    prices = iter([10.0, 12.0])

    def fake_scrape(client, categories, max_pages):
        assert categories == ["Mystery"] and max_pages == 2
        return ScrapeResult(books=[make_book("A", next(prices))], complete_categories={"Mystery"})

    monkeypatch.setattr(cli, "PoliteClient", DummyClient)
    monkeypatch.setattr(cli.scraper, "scrape", fake_scrape)
    args = ["--category", "Mystery", "--max-pages", "2", "--output-dir", str(tmp_path / "out"),
            "--db", str(tmp_path / "h.db"), "--log-dir", str(tmp_path / "logs")]

    assert cli.main(args) == 0
    with caplog.at_level(logging.INFO):
        assert cli.main(args) == 0

    assert len(list((tmp_path / "out").glob("*.xlsx"))) >= 1
    assert len(list((tmp_path / "out").glob("*.csv"))) >= 1
    assert (tmp_path / "logs" / "price_tracker.log").exists()
    assert "SUMMARY: 1 books scraped, 0 new, 0 removed, 1 price changes, 0 errors" in caplog.text


def test_rejects_bad_max_pages() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--max-pages", "0"])

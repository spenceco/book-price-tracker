"""Send log messages to both the console (coloured) and a log file."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"

_COLOURS = {
    logging.DEBUG: "\033[2m",      # dim
    logging.INFO: "\033[36m",      # cyan
    logging.WARNING: "\033[33m",   # yellow
    logging.ERROR: "\033[31m",     # red
    logging.CRITICAL: "\033[1;31m",
}
_RESET = "\033[0m"


class ColourFormatter(logging.Formatter):
    """Colour the level name when writing to a terminal."""

    def format(self, record: logging.LogRecord) -> str:
        original = record.levelname
        record.levelname = f"{_COLOURS.get(record.levelno, '')}{original:<7}{_RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original


def use_colour(stream: object) -> bool:
    """Colour only real terminals (or when FORCE_COLOR is set); never under NO_COLOR."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def setup_logging(log_dir: Path, verbose: bool = False) -> Path:
    """Configure the root logger and return the log file path.

    The file keeps full detail and rotates at 5 MB (5 backups kept);
    the console shows INFO and above (DEBUG with ``--verbose``).
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "price_tracker.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # Remove handlers from an earlier call (e.g. in tests) but leave others alone.
    for handler in [h for h in root.handlers if getattr(h, "_price_tracker", False)]:
        root.removeHandler(handler)
        handler.close()

    file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
    file_handler._price_tracker = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter_cls = ColourFormatter if use_colour(sys.stdout) else logging.Formatter
    console.setFormatter(formatter_cls(CONSOLE_FORMAT, datefmt="%H:%M:%S"))
    console._price_tracker = True  # type: ignore[attr-defined]
    root.addHandler(console)

    # httpx logs every request at INFO; our own DEBUG "Fetched ..." line already covers it.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return log_file

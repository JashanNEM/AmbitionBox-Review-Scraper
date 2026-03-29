"""
utils.py — Shared utilities: logging, CSV writer, retry logic
"""

from __future__ import annotations
import csv
import logging
import os
import random
import time
import functools
from pathlib import Path
from typing import Any, Callable

from parser import CSV_COLUMNS


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Configure root logger with console + optional file handler."""
    fmt = "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format=fmt, datefmt=datefmt, handlers=handlers)


# ---------------------------------------------------------------------------
# CSV writer (incremental — safe against mid-run crashes)
# ---------------------------------------------------------------------------

class CSVWriter:
    """
    Opens a CSV file in append mode.
    Writes the header row only when the file is new / empty.
    Call .write_rows(list_of_dicts) after each page.
    """

    def __init__(self, filepath: str | Path) -> None:
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._write_header = not self.filepath.exists() or self.filepath.stat().st_size == 0
        self._fh = self.filepath.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._fh,
            fieldnames=CSV_COLUMNS,
            extrasaction="ignore",   # silently drop unexpected keys
            quoting=csv.QUOTE_ALL,
        )
        if self._write_header:
            self._writer.writeheader()
            self._fh.flush()

    def write_rows(self, rows: list[dict[str, Any]]) -> int:
        """Write rows and flush. Returns number of rows written."""
        if not rows:
            return 0
        self._writer.writerows(rows)
        self._fh.flush()
        return len(rows)

    def close(self) -> None:
        self._fh.close()

    # Context-manager support
    def __enter__(self):  return self
    def __exit__(self, *_): self.close()


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def retry(max_attempts: int = 3, backoff_base: float = 5.0,
          exceptions: tuple = (Exception,)):
    """
    Decorator — retries the wrapped coroutine/function on failure.
    Waits backoff_base * 2^attempt seconds between attempts.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    wait = backoff_base * (2 ** attempt) + random.uniform(0, 2)
                    logging.getLogger(__name__).warning(
                        "Attempt %d/%d failed (%s). Retrying in %.1fs…",
                        attempt + 1, max_attempts, exc, wait
                    )
                    time.sleep(wait)
            raise last_exc  # type: ignore[misc]

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    wait = backoff_base * (2 ** attempt) + random.uniform(0, 2)
                    logging.getLogger(__name__).warning(
                        "Attempt %d/%d failed (%s). Retrying in %.1fs…",
                        attempt + 1, max_attempts, exc, wait
                    )
                    time.sleep(wait)
            raise last_exc  # type: ignore[misc]

        import asyncio
        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper

    return decorator


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def random_delay(min_s: float, max_s: float) -> None:
    """Sleep for a random duration in [min_s, max_s]."""
    time.sleep(random.uniform(min_s, max_s))


def build_url(slug: str, page: int) -> str:
    """Construct the AmbitionBox reviews URL for a given page."""
    base = f"https://www.ambitionbox.com/reviews/{slug}-reviews"
    if page <= 1:
        return base
    return f"{base}?page={page}"


def total_pages_from_meta(total_reviews: str, per_page: int = 20) -> int:
    """Calculate total pages from total review count string (handles k and L)."""
    try:
        raw = total_reviews.replace(",", "").strip().lower()
        multiplier = 1
        
        if raw.endswith('k'):
            multiplier = 1000
            raw = raw.replace('k', '')
        elif raw.endswith('l'):
            multiplier = 100000
            raw = raw.replace('l', '')
            
        n = int(float(raw) * multiplier)
        return max(1, -(-n // per_page))   # ceiling division
    except (ValueError, AttributeError):
        return 1


def progress_bar(current: int, total: int, width: int = 40) -> str:
    """Simple ASCII progress bar string."""
    if total <= 0:
        return ""
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = 100 * current / total
    return f"[{bar}] {current}/{total}  ({pct:.1f}%)"

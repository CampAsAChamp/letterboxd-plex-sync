"""Pure helper functions for letterboxd-plex-sync (no external service dependencies)."""

from __future__ import annotations

import csv
import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import requests

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_REQUEST_DELAY_SECONDS = 0.26


def retry_with_backoff(
    func,
    *,
    attempts: int = 3,
    initial_delay_seconds: float = 5.0,
    backoff_factor: float = 4.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_retry=None,
):
    """
    Call `func()`, retrying on the given exceptions with exponential backoff.

    Re-raises the last exception if all attempts fail. `on_retry(attempt, exc, delay)`
    is called (if given) before each sleep, so callers can log a clear warning instead
    of letting a noisy traceback fly on transient failures (e.g. rate limiting).
    """
    delay = initial_delay_seconds
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except exceptions as exc:
            if attempt == attempts:
                raise
            if on_retry:
                on_retry(attempt, exc, delay)
            time.sleep(delay)
            delay *= backoff_factor


def letterboxd_rating_to_plex(lb_rating: float) -> float:
    """Convert Letterboxd's 0–5 scale to Plex's 0–10 scale."""
    return lb_rating * 2


def lookup_tmdb_id(
    api_key: str,
    title: str,
    year: str | None = None,
    session: requests.Session | None = None,
) -> str | None:
    """
    Resolve a movie title (and optional year) to a TMDB ID via the TMDB search API.

    Returns the first search result ID, or None if no match is found.
    """
    if not api_key:
        return None

    http = session or requests
    params: dict[str, str] = {"api_key": api_key, "query": title}
    if year:
        params["year"] = year

    response = http.get(
        f"{TMDB_API_BASE}/search/movie", params=params, timeout=30
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        return None
    return str(results[0]["id"])


def parse_radarr_error_response(response_content: bytes) -> list[dict[str, Any]]:
    """Parse a Radarr 400 error response body into a list of error objects."""
    try:
        parsed = json.loads(response_content.decode("utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return parsed
    return []


def classify_radarr_error(error: dict[str, Any]) -> str:
    """Classify a single Radarr validation error."""
    error_code = error.get("errorCode", "")
    error_message = error.get("errorMessage", "")

    if error_code == "MovieExistsValidator":
        return "already_exists"
    if "A movie with this ID was not found" in error_message:
        return "not_found"
    if error_code == "MoviePathValidator":
        return "path_conflict"
    return "unhandled"


def format_progress_bar(current: int, total: int, width: int = 20) -> str:
    """Return a text progress bar suitable for log files, e.g. [========------------]."""
    if total <= 0:
        return "[" + "-" * width + "]"
    filled = int(width * current / total)
    filled = min(max(filled, 0), width)
    return "[" + "=" * filled + "-" * (width - filled) + "]"


def count_csv_data_rows(csv_path: str, min_columns: int = 4) -> int:
    """Count data rows in a Letterboxd export CSV (excluding header)."""
    if not os.path.exists(csv_path):
        return 0

    count = 0
    with open(csv_path, encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        next(reader, None)
        for row in reader:
            if len(row) >= min_columns:
                count += 1
    return count


class WorkflowSteps:
    """Log numbered high-level sync steps, e.g. [Step 2/6] Index Plex libraries."""

    def __init__(self, step_names: list[str]) -> None:
        self._step_names = step_names
        self._total = len(step_names)
        self._current = 0

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        self._current += 1
        logging.info(
            "[Step %d/%d] %s — starting",
            self._current,
            self._total,
            name,
        )
        started = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - started
            logging.info(
                "[Step %d/%d] %s — complete (%.1fs)",
                self._current,
                self._total,
                name,
                elapsed,
            )


class StageProgress:
    """
    Log within-stage progress as current/total plus an ASCII bar.

    Logs at start, completion, and periodic milestones (every item when total <= 25,
    otherwise every 10%) to keep log volume reasonable in Docker/cron output.
    """

    def __init__(self, label: str, total: int, *, bar_width: int = 20) -> None:
        self.label = label
        self.total = max(total, 0)
        self.current = 0
        self.bar_width = bar_width
        self._last_logged_milestone = -1

    def start(self) -> None:
        if self.total == 0:
            logging.info("  %s: nothing to do", self.label)
            return
        self._log(force=True)

    def advance(self, count: int = 1) -> None:
        if self.total == 0:
            return
        self.current = min(self.current + count, self.total)
        self._log()

    def finish(self) -> None:
        if self.total == 0:
            return
        self.current = self.total
        self._log(force=True)

    def _milestone(self) -> int:
        if self.total <= 25:
            return self.current
        if self.current >= self.total:
            return 100
        return (int(100 * self.current / self.total) // 10) * 10

    def _log(self, force: bool = False) -> None:
        milestone = self._milestone()
        if not force and milestone <= self._last_logged_milestone:
            return
        self._last_logged_milestone = milestone
        pct = int(100 * self.current / self.total) if self.total else 100
        logging.info(
            "  %s: %d/%d %s %d%%",
            self.label,
            self.current,
            self.total,
            format_progress_bar(self.current, self.total, self.bar_width),
            pct,
        )

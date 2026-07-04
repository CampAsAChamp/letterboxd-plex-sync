"""Sync run counters, per-item outcomes, and end-of-run summary."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

FAILURE_STATUSES = frozenset(
    {"failed", "not_in_library", "error", "path_conflict", "not_found"}
)

SUCCESS_STATUSES = frozenset(
    {
        "added",
        "updated",
        "unchanged",
        "marked",
        "already_played",
        "already_listed",
        "already_present",
    }
)

CATEGORY_LABELS = {
    "mapping": "TMDB mappings",
    "rating": "Ratings",
    "watched": "Watched",
    "watchlist": "Watchlist",
    "radarr": "Radarr",
}

CATEGORY_ORDER = ("mapping", "rating", "watched", "watchlist", "radarr")


@dataclass
class SyncItemOutcome:
    """Per-item sync result for reporting."""

    category: str
    title: str
    status: str
    detail: str = ""


@dataclass
class SyncStats:
    """Counters and per-item outcomes for the end-of-run summary."""

    mappings_added: int = 0
    mappings_failed: int = 0
    rated: int = 0
    ratings_skipped: int = 0
    ratings_not_in_library: int = 0
    marked_watched: int = 0
    watched_skipped: int = 0
    watched_not_in_library: int = 0
    watchlist_added: int = 0
    watchlist_skipped: int = 0
    watchlist_not_in_library: int = 0
    radarr_added: int = 0
    radarr_already_exists: int = 0
    radarr_failed: int = 0
    dry_run: bool = False
    items: list[SyncItemOutcome] = field(default_factory=list)

    def record(
        self, category: str, title: str, status: str, detail: str = ""
    ) -> None:
        """Record a per-item outcome for the end-of-run report."""
        self.items.append(
            SyncItemOutcome(
                category=category, title=title, status=status, detail=detail
            )
        )

    def _inline_limit(self) -> int:
        raw = os.getenv("SYNC_REPORT_INLINE_LIMIT", "25")
        try:
            return max(int(raw), 0)
        except ValueError:
            return 25

    def _format_item_line(self, item: SyncItemOutcome) -> str:
        if item.detail:
            return f"    - {item.title} — {item.detail}"
        return f"    - {item.title}"

    def _items_by_category(self, category: str) -> list[SyncItemOutcome]:
        return [item for item in self.items if item.category == category]

    def write_report(self, path: str) -> str:
        """Write a human-readable succeeded/failed report and return the path."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        dry_run_note = " (DRY RUN)" if self.dry_run else ""
        lines = [
            f"Letterboxd-Plex Sync Report — {timestamp}{dry_run_note}",
            "=" * 64,
            "",
        ]

        for category in CATEGORY_ORDER:
            category_items = self._items_by_category(category)
            if not category_items:
                continue

            succeeded = [
                item for item in category_items if item.status in SUCCESS_STATUSES
            ]
            failed = [
                item for item in category_items if item.status in FAILURE_STATUSES
            ]

            lines.append(CATEGORY_LABELS[category])
            lines.append(f"  Succeeded ({len(succeeded)})")
            if succeeded:
                for item in succeeded:
                    lines.append(self._format_item_line(item).replace("    ", "  ", 1))
            else:
                lines.append("    (none)")
            lines.append(f"  Failed ({len(failed)})")
            if failed:
                for item in failed:
                    lines.append(self._format_item_line(item).replace("    ", "  ", 1))
            else:
                lines.append("    (none)")
            lines.append("")

        with open(path, "w", encoding="utf-8") as report_file:
            report_file.write("\n".join(lines).rstrip() + "\n")
        return path

    def log_summary(
        self,
        report_path: str | None = None,
        combined_log_path: str | None = None,
    ) -> None:
        """Log aggregate counters, inline failures, and paths to report/log files."""
        logging.info("========================================")
        if self.dry_run:
            logging.info("Sync summary (DRY RUN — no changes written):")
        else:
            logging.info("Sync summary:")
        logging.info(
            "  TMDB mappings: %d added, %d failed",
            self.mappings_added,
            self.mappings_failed,
        )
        logging.info(
            "  Ratings: %d updated, %d unchanged, %d not in library",
            self.rated,
            self.ratings_skipped,
            self.ratings_not_in_library,
        )
        logging.info(
            "  Watched: %d marked played, %d already played, %d not in library",
            self.marked_watched,
            self.watched_skipped,
            self.watched_not_in_library,
        )
        logging.info(
            "  Watchlist: %d added, %d already listed, %d not in library",
            self.watchlist_added,
            self.watchlist_skipped,
            self.watchlist_not_in_library,
        )
        logging.info(
            "  Radarr: %d added, %d already present, %d failed",
            self.radarr_added,
            self.radarr_already_exists,
            self.radarr_failed,
        )

        failures_by_category: list[tuple[str, list[SyncItemOutcome]]] = []
        for category in CATEGORY_ORDER:
            failed = [
                item
                for item in self._items_by_category(category)
                if item.status in FAILURE_STATUSES
            ]
            if failed:
                failures_by_category.append((category, failed))

        if failures_by_category:
            logging.info("  Failures:")
            inline_limit = self._inline_limit()
            for category, failed in failures_by_category:
                logging.info("    %s:", CATEGORY_LABELS[category])
                shown = failed[:inline_limit] if inline_limit else failed
                for item in shown:
                    if item.detail:
                        logging.info("      - %s — %s", item.title, item.detail)
                    else:
                        logging.info("      - %s", item.title)
                remaining = len(failed) - len(shown)
                if remaining > 0:
                    logging.info(
                        "      ... and %d more in report",
                        remaining,
                    )
        else:
            logging.info("  Failures: none")

        if report_path:
            logging.info("  Detailed report: %s", report_path)
        if combined_log_path:
            logging.info("  Full run log: %s", combined_log_path)
        logging.info("========================================")

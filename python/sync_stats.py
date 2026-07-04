"""Sync run counters and end-of-run summary."""

from __future__ import annotations

import logging
from dataclasses import dataclass


@dataclass
class SyncStats:
    """Counters for the end-of-run summary."""

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

    def log_summary(self) -> None:
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
        logging.info("========================================")

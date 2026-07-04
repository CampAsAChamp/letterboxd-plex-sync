"""Logging setup and environment/workflow configuration helpers."""

from __future__ import annotations

import logging
import os
import sys


def configure_logging() -> None:
    """Configure root logging from the DEBUG environment variable."""
    debug = os.getenv("DEBUG", "false") != "false"
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s.%(msecs)03d %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def is_dry_run() -> bool:
    """Return True when DRY_RUN=true (preview mode; no Plex/Radarr writes)."""
    return os.getenv("DRY_RUN", "false").lower() == "true"


def require_env(*names: str) -> dict[str, str]:
    """Return env values for the given names, exiting if any are missing."""
    values: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        value = os.getenv(name, "").strip()
        if not value:
            missing.append(name)
        else:
            values[name] = value
    if missing:
        logging.error(
            "Missing required environment variables: %s", ", ".join(missing)
        )
        sys.exit(1)
    return values


def build_workflow_steps(
    *,
    map_letterboxd_to_tmdb: bool,
    sync_watched: bool,
    sync_ratings: bool,
    sync_watchlist: bool,
    sync_radarr: bool,
) -> list[str]:
    """Build the ordered list of high-level steps for this run."""
    steps = [
        "Download Letterboxd user data",
        "Index Plex movie libraries",
    ]
    if map_letterboxd_to_tmdb:
        steps.append("Map Letterboxd URLs to TMDB IDs")
    if sync_watched:
        steps.append("Sync watched status to Plex")
    if sync_ratings:
        steps.append("Sync ratings to Plex")
    if sync_watchlist:
        steps.append("Sync watchlist to Plex")
    if sync_radarr:
        steps.append("Sync watchlist to Radarr")
    return steps

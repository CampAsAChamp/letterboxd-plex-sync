#!/usr/bin/env python3
"""
Sync Letterboxd ratings, watch history, and watchlist to Plex (and optionally Radarr).

High-level steps:
1. Download Letterboxd CSV exports via letterboxd_stats
2. Build a Letterboxd URL → TMDB ID mapping (cached on disk)
3. Index Plex movie libraries by TMDB GUID
4. Apply one-way sync: ratings, watched (played only), watchlist additions, Radarr additions
"""

from __future__ import annotations

import logging
import os
import sys

from letterboxd_stats import web_scraper as ws
from plexapi.exceptions import NotFound
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer

from plex_sync import (
    build_plex_guid_lookup,
    sync_plex_ratings_from_letterboxd,
    sync_plex_watched_status_from_letterboxd,
    sync_plex_watchlist_from_letterboxd,
)
from radarr_sync import sync_watchlist_to_radarr
from sync_config import build_workflow_steps, configure_logging, is_dry_run, require_env
from sync_helpers import StageProgress, WorkflowSteps, retry_with_backoff
from sync_state import letterboxd_to_tmdb_map
from sync_stats import SyncStats
from tmdb_mapping import (
    count_uncached_letterboxd_urls,
    load_existing_mapping,
    populate_letterboxd_tmdb_mapping_file,
)

# Change the current working directory to the location of this script
current_script_path = os.path.abspath(__file__)
current_script_dir = os.path.dirname(current_script_path)
os.chdir(current_script_dir)

configure_logging()

LETTERBOXD_LOGIN_ATTEMPTS = 3
LETTERBOXD_LOGIN_INITIAL_DELAY_SECONDS = 30.0


def main() -> None:
    """Main function to sync Letterboxd data with Plex."""
    stats = SyncStats(dry_run=is_dry_run())

    logging.info("Starting sync job")

    if stats.dry_run:
        logging.warning(
            "DRY_RUN is enabled — previewing changes only; "
            "nothing will be written to Plex or Radarr."
        )

    logging.warning(
        "\n****************************************************\n"
        "WARNING: This program comes with NO WARRANTY.\n"
        "Use it at your own risk. The authors are not responsible\n"
        "for any damage or data loss that may occur as a result\n"
        "of using this software.\n"
        "****************************************************\n"
    )

    logging.info("========================================")
    logging.info("Starting Letterboxd-Plex Sync Program")
    logging.info("========================================")

    letterboxd_to_tmdb_csv = os.getenv(
        "LB_TMDB_MAP_CSV_PATH_OVERRIDE", "/app/data/lb_URL_to_tmdb_id.csv"
    )
    map_letterboxd_to_tmdb = os.getenv("MAP_LETTERBOXD_TO_TMDB", "true") == "true"
    sync_watchlist_to_plex_enabled = os.getenv("SYNC_WATCHLIST", "true") == "true"
    sync_watched_enabled = os.getenv("SYNC_WATCHED", "true") == "true"
    sync_ratings_enabled = os.getenv("SYNC_RATINGS", "true") == "true"
    sync_watchlist_to_radarr_enabled = (
        os.getenv("SYNC_WATCHLIST_TO_RADARR", "false") == "true"
    )
    plex_library_name = os.getenv("PLEX_LIBRARY_NAME")

    os.makedirs(os.path.dirname(letterboxd_to_tmdb_csv) or ".", exist_ok=True)
    open(letterboxd_to_tmdb_csv, "a", encoding="utf-8").close()

    ratings_csv = os.getenv("LETTERBOXD_RATINGS_CSV", "/tmp/static/ratings.csv")
    watchlist_csv = os.getenv("LETTERBOXD_WATCHLIST_CSV", "/tmp/static/watchlist.csv")
    watched_csv = os.getenv("LETTERBOXD_WATCHED_CSV", "/tmp/static/watched.csv")

    step_names = build_workflow_steps(
        map_letterboxd_to_tmdb=map_letterboxd_to_tmdb,
        sync_watched=sync_watched_enabled,
        sync_ratings=sync_ratings_enabled,
        sync_watchlist=sync_watchlist_to_plex_enabled,
        sync_radarr=sync_watchlist_to_radarr_enabled,
    )
    logging.info(
        "Planned workflow (%d steps): %s",
        len(step_names),
        " → ".join(step_names),
    )
    workflow = WorkflowSteps(step_names)

    env = require_env("PLEX_BASEURL", "PLEX_TOKEN", "TMDB_API_KEY")
    plex_base_url = env["PLEX_BASEURL"]
    plex_token = env["PLEX_TOKEN"]
    tmdb_api_key = env["TMDB_API_KEY"]

    logging.info("Connecting to Plex at %s ...", plex_base_url)
    plex = PlexServer(plex_base_url, plex_token)
    logging.info("Connected to Plex server %r", plex.friendlyName)

    logging.info("Authenticating with MyPlex ...")
    account = MyPlexAccount(token=plex_token)

    plex_user_name = os.getenv("PLEX_USER")
    if plex_user_name:
        logging.info('Switching to Plex home user "%s" ...', plex_user_name)
        plex_user_pin = os.getenv("PLEX_PIN")
        user = account.switchHomeUser(user=plex_user_name, pin=plex_user_pin)
        plex = plex.switchUser(plex_user_name)
        logging.info('Using Plex home user "%s"', user.title)
    else:
        user = account
        logging.info('Using Plex account "%s"', user.title)

    with workflow.step("Download Letterboxd user data"):
        logging.info("Logging into Letterboxd (this may take a minute) ...")

        def _login_and_download() -> None:
            downloader = ws.Connector()
            downloader.login()
            logging.info("Letterboxd login successful; downloading export CSVs ...")
            downloader.download_stats()

        def _log_retry(attempt: int, exc: Exception, delay: float) -> None:
            logging.warning(
                "Letterboxd login/download failed (attempt %d/%d): %s. "
                "This is often a transient rate limit or anti-bot challenge; "
                "retrying in %.0fs ...",
                attempt,
                LETTERBOXD_LOGIN_ATTEMPTS,
                exc,
                delay,
            )

        try:
            retry_with_backoff(
                _login_and_download,
                attempts=LETTERBOXD_LOGIN_ATTEMPTS,
                initial_delay_seconds=LETTERBOXD_LOGIN_INITIAL_DELAY_SECONDS,
                exceptions=(ConnectionError, ValueError, OSError),
                on_retry=_log_retry,
            )
        except (ConnectionError, ValueError, OSError) as exc:
            logging.error(
                "Failed to log in to Letterboxd after %d attempts: %s. "
                "Skipping this run; it will retry on the next scheduled sync.",
                LETTERBOXD_LOGIN_ATTEMPTS,
                exc,
            )
            sys.exit(1)

        logging.info("Letterboxd export download complete")

    if plex_library_name:
        try:
            movie_libraries = [plex.library.section(plex_library_name)]
        except NotFound:
            logging.error(
                'No Movie library named "%s" found on the Plex server!',
                plex_library_name,
            )
            sys.exit(1)
    else:
        movie_libraries = [
            lib for lib in plex.library.sections() if lib.type == "movie"
        ]
        if not movie_libraries:
            logging.error("No Movie libraries found on the Plex server!")
            sys.exit(1)

    with workflow.step("Index Plex movie libraries"):
        build_plex_guid_lookup(movie_libraries)

    if map_letterboxd_to_tmdb:
        with workflow.step("Map Letterboxd URLs to TMDB IDs"):
            csv_paths = [ratings_csv, watchlist_csv, watched_csv]
            uncached_total = count_uncached_letterboxd_urls(
                csv_paths, letterboxd_to_tmdb_csv
            )
            if uncached_total == 0:
                logging.info(
                    "TMDB mapping cache is warm (%d URLs cached); skipping API lookups",
                    len(letterboxd_to_tmdb_map),
                )
            else:
                overall = StageProgress("TMDB mapping (all sources)", uncached_total)
                overall.start()
                for path in csv_paths:
                    populate_letterboxd_tmdb_mapping_file(
                        path,
                        letterboxd_to_tmdb_csv,
                        tmdb_api_key,
                        stats,
                        progress=overall,
                    )
                overall.finish()
    else:
        logging.info("Skipping TMDB mapping (MAP_LETTERBOXD_TO_TMDB=false)")

    load_existing_mapping(letterboxd_to_tmdb_csv)

    if sync_watched_enabled:
        with workflow.step("Sync watched status to Plex"):
            sync_plex_watched_status_from_letterboxd(user, watched_csv, stats)

    if sync_ratings_enabled:
        with workflow.step("Sync ratings to Plex"):
            sync_plex_ratings_from_letterboxd(ratings_csv, stats)

    if sync_watchlist_to_plex_enabled:
        with workflow.step("Sync watchlist to Plex"):
            sync_plex_watchlist_from_letterboxd(user, watchlist_csv, stats)

    if sync_watchlist_to_radarr_enabled:
        radarr_env = require_env("RADARR_URL", "RADARR_TOKEN")
        with workflow.step("Sync watchlist to Radarr"):
            sync_watchlist_to_radarr(
                watchlist_csv,
                radarr_env["RADARR_URL"],
                radarr_env["RADARR_TOKEN"],
                stats,
            )

    report_path = os.getenv(
        "SYNC_REPORT_PATH", "/app/data/latest_sync_report.txt"
    )
    combined_log_path = os.getenv(
        "COMBINED_LOG_PATH", "/app/data/combined_log.txt"
    )
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    stats.write_report(report_path)
    stats.log_summary(
        report_path=report_path, combined_log_path=combined_log_path
    )
    logging.info("Sync process complete.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.error("Process interrupted.")
        sys.exit(130)
    except Exception:
        logging.exception("Sync failed with an unexpected error.")
        sys.exit(1)

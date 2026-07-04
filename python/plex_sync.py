"""Plex library indexing and Letterboxd-to-Plex sync operations."""

from __future__ import annotations

import csv
import logging

from plexapi.exceptions import BadRequest, NotFound
from plexapi.utils import searchType

from sync_config import is_dry_run
from sync_helpers import StageProgress, letterboxd_rating_to_plex
from sync_state import (
    letterboxd_to_tmdb_map,
    plex_guid_lookup_table,
    plex_metadata_server,
)
from sync_stats import SyncStats


def get_plex_video_by_letterboxd_url(lb_url: str):
    """Fetch the Plex video object corresponding to a Letterboxd URL."""
    try:
        tmdb_id = letterboxd_to_tmdb_map[lb_url]
        return plex_guid_lookup_table[f"tmdb://{tmdb_id}"]
    except KeyError as exc:
        logging.debug(
            "Failed to find video in Plex Library for %s. Reason: %s", lb_url, exc
        )
        return None


def get_plex_video_by_tmdb_id(tmdb_id: str, libtype: str = "movie"):
    guid = "tmdb://" + tmdb_id
    logging.debug("Querying Plex for GUID %s", guid)

    try:
        video = plex_metadata_server.fetchItem(
            f"/library/metadata/matches?type={searchType(libtype)}&guid={guid}"
        )
    except NotFound as exc:
        logging.warning("Plex could not find a match for TMDb GUID %s: %s", guid, exc)
        video = None
    except Exception as exc:
        logging.error(
            "Unexpected error during Plex fetchItem for GUID %s: %s",
            guid,
            exc,
            exc_info=True,
        )
        video = None
    return video


def build_plex_guid_lookup(movie_libraries) -> None:
    """Index all movies from the given Plex libraries by TMDB GUID."""
    for movies_library in movie_libraries:
        items = movies_library.all()
        progress = StageProgress(f'Indexing "{movies_library.title}"', len(items))
        progress.start()
        for item in items:
            plex_guid_lookup_table[item.guid] = item
            plex_guid_lookup_table.update({guid.id: item for guid in item.guids})
            progress.advance()
        progress.finish()


def sync_plex_ratings_from_letterboxd(ratings_csv: str, stats: SyncStats) -> None:
    """Sync user ratings from Letterboxd to Plex."""
    rows: list[list[str]] = []
    with open(ratings_csv, encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile, delimiter=",")
        next(reader, None)
        for row in reader:
            if len(row) >= 5:
                rows.append(row)

    progress = StageProgress("Syncing ratings", len(rows))
    progress.start()

    for row in rows:
        lb_title = row[1]
        lb_url = row[3]

        video = get_plex_video_by_letterboxd_url(lb_url)
        if not video:
            stats.ratings_not_in_library += 1
            logging.debug("Rating: Failed to find: %s", lb_title)
            progress.advance()
            continue

        lb_rating = letterboxd_rating_to_plex(float(row[4]))

        if video.userRating != lb_rating:
            if is_dry_run():
                logging.info(
                    "[DRY RUN] Would rate %s at %s/10", video.title, lb_rating
                )
                stats.rated += 1
            else:
                video.rate(lb_rating)
                stats.rated += 1
                logging.debug("Rated %s at %s/10", video.title, lb_rating)
        else:
            stats.ratings_skipped += 1
            logging.debug(
                "Skipped rating %s. Already rated at %s/10",
                video.title,
                video.userRating,
            )
        progress.advance()

    progress.finish()


def sync_plex_watchlist_from_letterboxd(
    user, watchlist_csv: str, stats: SyncStats
) -> None:
    """Sync user watchlist from Letterboxd to Plex (add-only)."""
    current_watchlist = user.watchlist()

    rows: list[list[str]] = []
    with open(watchlist_csv, encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile, delimiter=",")
        next(reader, None)
        for row in reader:
            if len(row) >= 4:
                rows.append(row)

    progress = StageProgress("Syncing watchlist to Plex", len(rows))
    progress.start()

    for row in rows:
        lb_title = row[1]
        lb_url = row[3]

        video = get_plex_video_by_letterboxd_url(lb_url)
        if not video:
            tmdb_id = letterboxd_to_tmdb_map.get(lb_url)
            if not tmdb_id:
                stats.watchlist_not_in_library += 1
                logging.warning("Skipping: No TMDB ID found for %s", lb_url)
                progress.advance()
                continue
            video = get_plex_video_by_tmdb_id(tmdb_id)

        if not video:
            stats.watchlist_not_in_library += 1
            logging.debug("Watchlist: Failed to find in Plex: %s", lb_title)
            progress.advance()
            continue

        if not any(v.guid == video.guid for v in current_watchlist):
            if is_dry_run():
                logging.info("[DRY RUN] Would add to watchlist: %s", video.title)
                stats.watchlist_added += 1
            else:
                try:
                    video.addToWatchlist(user)
                    stats.watchlist_added += 1
                    logging.info("Added to watchlist: %s", video.title)
                except BadRequest:
                    logging.error(
                        'An error occurred when adding "%s" to watchlist.', video.title
                    )
        else:
            stats.watchlist_skipped += 1
            logging.debug("Already on watchlist: %s", video.title)
        progress.advance()

    progress.finish()


def sync_plex_watched_status_from_letterboxd(watched_csv: str, stats: SyncStats) -> None:
    """Sync user watched status from Letterboxd to Plex (marks played only)."""
    rows: list[list[str]] = []
    with open(watched_csv, encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile, delimiter=",")
        next(reader, None)
        for row in reader:
            if len(row) >= 4:
                rows.append(row)

    progress = StageProgress("Syncing watched status", len(rows))
    progress.start()

    for row in rows:
        lb_title = row[1]
        lb_url = row[3]

        video = get_plex_video_by_letterboxd_url(lb_url)
        if not video:
            stats.watched_not_in_library += 1
            logging.debug("Watched: Failed to find: %s", lb_title)
            progress.advance()
            continue

        if not video.isPlayed:
            if is_dry_run():
                logging.info("[DRY RUN] Would mark %s as played.", video.title)
                stats.marked_watched += 1
            else:
                video.markPlayed()
                stats.marked_watched += 1
                logging.info("Marked %s as played.", video.title)
        else:
            stats.watched_skipped += 1
            logging.debug("Skipped marking %s as played. Already marked.", video.title)
        progress.advance()

    progress.finish()

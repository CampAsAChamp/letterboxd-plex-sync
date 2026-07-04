"""Plex library indexing and Letterboxd-to-Plex sync operations."""

from __future__ import annotations

import csv
import logging

from plexapi.exceptions import NotFound, PlexApiException
from plexapi.utils import searchType

from sync_config import is_dry_run
from sync_helpers import StageProgress, letterboxd_rating_to_plex
from sync_state import (
    letterboxd_to_tmdb_map,
    plex_guid_lookup_table,
    plex_metadata_server,
)
from sync_stats import SyncStats


def get_plex_video_from_local_library(lb_url: str):
    """Look up a Plex video in the indexed local library by Letterboxd URL."""
    try:
        tmdb_id = letterboxd_to_tmdb_map[lb_url]
        return plex_guid_lookup_table[f"tmdb://{tmdb_id}"]
    except KeyError as exc:
        logging.debug(
            "Failed to find video in Plex Library for %s. Reason: %s", lb_url, exc
        )
        return None


def resolve_plex_video_by_letterboxd_url(lb_url: str):
    """Resolve a Plex video by Letterboxd URL (local library, then metadata API)."""
    video = get_plex_video_from_local_library(lb_url)
    if video:
        return video

    tmdb_id = letterboxd_to_tmdb_map.get(lb_url)
    if not tmdb_id:
        return None

    return get_plex_video_by_tmdb_id(tmdb_id)


def is_local_plex_video(video) -> bool:
    """
    Return True if `video` is a real local library item rather than a remote
    Plex Discover/metadata match.

    Discover matches (from get_plex_video_by_tmdb_id) have no valid ratingKey
    (it's NaN), so rate()/markPlayed() always 404 against them — those calls
    are local Plex Media Server operations, unlike addToWatchlist() which is
    a MyPlex account-level action and works fine on Discover matches.
    """
    return video._server is not plex_metadata_server


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

        video = resolve_plex_video_by_letterboxd_url(lb_url)
        if not video or not is_local_plex_video(video):
            tmdb_id = letterboxd_to_tmdb_map.get(lb_url)
            detail = "no TMDB ID" if not tmdb_id else ""
            stats.ratings_not_in_library += 1
            stats.record("rating", lb_title, "not_in_library", detail)
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
                stats.record("rating", lb_title, "updated", f"{lb_rating}/10")
            else:
                try:
                    video.rate(lb_rating)
                    stats.rated += 1
                    stats.record("rating", lb_title, "updated", f"{lb_rating}/10")
                    logging.debug("Rated %s at %s/10", video.title, lb_rating)
                except PlexApiException as exc:
                    stats.record("rating", lb_title, "error", f"Plex error: {exc}")
                    logging.error(
                        'An error occurred when rating "%s": %s', video.title, exc
                    )
        else:
            stats.ratings_skipped += 1
            stats.record("rating", lb_title, "unchanged", f"{video.userRating}/10")
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

        video = resolve_plex_video_by_letterboxd_url(lb_url)
        if not video:
            if not letterboxd_to_tmdb_map.get(lb_url):
                stats.watchlist_not_in_library += 1
                stats.record("watchlist", lb_title, "not_in_library", "no TMDB ID")
                logging.warning("Skipping: No TMDB ID found for %s", lb_url)
                progress.advance()
                continue

        if not video:
            stats.watchlist_not_in_library += 1
            stats.record("watchlist", lb_title, "not_in_library")
            logging.debug("Watchlist: Failed to find in Plex: %s", lb_title)
            progress.advance()
            continue

        if not any(v.guid == video.guid for v in current_watchlist):
            if is_dry_run():
                logging.info("[DRY RUN] Would add to watchlist: %s", video.title)
                stats.watchlist_added += 1
                stats.record("watchlist", lb_title, "added")
            else:
                try:
                    video.addToWatchlist(user)
                    stats.watchlist_added += 1
                    stats.record("watchlist", lb_title, "added")
                    logging.info("Added to watchlist: %s", video.title)
                except PlexApiException as exc:
                    stats.record("watchlist", lb_title, "error", f"Plex error: {exc}")
                    logging.error(
                        'An error occurred when adding "%s" to watchlist: %s',
                        video.title,
                        exc,
                    )
        else:
            stats.watchlist_skipped += 1
            stats.record("watchlist", lb_title, "already_listed")
        progress.advance()

    progress.finish()


def sync_plex_watched_status_from_letterboxd(
    user, watched_csv: str, stats: SyncStats
) -> None:
    """
    Sync user watched status from Letterboxd to Plex (marks played only).

    Movies in the local library are marked played on the Plex Media Server.
    Movies resolved only via Plex's remote Discover metadata (not owned
    locally) are marked played on the account instead — account.markPlayed()
    posts to Plex's Discover activity endpoint, which (unlike rate()) is
    supported for items you don't own.
    """
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

        video = resolve_plex_video_by_letterboxd_url(lb_url)
        if not video:
            tmdb_id = letterboxd_to_tmdb_map.get(lb_url)
            detail = "no TMDB ID" if not tmdb_id else ""
            stats.watched_not_in_library += 1
            stats.record("watched", lb_title, "not_in_library", detail)
            logging.debug("Watched: Failed to find: %s", lb_title)
            progress.advance()
            continue

        local = is_local_plex_video(video)
        is_played = video.isPlayed if local else user.isPlayed(video)

        if not is_played:
            if is_dry_run():
                logging.info("[DRY RUN] Would mark %s as played.", video.title)
                stats.marked_watched += 1
                stats.record("watched", lb_title, "marked")
            else:
                try:
                    if local:
                        video.markPlayed()
                    else:
                        user.markPlayed(video)
                    stats.marked_watched += 1
                    stats.record("watched", lb_title, "marked")
                    logging.info("Marked %s as played.", video.title)
                except PlexApiException as exc:
                    stats.record("watched", lb_title, "error", f"Plex error: {exc}")
                    logging.error(
                        'An error occurred when marking "%s" as played: %s',
                        video.title,
                        exc,
                    )
        else:
            stats.watched_skipped += 1
            stats.record("watched", lb_title, "already_played")
        progress.advance()

    progress.finish()

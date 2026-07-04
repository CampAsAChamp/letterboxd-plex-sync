"""Radarr API operations and Letterboxd watchlist sync."""

from __future__ import annotations

import csv
import logging
import os

import requests

from sync_config import is_dry_run
from sync_helpers import StageProgress, classify_radarr_error, parse_radarr_error_response
from sync_state import letterboxd_to_tmdb_map
from sync_stats import SyncStats


def get_or_create_tag(radarr_url: str, radarr_token: str, tag_name: str) -> int:
    """Fetch the ID of an existing tag or create a new one."""
    headers = {"X-Api-Key": radarr_token, "Content-Type": "application/json"}
    tags_endpoint = f"{radarr_url.rstrip('/')}/api/v3/tag"

    response = requests.get(tags_endpoint, headers=headers, timeout=30)
    response.raise_for_status()
    existing_tags = response.json()

    for tag in existing_tags:
        if tag["label"].lower() == tag_name.lower():
            return tag["id"]

    create_response = requests.post(
        tags_endpoint, json={"label": tag_name}, headers=headers, timeout=30
    )
    create_response.raise_for_status()
    return create_response.json()["id"]


def get_quality_profile_id(
    radarr_url: str, radarr_token: str, profile_name: str
) -> int | None:
    """Retrieve the ID of a quality profile in Radarr by its name."""
    headers = {"X-Api-Key": radarr_token}
    endpoint = f"{radarr_url.rstrip('/')}/api/v3/qualityprofile"

    try:
        response = requests.get(endpoint, headers=headers, timeout=30)
        response.raise_for_status()
        for profile in response.json():
            if profile["name"].lower() == profile_name.lower():
                return profile["id"]
        return None
    except requests.exceptions.RequestException as exc:
        logging.error("Failed to fetch quality profiles from Radarr: %s", exc)
        return None


def get_radarr_movies(radarr_url: str, radarr_token: str) -> set[int]:
    """Fetch the list of movies currently in Radarr."""
    headers = {"X-Api-Key": radarr_token}
    endpoint = f"{radarr_url.rstrip('/')}/api/v3/movie"

    try:
        response = requests.get(endpoint, headers=headers, timeout=30)
        response.raise_for_status()
        return {movie["tmdbId"] for movie in response.json()}
    except requests.exceptions.RequestException as exc:
        logging.error("Failed to fetch movies from Radarr: %s", exc)
        return set()


def add_to_radarr(
    tmdb_id: str | int,
    radarr_url: str,
    radarr_token: str,
    tag_names: list[str] | None = None,
) -> str:
    """
    Add a movie to Radarr using its TMDB ID.

    Returns one of: 'added', 'already_exists', 'not_found', 'path_conflict', 'failed'.
    """
    headers = {"X-Api-Key": radarr_token, "Content-Type": "application/json"}

    quality_profile_name = os.getenv("RADARR_QUALITY_PROFILE")
    quality_profile = (
        get_quality_profile_id(radarr_url, radarr_token, quality_profile_name)
        if quality_profile_name
        else None
    )
    quality_profile = quality_profile or 1
    root_folder_path = os.getenv("RADARR_ROOT_FOLDER", "/movies")
    radarr_monitored = os.getenv("RADARR_MONITORED", "true") == "true"
    radarr_search = os.getenv("RADARR_SEARCH", "true") == "true"

    endpoint = f"{radarr_url.rstrip('/')}/api/v3/movie"
    payload = {
        "tmdbId": int(tmdb_id),
        "qualityProfileId": int(quality_profile),
        "rootFolderPath": root_folder_path,
        "monitored": radarr_monitored,
        "addOptions": {"searchForMovie": radarr_search},
    }

    if is_dry_run():
        if tag_names:
            payload["tags"] = tag_names
        logging.info(
            "[DRY RUN] Would add movie with TMDB ID %s to Radarr (payload: %s).",
            tmdb_id,
            payload,
        )
        return "added"

    if tag_names:
        payload["tags"] = [
            get_or_create_tag(radarr_url, radarr_token, tag_name)
            for tag_name in tag_names
        ]

    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        logging.info("Successfully added movie with TMDB ID %s to Radarr.", tmdb_id)
        return "added"
    except requests.exceptions.HTTPError:
        if response.status_code == 400:
            for error in parse_radarr_error_response(response.content):
                result = classify_radarr_error(error)
                error_message = error.get("errorMessage", "")
                if result == "already_exists":
                    logging.warning(
                        "Movie with TMDB ID %s is already in Radarr.", tmdb_id
                    )
                    return "already_exists"
                if result == "not_found":
                    logging.warning(
                        "A movie with TMDB ID %s was not found in Radarr search.",
                        tmdb_id,
                    )
                    return "not_found"
                if result == "path_conflict":
                    logging.warning(
                        "Path conflict for TMDB ID %s: %s", tmdb_id, error_message
                    )
                    return "path_conflict"
                logging.error(
                    "Unhandled Radarr error for TMDB ID %s: %s", tmdb_id, error_message
                )
            return "failed"
        logging.warning(
            "Failed to add movie with TMDB ID %s to Radarr: HTTP %s",
            tmdb_id,
            response.status_code,
        )
        logging.warning("Response content: %s", response.content)
        logging.warning("Payload: %s", payload)
        return "failed"


def sync_watchlist_to_radarr(
    watchlist_csv: str, radarr_url: str, radarr_token: str, stats: SyncStats
) -> None:
    """Sync the Letterboxd watchlist to Radarr (add-only)."""
    radarr_tags_env = os.getenv("RADARR_TAGS", "")
    radarr_tags = (
        [tag.strip() for tag in radarr_tags_env.split(",") if tag.strip()]
        if radarr_tags_env
        else []
    )

    logging.info("Radarr tags: %s", radarr_tags)
    existing_tmdb_ids = get_radarr_movies(radarr_url, radarr_token)

    rows: list[list[str]] = []
    with open(watchlist_csv, encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile, delimiter=",")
        next(reader, None)
        for row in reader:
            if len(row) >= 4:
                rows.append(row)

    progress = StageProgress("Syncing watchlist to Radarr", len(rows))
    progress.start()

    for row in rows:
        lb_title = row[1]
        lb_url = row[3]
        tmdb_id = letterboxd_to_tmdb_map.get(lb_url)
        if tmdb_id is None:
            logging.debug("Radarr Sync: Failed to find TMDB ID for %s", lb_title)
            progress.advance()
            continue

        if int(tmdb_id) in existing_tmdb_ids:
            stats.radarr_already_exists += 1
            logging.debug("Skipping %s. Already in Radarr.", lb_title)
            progress.advance()
            continue

        result = add_to_radarr(tmdb_id, radarr_url, radarr_token, tag_names=radarr_tags)
        if result == "added":
            stats.radarr_added += 1
            existing_tmdb_ids.add(int(tmdb_id))
        elif result == "already_exists":
            stats.radarr_already_exists += 1
        else:
            stats.radarr_failed += 1
        progress.advance()

    progress.finish()

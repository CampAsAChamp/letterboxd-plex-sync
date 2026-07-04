"""Letterboxd URL to TMDB ID mapping (disk cache + API lookup)."""

from __future__ import annotations

import csv
import logging
import os
import time

import requests

from sync_helpers import TMDB_REQUEST_DELAY_SECONDS, StageProgress, lookup_tmdb_id
from sync_state import letterboxd_to_tmdb_map
from sync_stats import SyncStats


def load_existing_mapping(mapping_csv: str) -> None:
    """Load the existing Letterboxd-to-TMDB mappings from the CSV file."""
    if not os.path.exists(mapping_csv):
        return

    with open(mapping_csv, encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) >= 2 and row[0] and row[1]:
                letterboxd_to_tmdb_map[row[0]] = row[1]


def populate_letterboxd_tmdb_mapping_file(
    csv_path: str,
    letterboxd_to_tmdb_mapping_csv: str,
    tmdb_api_key: str,
    stats: SyncStats,
    progress: StageProgress | None = None,
) -> None:
    """Build the Letterboxd to TMDB mapping file for any URLs not already cached."""
    if not os.path.exists(csv_path):
        logging.debug("Skipping mapping for missing CSV: %s", csv_path)
        return

    load_existing_mapping(letterboxd_to_tmdb_mapping_csv)
    new_mappings: list[str] = []
    session = requests.Session()

    rows_to_map: list[list[str]] = []
    with open(csv_path, encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile, delimiter=",")
        next(reader, None)
        for row in reader:
            if len(row) < 4:
                continue
            if row[3] not in letterboxd_to_tmdb_map:
                rows_to_map.append(row)

    own_progress = progress is None
    stage = progress or StageProgress(
        f"TMDB mapping ({os.path.basename(csv_path)})", len(rows_to_map)
    )
    if own_progress:
        stage.start()

    for row in rows_to_map:
        lb_title = row[1]
        lb_year = row[2] if len(row) > 2 else None
        lb_url = row[3]

        try:
            time.sleep(TMDB_REQUEST_DELAY_SECONDS)
            tmdb_id = lookup_tmdb_id(
                tmdb_api_key, lb_title, lb_year or None, session=session
            )
        except requests.RequestException as exc:
            logging.debug("TMDB API lookup failed for %s: %s", lb_title, exc)
            stats.mappings_failed += 1
            stats.record("mapping", lb_title, "failed", f"API error: {exc}")
            stage.advance()
            continue

        if tmdb_id is None:
            logging.debug("No TMDB match for %s", lb_title)
            stats.mappings_failed += 1
            stats.record("mapping", lb_title, "failed", "no TMDB match")
            stage.advance()
            continue

        letterboxd_to_tmdb_map[lb_url] = tmdb_id
        new_mappings.append(f"{lb_url},{tmdb_id}\n")
        stats.mappings_added += 1
        stats.record("mapping", lb_title, "added", f"TMDB {tmdb_id}")
        stage.advance()

    if own_progress:
        stage.finish()

    if new_mappings:
        with open(letterboxd_to_tmdb_mapping_csv, "a", encoding="utf-8") as csvfile:
            csvfile.writelines(new_mappings)


def count_uncached_letterboxd_urls(csv_paths: list[str], mapping_csv: str) -> int:
    """Count unique Letterboxd URLs across CSVs that are not yet in the mapping cache."""
    load_existing_mapping(mapping_csv)
    uncached_urls: set[str] = set()
    for path in csv_paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as csvfile:
            reader = csv.reader(csvfile)
            next(reader, None)
            for row in reader:
                if len(row) >= 4 and row[3] not in letterboxd_to_tmdb_map:
                    uncached_urls.add(row[3])
    return len(uncached_urls)


def mapping_cache_is_warm(csv_paths: list[str], mapping_csv: str) -> bool:
    """Return True when every Letterboxd URL in the CSVs is already cached."""
    return count_uncached_letterboxd_urls(csv_paths, mapping_csv) == 0

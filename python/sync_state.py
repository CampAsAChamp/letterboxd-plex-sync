"""Shared mutable runtime state for the Letterboxd-Plex sync job."""

from __future__ import annotations

import os
from typing import Any

from plexapi.server import PlexServer

letterboxd_to_tmdb_map: dict[str, str] = {}
plex_guid_lookup_table: dict[str, Any] = {}

plex_metadata_server = PlexServer(
    "https://discover.provider.plex.tv", token=os.getenv("PLEX_TOKEN")
)

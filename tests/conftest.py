"""Pytest configuration — mock Plex API deps so unit tests run without plexapi installed."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

_PLEXAPI_MODULES = (
    "plexapi",
    "plexapi.server",
    "plexapi.exceptions",
    "plexapi.myplex",
    "plexapi.utils",
)

for _name in _PLEXAPI_MODULES:
    sys.modules.setdefault(_name, MagicMock())

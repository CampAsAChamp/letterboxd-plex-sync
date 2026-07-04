"""Tests for Plex video resolution and ratings sync."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from plex_sync import (
    get_plex_video_from_local_library,
    resolve_plex_video_by_letterboxd_url,
    sync_plex_ratings_from_letterboxd,
    sync_plex_watched_status_from_letterboxd,
)
from sync_state import letterboxd_to_tmdb_map, plex_guid_lookup_table
from sync_stats import SyncStats


class TestResolvePlexVideoByLetterboxdUrl:
    def setup_method(self) -> None:
        letterboxd_to_tmdb_map.clear()
        plex_guid_lookup_table.clear()

    def test_returns_local_library_item_without_metadata_lookup(self):
        lb_url = "https://boxd.it/abc"
        local_video = MagicMock(title="Inception")
        letterboxd_to_tmdb_map[lb_url] = "27205"
        plex_guid_lookup_table["tmdb://27205"] = local_video

        with patch("plex_sync.get_plex_video_by_tmdb_id") as mock_metadata:
            result = resolve_plex_video_by_letterboxd_url(lb_url)

        assert result is local_video
        mock_metadata.assert_not_called()

    def test_falls_back_to_metadata_lookup_when_not_in_local_library(self):
        lb_url = "https://boxd.it/xyz"
        metadata_video = MagicMock(title="Parasite")
        letterboxd_to_tmdb_map[lb_url] = "496243"

        with patch(
            "plex_sync.get_plex_video_by_tmdb_id", return_value=metadata_video
        ) as mock_metadata:
            result = resolve_plex_video_by_letterboxd_url(lb_url)

        assert result is metadata_video
        mock_metadata.assert_called_once_with("496243")

    def test_returns_none_when_no_tmdb_mapping(self):
        with patch("plex_sync.get_plex_video_by_tmdb_id") as mock_metadata:
            result = resolve_plex_video_by_letterboxd_url("https://boxd.it/missing")

        assert result is None
        mock_metadata.assert_not_called()

    def test_returns_none_when_metadata_lookup_fails(self):
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        with patch("plex_sync.get_plex_video_by_tmdb_id", return_value=None):
            result = resolve_plex_video_by_letterboxd_url(lb_url)

        assert result is None


class TestGetPlexVideoFromLocalLibrary:
    def setup_method(self) -> None:
        letterboxd_to_tmdb_map.clear()
        plex_guid_lookup_table.clear()

    def test_returns_none_when_tmdb_id_not_in_local_index(self):
        letterboxd_to_tmdb_map["https://boxd.it/xyz"] = "496243"
        assert get_plex_video_from_local_library("https://boxd.it/xyz") is None


class TestSyncPlexRatingsFromLetterboxd:
    def setup_method(self) -> None:
        letterboxd_to_tmdb_map.clear()
        plex_guid_lookup_table.clear()

    def test_rates_via_metadata_resolver_in_dry_run(self, tmp_path, caplog, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "true")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        ratings_csv = tmp_path / "ratings.csv"
        ratings_csv.write_text(
            "Date,Name,Year,URI,Rating\n"
            f"2024-01-01,Parasite,2019,{lb_url},4.5\n",
            encoding="utf-8",
        )

        metadata_video = MagicMock(title="Parasite", userRating=0.0)
        stats = SyncStats(dry_run=True)

        with patch(
            "plex_sync.resolve_plex_video_by_letterboxd_url",
            return_value=metadata_video,
        ):
            with caplog.at_level(logging.INFO):
                sync_plex_ratings_from_letterboxd(str(ratings_csv), stats)

        assert stats.rated == 1
        assert stats.ratings_not_in_library == 0
        assert any(
            "[DRY RUN] Would rate Parasite at 9.0/10" in record.message
            for record in caplog.records
        )

    def test_records_badrequest_when_rating_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "false")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        ratings_csv = tmp_path / "ratings.csv"
        ratings_csv.write_text(
            "Date,Name,Year,URI,Rating\n"
            f"2024-01-01,Parasite,2019,{lb_url},4.5\n",
            encoding="utf-8",
        )

        class FakeBadRequest(Exception):
            pass

        metadata_video = MagicMock(title="Parasite", userRating=0.0)
        metadata_video.rate.side_effect = FakeBadRequest("rating rejected")
        stats = SyncStats()

        with patch("plex_sync.BadRequest", FakeBadRequest):
            with patch(
                "plex_sync.resolve_plex_video_by_letterboxd_url",
                return_value=metadata_video,
            ):
                sync_plex_ratings_from_letterboxd(str(ratings_csv), stats)

        assert stats.rated == 0
        assert stats.items[-1].status == "error"
        assert stats.items[-1].detail == "Plex BadRequest"

    def test_records_not_in_library_when_resolver_returns_none(self, tmp_path):
        lb_url = "https://boxd.it/missing"
        ratings_csv = tmp_path / "ratings.csv"
        ratings_csv.write_text(
            "Date,Name,Year,URI,Rating\n"
            f"2024-01-01,Dope Thief,2025,{lb_url},3.5\n",
            encoding="utf-8",
        )
        stats = SyncStats()

        with patch("plex_sync.resolve_plex_video_by_letterboxd_url", return_value=None):
            sync_plex_ratings_from_letterboxd(str(ratings_csv), stats)

        assert stats.ratings_not_in_library == 1
        assert stats.items[0].status == "not_in_library"


class TestSyncPlexWatchedStatusFromLetterboxd:
    def setup_method(self) -> None:
        letterboxd_to_tmdb_map.clear()
        plex_guid_lookup_table.clear()

    def test_marks_via_metadata_resolver_in_dry_run(self, tmp_path, caplog, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "true")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        watched_csv = tmp_path / "watched.csv"
        watched_csv.write_text(
            "Date,Name,Year,URI\n"
            f"2024-01-01,Parasite,2019,{lb_url}\n",
            encoding="utf-8",
        )

        metadata_video = MagicMock(title="Parasite", isPlayed=False)
        stats = SyncStats(dry_run=True)

        with patch(
            "plex_sync.resolve_plex_video_by_letterboxd_url",
            return_value=metadata_video,
        ):
            with caplog.at_level(logging.INFO):
                sync_plex_watched_status_from_letterboxd(str(watched_csv), stats)

        assert stats.marked_watched == 1
        assert stats.watched_not_in_library == 0
        assert any(
            "[DRY RUN] Would mark Parasite as played." in record.message
            for record in caplog.records
        )

    def test_skips_already_played_via_metadata_resolver(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "true")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        watched_csv = tmp_path / "watched.csv"
        watched_csv.write_text(
            "Date,Name,Year,URI\n"
            f"2024-01-01,Parasite,2019,{lb_url}\n",
            encoding="utf-8",
        )

        metadata_video = MagicMock(title="Parasite", isPlayed=True)
        stats = SyncStats(dry_run=True)

        with patch(
            "plex_sync.resolve_plex_video_by_letterboxd_url",
            return_value=metadata_video,
        ):
            sync_plex_watched_status_from_letterboxd(str(watched_csv), stats)

        assert stats.marked_watched == 0
        assert stats.watched_skipped == 1
        assert stats.items[0].status == "already_played"

    def test_records_badrequest_when_mark_played_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "false")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        watched_csv = tmp_path / "watched.csv"
        watched_csv.write_text(
            "Date,Name,Year,URI\n"
            f"2024-01-01,Parasite,2019,{lb_url}\n",
            encoding="utf-8",
        )

        class FakeBadRequest(Exception):
            pass

        metadata_video = MagicMock(title="Parasite", isPlayed=False)
        metadata_video.markPlayed.side_effect = FakeBadRequest("mark played rejected")
        stats = SyncStats()

        with patch("plex_sync.BadRequest", FakeBadRequest):
            with patch(
                "plex_sync.resolve_plex_video_by_letterboxd_url",
                return_value=metadata_video,
            ):
                sync_plex_watched_status_from_letterboxd(str(watched_csv), stats)

        assert stats.marked_watched == 0
        assert stats.items[-1].status == "error"
        assert stats.items[-1].detail == "Plex BadRequest"

    def test_records_not_in_library_when_resolver_returns_none(self, tmp_path):
        lb_url = "https://boxd.it/missing"
        watched_csv = tmp_path / "watched.csv"
        watched_csv.write_text(
            "Date,Name,Year,URI\n"
            f"2024-01-01,Dope Thief,2025,{lb_url}\n",
            encoding="utf-8",
        )
        stats = SyncStats()

        with patch("plex_sync.resolve_plex_video_by_letterboxd_url", return_value=None):
            sync_plex_watched_status_from_letterboxd(str(watched_csv), stats)

        assert stats.watched_not_in_library == 1
        assert stats.items[0].status == "not_in_library"

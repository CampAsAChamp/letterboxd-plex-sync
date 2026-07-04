"""Tests for Plex video resolution and ratings sync."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import plex_sync
from plex_sync import (
    get_plex_video_from_local_library,
    is_local_plex_video,
    resolve_plex_video_by_letterboxd_url,
    sync_plex_ratings_from_letterboxd,
    sync_plex_watched_status_from_letterboxd,
)
from sync_state import letterboxd_to_tmdb_map, plex_guid_lookup_table
from sync_stats import SyncStats


class TestIsLocalPlexVideo:
    def test_true_for_local_library_video(self):
        video = MagicMock()
        video._server = MagicMock(name="local_plex_server")
        assert is_local_plex_video(video) is True

    def test_false_for_remote_metadata_match(self):
        video = MagicMock()
        video._server = plex_sync.plex_metadata_server
        assert is_local_plex_video(video) is False


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

    def test_rates_local_library_video_in_dry_run(self, tmp_path, caplog, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "true")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        ratings_csv = tmp_path / "ratings.csv"
        ratings_csv.write_text(
            "Date,Name,Year,URI,Rating\n"
            f"2024-01-01,Parasite,2019,{lb_url},4.5\n",
            encoding="utf-8",
        )

        local_video = MagicMock(title="Parasite", userRating=0.0)
        stats = SyncStats(dry_run=True)

        with patch(
            "plex_sync.resolve_plex_video_by_letterboxd_url",
            return_value=local_video,
        ):
            with caplog.at_level(logging.INFO):
                sync_plex_ratings_from_letterboxd(str(ratings_csv), stats)

        assert stats.rated == 1
        assert stats.ratings_not_in_library == 0
        assert any(
            "[DRY RUN] Would rate Parasite at 9.0/10" in record.message
            for record in caplog.records
        )

    def test_skips_remote_metadata_match_as_not_in_library(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "true")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        ratings_csv = tmp_path / "ratings.csv"
        ratings_csv.write_text(
            "Date,Name,Year,URI,Rating\n"
            f"2024-01-01,Parasite,2019,{lb_url},4.5\n",
            encoding="utf-8",
        )

        remote_video = MagicMock(title="Parasite", userRating=0.0)
        remote_video._server = plex_sync.plex_metadata_server
        stats = SyncStats(dry_run=True)

        with patch(
            "plex_sync.resolve_plex_video_by_letterboxd_url",
            return_value=remote_video,
        ):
            sync_plex_ratings_from_letterboxd(str(ratings_csv), stats)

        assert stats.rated == 0
        assert stats.ratings_not_in_library == 1
        assert stats.items[0].status == "not_in_library"
        remote_video.rate.assert_not_called()

    def test_records_plex_error_when_rating_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "false")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        ratings_csv = tmp_path / "ratings.csv"
        ratings_csv.write_text(
            "Date,Name,Year,URI,Rating\n"
            f"2024-01-01,Parasite,2019,{lb_url},4.5\n",
            encoding="utf-8",
        )

        class FakePlexApiException(Exception):
            pass

        local_video = MagicMock(title="Parasite", userRating=0.0)
        local_video.rate.side_effect = FakePlexApiException("rating rejected")
        stats = SyncStats()

        with patch("plex_sync.PlexApiException", FakePlexApiException):
            with patch(
                "plex_sync.resolve_plex_video_by_letterboxd_url",
                return_value=local_video,
            ):
                sync_plex_ratings_from_letterboxd(str(ratings_csv), stats)

        assert stats.rated == 0
        assert stats.items[-1].status == "error"
        assert stats.items[-1].detail == "Plex error: rating rejected"

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

    def test_marks_local_library_video_in_dry_run(self, tmp_path, caplog, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "true")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        watched_csv = tmp_path / "watched.csv"
        watched_csv.write_text(
            "Date,Name,Year,URI\n"
            f"2024-01-01,Parasite,2019,{lb_url}\n",
            encoding="utf-8",
        )

        local_video = MagicMock(title="Parasite", isPlayed=False)
        user = MagicMock()
        stats = SyncStats(dry_run=True)

        with patch(
            "plex_sync.resolve_plex_video_by_letterboxd_url",
            return_value=local_video,
        ):
            with caplog.at_level(logging.INFO):
                sync_plex_watched_status_from_letterboxd(user, str(watched_csv), stats)

        assert stats.marked_watched == 1
        assert stats.watched_not_in_library == 0
        assert any(
            "[DRY RUN] Would mark Parasite as played." in record.message
            for record in caplog.records
        )
        user.isPlayed.assert_not_called()

    def test_skips_already_played_local_library_video(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "true")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        watched_csv = tmp_path / "watched.csv"
        watched_csv.write_text(
            "Date,Name,Year,URI\n"
            f"2024-01-01,Parasite,2019,{lb_url}\n",
            encoding="utf-8",
        )

        local_video = MagicMock(title="Parasite", isPlayed=True)
        user = MagicMock()
        stats = SyncStats(dry_run=True)

        with patch(
            "plex_sync.resolve_plex_video_by_letterboxd_url",
            return_value=local_video,
        ):
            sync_plex_watched_status_from_letterboxd(user, str(watched_csv), stats)

        assert stats.marked_watched == 0
        assert stats.watched_skipped == 1
        assert stats.items[0].status == "already_played"

    def test_marks_remote_metadata_match_via_account(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "false")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        watched_csv = tmp_path / "watched.csv"
        watched_csv.write_text(
            "Date,Name,Year,URI\n"
            f"2024-01-01,Parasite,2019,{lb_url}\n",
            encoding="utf-8",
        )

        remote_video = MagicMock(title="Parasite")
        remote_video._server = plex_sync.plex_metadata_server
        user = MagicMock()
        user.isPlayed.return_value = False
        stats = SyncStats()

        with patch(
            "plex_sync.resolve_plex_video_by_letterboxd_url",
            return_value=remote_video,
        ):
            sync_plex_watched_status_from_letterboxd(user, str(watched_csv), stats)

        assert stats.marked_watched == 1
        assert stats.watched_not_in_library == 0
        assert stats.items[0].status == "marked"
        user.isPlayed.assert_called_once_with(remote_video)
        user.markPlayed.assert_called_once_with(remote_video)
        remote_video.markPlayed.assert_not_called()

    def test_skips_already_played_remote_metadata_match(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "false")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        watched_csv = tmp_path / "watched.csv"
        watched_csv.write_text(
            "Date,Name,Year,URI\n"
            f"2024-01-01,Parasite,2019,{lb_url}\n",
            encoding="utf-8",
        )

        remote_video = MagicMock(title="Parasite")
        remote_video._server = plex_sync.plex_metadata_server
        user = MagicMock()
        user.isPlayed.return_value = True
        stats = SyncStats()

        with patch(
            "plex_sync.resolve_plex_video_by_letterboxd_url",
            return_value=remote_video,
        ):
            sync_plex_watched_status_from_letterboxd(user, str(watched_csv), stats)

        assert stats.marked_watched == 0
        assert stats.watched_skipped == 1
        assert stats.items[0].status == "already_played"
        user.markPlayed.assert_not_called()

    def test_records_plex_error_when_mark_played_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "false")
        lb_url = "https://boxd.it/xyz"
        letterboxd_to_tmdb_map[lb_url] = "496243"

        watched_csv = tmp_path / "watched.csv"
        watched_csv.write_text(
            "Date,Name,Year,URI\n"
            f"2024-01-01,Parasite,2019,{lb_url}\n",
            encoding="utf-8",
        )

        class FakePlexApiException(Exception):
            pass

        local_video = MagicMock(title="Parasite", isPlayed=False)
        local_video.markPlayed.side_effect = FakePlexApiException("mark played rejected")
        user = MagicMock()
        stats = SyncStats()

        with patch("plex_sync.PlexApiException", FakePlexApiException):
            with patch(
                "plex_sync.resolve_plex_video_by_letterboxd_url",
                return_value=local_video,
            ):
                sync_plex_watched_status_from_letterboxd(user, str(watched_csv), stats)

        assert stats.marked_watched == 0
        assert stats.items[-1].status == "error"
        assert stats.items[-1].detail == "Plex error: mark played rejected"

    def test_records_not_in_library_when_resolver_returns_none(self, tmp_path):
        lb_url = "https://boxd.it/missing"
        watched_csv = tmp_path / "watched.csv"
        watched_csv.write_text(
            "Date,Name,Year,URI\n"
            f"2024-01-01,Dope Thief,2025,{lb_url}\n",
            encoding="utf-8",
        )
        user = MagicMock()
        stats = SyncStats()

        with patch("plex_sync.resolve_plex_video_by_letterboxd_url", return_value=None):
            sync_plex_watched_status_from_letterboxd(user, str(watched_csv), stats)

        assert stats.watched_not_in_library == 1
        assert stats.items[0].status == "not_in_library"

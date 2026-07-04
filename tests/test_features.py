"""Tests for sync_config and tmdb_mapping."""

from __future__ import annotations

from sync_config import is_dry_run
from sync_state import letterboxd_to_tmdb_map
from tmdb_mapping import count_uncached_letterboxd_urls, mapping_cache_is_warm


class TestDryRun:
    def test_is_dry_run_defaults_false(self, monkeypatch):
        monkeypatch.delenv("DRY_RUN", raising=False)
        assert is_dry_run() is False

    def test_is_dry_run_true(self, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "true")
        assert is_dry_run() is True


class TestMappingCache:
    def setup_method(self) -> None:
        letterboxd_to_tmdb_map.clear()

    def test_mapping_cache_is_warm_when_all_urls_cached(self, tmp_path):
        mapping_csv = tmp_path / "map.csv"
        mapping_csv.write_text(
            "https://letterboxd.com/film/inception/,27205\n", encoding="utf-8"
        )
        ratings_csv = tmp_path / "ratings.csv"
        ratings_csv.write_text(
            "Date,Name,Year,URI,Rating\n"
            "2024-01-01,Inception,2010,https://letterboxd.com/film/inception/,5\n",
            encoding="utf-8",
        )

        assert mapping_cache_is_warm([str(ratings_csv)], str(mapping_csv)) is True
        assert count_uncached_letterboxd_urls([str(ratings_csv)], str(mapping_csv)) == 0

    def test_mapping_cache_is_cold_when_url_missing(self, tmp_path):
        mapping_csv = tmp_path / "map.csv"
        mapping_csv.write_text("", encoding="utf-8")
        ratings_csv = tmp_path / "ratings.csv"
        ratings_csv.write_text(
            "Date,Name,Year,URI,Rating\n"
            "2024-01-01,Inception,2010,https://letterboxd.com/film/inception/,5\n",
            encoding="utf-8",
        )

        assert mapping_cache_is_warm([str(ratings_csv)], str(mapping_csv)) is False
        assert count_uncached_letterboxd_urls([str(ratings_csv)], str(mapping_csv)) == 1

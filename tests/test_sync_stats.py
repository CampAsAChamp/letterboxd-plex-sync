"""Tests for sync_stats reporting and summary."""

from __future__ import annotations

import logging

from sync_stats import SyncStats


class TestSyncStatsRecord:
    def test_record_accumulates_outcomes(self):
        stats = SyncStats()
        stats.record("rating", "Inception", "updated", "9/10")
        stats.record("rating", "Unknown Film", "not_in_library")

        assert len(stats.items) == 2
        assert stats.items[0].category == "rating"
        assert stats.items[0].title == "Inception"
        assert stats.items[1].status == "not_in_library"


class TestWriteReport:
    def test_write_report_includes_succeeded_and_failed_sections(self, tmp_path):
        stats = SyncStats(dry_run=True)
        stats.record("mapping", "Inception", "added", "TMDB 27205")
        stats.record("mapping", "Obscure Film", "failed", "no TMDB match")
        stats.record("rating", "Inception", "updated", "9/10")
        stats.record("rating", "Missing Film", "not_in_library")

        report_path = tmp_path / "report.txt"
        written = stats.write_report(str(report_path))

        assert written == str(report_path)
        content = report_path.read_text(encoding="utf-8")
        assert "Letterboxd-Plex Sync Report" in content
        assert "(DRY RUN)" in content
        assert "TMDB mappings" in content
        assert "Succeeded (1)" in content
        assert "- Inception — TMDB 27205" in content
        assert "Failed (1)" in content
        assert "- Obscure Film — no TMDB match" in content
        assert "Ratings" in content
        assert "- Missing Film" in content


class TestLogSummary:
    def test_log_summary_lists_failures_and_paths(self, caplog):
        stats = SyncStats()
        stats.record("watchlist", "Missing Film", "not_in_library")
        stats.record("radarr", "Bad Add", "failed", "TMDB 123")

        with caplog.at_level(logging.INFO):
            stats.log_summary(
                report_path="/app/data/latest_sync_report.txt",
                combined_log_path="/app/data/combined_log.txt",
            )

        messages = [record.message for record in caplog.records]
        assert any("Failures:" in message for message in messages)
        assert any("Missing Film" in message for message in messages)
        assert any("Bad Add" in message for message in messages)
        assert any(
            "Detailed report: /app/data/latest_sync_report.txt" in message
            for message in messages
        )
        assert any(
            "Full run log: /app/data/combined_log.txt" in message
            for message in messages
        )

    def test_log_summary_reports_no_failures(self, caplog):
        stats = SyncStats()
        stats.record("rating", "Inception", "updated", "9/10")

        with caplog.at_level(logging.INFO):
            stats.log_summary()

        messages = [record.message for record in caplog.records]
        assert any("Failures: none" in message for message in messages)

    def test_log_summary_caps_inline_failures(self, monkeypatch, caplog):
        monkeypatch.setenv("SYNC_REPORT_INLINE_LIMIT", "25")
        stats = SyncStats()
        for index in range(30):
            stats.record("rating", f"Film {index}", "not_in_library")

        with caplog.at_level(logging.INFO):
            stats.log_summary(report_path="/tmp/report.txt")

        messages = [record.message for record in caplog.records]
        assert sum("Film " in message for message in messages) == 25
        assert any("... and 5 more in report" in message for message in messages)

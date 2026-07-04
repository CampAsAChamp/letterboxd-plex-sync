"""Tests for letterboxd-plex-sync helper functions."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sync_helpers import (
    StageProgress,
    WorkflowSteps,
    classify_radarr_error,
    count_csv_data_rows,
    format_progress_bar,
    letterboxd_rating_to_plex,
    lookup_tmdb_id,
    parse_radarr_error_response,
)


class TestLetterboxdRatingToPlex:
    def test_converts_half_star_ratings(self):
        assert letterboxd_rating_to_plex(2.5) == 5.0
        assert letterboxd_rating_to_plex(5.0) == 10.0
        assert letterboxd_rating_to_plex(0.0) == 0.0


class TestProgressHelpers:
    def test_format_progress_bar_empty(self):
        assert format_progress_bar(0, 0) == "[--------------------]"

    def test_format_progress_bar_half(self):
        assert format_progress_bar(5, 10, width=10) == "[=====-----]"

    def test_format_progress_bar_complete(self):
        assert format_progress_bar(10, 10, width=10) == "[==========]"

    def test_count_csv_data_rows(self, tmp_path):
        csv_file = tmp_path / "sample.csv"
        csv_file.write_text(
            "Date,Name,Year,URI,Rating\n"
            "2024-01-01,Inception,2010,https://letterboxd.com/film/inception/,5\n"
            "2024-01-02,Bad Row\n",
            encoding="utf-8",
        )
        assert count_csv_data_rows(str(csv_file), min_columns=4) == 1

    def test_stage_progress_logs_milestones(self, caplog):
        import logging

        caplog.set_level(logging.INFO)
        progress = StageProgress("Test stage", 100)
        progress.start()
        progress.advance(10)
        progress.advance(10)
        progress.finish()
        messages = [record.message for record in caplog.records]
        assert any("Test stage: 0/100" in message for message in messages)
        assert any("Test stage: 100/100" in message for message in messages)

    def test_workflow_steps_numbering(self, caplog):
        import logging

        caplog.set_level(logging.INFO)
        workflow = WorkflowSteps(["Alpha", "Beta"])
        with workflow.step("Alpha"):
            pass
        with workflow.step("Beta"):
            pass
        messages = [record.message for record in caplog.records]
        assert messages[0] == "[Step 1/2] Alpha — starting"
        assert messages[1].startswith("[Step 1/2] Alpha — complete (")
        assert messages[2] == "[Step 2/2] Beta — starting"


class TestLookupTmdbId:
    def test_returns_first_result_id(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": [{"id": 27205}]}
        mock_response.raise_for_status = MagicMock()
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        result = lookup_tmdb_id("key", "Inception", "2010", session=mock_session)

        assert result == "27205"
        mock_session.get.assert_called_once()
        call_kwargs = mock_session.get.call_args
        assert call_kwargs[1]["params"]["query"] == "Inception"
        assert call_kwargs[1]["params"]["year"] == "2010"

    def test_returns_none_when_no_results(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        assert lookup_tmdb_id("key", "Unknown Film", session=mock_session) is None

    def test_returns_none_without_api_key(self):
        assert lookup_tmdb_id("", "Inception") is None


class TestRadarrErrorParsing:
    def test_parses_error_list(self):
        content = json.dumps(
            [{"errorCode": "MovieExistsValidator", "errorMessage": "exists"}]
        ).encode()
        errors = parse_radarr_error_response(content)
        assert len(errors) == 1
        assert classify_radarr_error(errors[0]) == "already_exists"

    def test_handles_invalid_json(self):
        assert parse_radarr_error_response(b"not json") == []

    def test_classifies_not_found(self):
        error = {
            "errorCode": "SomeCode",
            "errorMessage": "A movie with this ID was not found, please try again.",
        }
        assert classify_radarr_error(error) == "not_found"

    def test_classifies_path_conflict(self):
        error = {"errorCode": "MoviePathValidator", "errorMessage": "Path already in use"}
        assert classify_radarr_error(error) == "path_conflict"


class TestGenerateConfig:
    def test_exits_when_required_env_missing(self, monkeypatch, caplog):
        import logging

        import generate_config

        caplog.set_level(logging.ERROR)
        for name in ("LB_USERNAME", "LB_PASSWORD", "TMDB_API_KEY"):
            monkeypatch.delenv(name, raising=False)

        with pytest.raises(SystemExit) as exc_info:
            generate_config.main()

        assert exc_info.value.code == 1
        assert any(
            "Missing required environment variables" in record.message
            for record in caplog.records
        )


class TestSyncScriptSyntax:
    def test_scripts_compile(self):
        repo_root = Path(__file__).resolve().parents[1]
        for script in (
            "python/generate_config.py",
            "python/sync_helpers.py",
            "python/sync_state.py",
            "python/sync_stats.py",
            "python/sync_config.py",
            "python/tmdb_mapping.py",
            "python/plex_sync.py",
            "python/radarr_sync.py",
            "python/sync_lb_to_plex.py",
        ):
            subprocess.run(
                [sys.executable, "-m", "py_compile", str(repo_root / script)],
                check=True,
            )

"""Tests for the Google Sheets sync agent and SheetsClient.

All Google API calls are mocked — no real credentials or network required.
SheetsClient.__init__ is patched at the integration layer so we can test
agent behaviour (skip conditions, dedup, append) without needing a real Sheet.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_job_agent.agents.sync_sheets import make_sync_sheets_node, sync_to_sheet
from pm_job_agent.config.settings import Settings
from pm_job_agent.integrations.sheets import SheetsClient, SheetsError
from pm_job_agent.services.types import RankedJobDict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**overrides) -> Settings:
    defaults = dict(default_llm_provider="stub")
    defaults.update(overrides)
    return Settings(**defaults)


def _job(job_id: str = "src:1", score: float = 0.4, title: str = "PM Role") -> RankedJobDict:
    return RankedJobDict(
        id=job_id,
        title=title,
        company="Testco",
        location="Remote",
        url="https://example.com/job",
        source="test",
        description_snippet="Some description",
        score=score,
    )


def _mock_client(existing_ids: set | None = None) -> MagicMock:
    """Return a MagicMock SheetsClient with controllable existing IDs."""
    client = MagicMock(spec=SheetsClient)
    client.get_existing_ids.return_value = existing_ids or set()
    client.append_jobs.return_value = 0
    return client


# ---------------------------------------------------------------------------
# sync_to_sheet — skip conditions
# ---------------------------------------------------------------------------

class TestSyncSkipConditions:
    def test_skips_when_sheets_id_not_configured(self):
        """Pipeline should pass through cleanly when GOOGLE_SHEETS_ID is absent."""
        settings = _settings()  # google_sheets_id defaults to None
        result = sync_to_sheet({"ranked_jobs": [_job()]}, settings=settings)
        assert result == {}

    def test_skips_when_service_account_file_missing(self, tmp_path):
        """Pipeline should pass through when service account file doesn't exist."""
        settings = _settings(
            google_sheets_id="sheet123",
            google_service_account_path=tmp_path / "nonexistent.json",
        )
        result = sync_to_sheet({"ranked_jobs": [_job()]}, settings=settings)
        assert result == {}

    def test_skips_when_no_ranked_jobs(self, tmp_path):
        """No API call should happen when there are no jobs to sync."""
        sa_path = tmp_path / "sa.json"
        sa_path.write_text("{}")
        settings = _settings(
            google_sheets_id="sheet123",
            google_service_account_path=sa_path,
        )
        with patch("pm_job_agent.agents.sync_sheets.SheetsClient") as mock_cls:
            result = sync_to_sheet({"ranked_jobs": []}, settings=settings)
        mock_cls.assert_not_called()
        assert result == {}

    def test_skips_when_ranked_jobs_absent_from_state(self, tmp_path):
        """Missing ranked_jobs key in state should be treated as empty."""
        sa_path = tmp_path / "sa.json"
        sa_path.write_text("{}")
        settings = _settings(
            google_sheets_id="sheet123",
            google_service_account_path=sa_path,
        )
        with patch("pm_job_agent.agents.sync_sheets.SheetsClient") as mock_cls:
            result = sync_to_sheet({}, settings=settings)
        mock_cls.assert_not_called()
        assert result == {}

    def test_returns_empty_dict_on_sheets_error(self, tmp_path):
        """A SheetsError should be caught and logged — pipeline must not fail."""
        sa_path = tmp_path / "sa.json"
        sa_path.write_text("{}")
        settings = _settings(
            google_sheets_id="sheet123",
            google_service_account_path=sa_path,
        )
        with patch(
            "pm_job_agent.agents.sync_sheets.SheetsClient",
            side_effect=SheetsError("API down"),
        ):
            result = sync_to_sheet({"ranked_jobs": [_job()]}, settings=settings)
        assert result == {}


# ---------------------------------------------------------------------------
# sync_to_sheet — happy path and deduplication
# ---------------------------------------------------------------------------

class TestSyncAppendBehavior:
    def _run_with_mock_client(self, state: dict, settings: Settings, mock_client: MagicMock) -> dict:
        with patch(
            "pm_job_agent.agents.sync_sheets.SheetsClient", return_value=mock_client
        ):
            return sync_to_sheet(state, settings=settings)

    def _settings_with_sa(self, tmp_path) -> Settings:
        sa_path = tmp_path / "sa.json"
        sa_path.write_text("{}")
        return _settings(
            google_sheets_id="sheet123",
            google_service_account_path=sa_path,
        )

    def test_calls_append_jobs_with_all_jobs_when_sheet_empty(self, tmp_path):
        settings = self._settings_with_sa(tmp_path)
        jobs = [_job("src:1"), _job("src:2"), _job("src:3")]
        client = _mock_client(existing_ids=set())
        client.append_jobs.return_value = 3

        self._run_with_mock_client({"ranked_jobs": jobs}, settings, client)

        client.append_jobs.assert_called_once()
        call_kwargs = client.append_jobs.call_args
        assert call_kwargs[0][0] == jobs  # first positional arg is the jobs list

    def test_passes_new_job_ids_from_state(self, tmp_path):
        settings = self._settings_with_sa(tmp_path)
        jobs = [_job("src:1"), _job("src:2")]
        new_ids = {"src:1"}
        client = _mock_client()

        self._run_with_mock_client(
            {"ranked_jobs": jobs, "new_job_ids": list(new_ids)},
            settings,
            client,
        )

        _, call_kwargs = client.append_jobs.call_args
        assert call_kwargs["new_job_ids"] == new_ids

    def test_passes_existing_ids_to_append(self, tmp_path):
        """existing_ids fetched via get_existing_ids() should be forwarded to append_jobs."""
        settings = self._settings_with_sa(tmp_path)
        existing = {"src:old1", "src:old2"}
        client = _mock_client(existing_ids=existing)

        self._run_with_mock_client({"ranked_jobs": [_job("src:new")]}, settings, client)

        _, call_kwargs = client.append_jobs.call_args
        assert call_kwargs["existing_ids"] == existing

    def test_returns_empty_dict_on_success(self, tmp_path):
        """Node always returns empty dict — state is not modified."""
        settings = self._settings_with_sa(tmp_path)
        client = _mock_client()
        result = self._run_with_mock_client({"ranked_jobs": [_job()]}, settings, client)
        assert result == {}


# ---------------------------------------------------------------------------
# make_sync_sheets_node — factory pattern
# ---------------------------------------------------------------------------

class TestMakeSyncSheetsNode:
    def test_returns_callable(self):
        settings = _settings()
        node = make_sync_sheets_node(settings)
        assert callable(node)

    def test_node_passes_through_when_unconfigured(self):
        """Factory-produced node should skip silently with no GOOGLE_SHEETS_ID."""
        settings = _settings()
        node = make_sync_sheets_node(settings)
        result = node({"ranked_jobs": [_job()]})
        assert result == {}


# ---------------------------------------------------------------------------
# SheetsClient — unit tests (mocking gspread internals)
# ---------------------------------------------------------------------------

class TestSheetsClientGetExistingIds:
    def _make_client_with_sheet(self, col_values: list) -> SheetsClient:
        """Construct a SheetsClient with all external calls mocked."""
        mock_sheet = MagicMock()
        mock_sheet.col_values.return_value = col_values
        mock_sheet.row_count = len(col_values)

        with (
            patch("pm_job_agent.integrations.sheets.Path.exists", return_value=True),
            patch("pm_job_agent.integrations.sheets.Credentials.from_service_account_file"),
            patch("pm_job_agent.integrations.sheets.gspread.authorize") as mock_auth,
        ):
            mock_auth.return_value.open_by_key.return_value.sheet1 = mock_sheet
            client = SheetsClient("sheet123", Path("fake/sa.json"))
            client._sheet = mock_sheet
        return client

    def test_returns_empty_set_for_blank_sheet(self):
        client = self._make_client_with_sheet([])
        assert client.get_existing_ids() == set()

    def test_strips_header_row(self):
        client = self._make_client_with_sheet(["job_id", "src:1", "src:2"])
        assert client.get_existing_ids() == {"src:1", "src:2"}

    def test_returns_ids_without_header(self):
        client = self._make_client_with_sheet(["src:1", "src:2", "src:3"])
        # If first value is not "job_id", all values are treated as IDs
        assert client.get_existing_ids() == {"src:1", "src:2", "src:3"}

    def test_filters_empty_strings(self):
        client = self._make_client_with_sheet(["job_id", "src:1", "", "src:2"])
        assert client.get_existing_ids() == {"src:1", "src:2"}


class TestSheetsClientAppendJobs:
    def _make_client(self, existing_col: list | None = None) -> tuple[SheetsClient, MagicMock]:
        mock_sheet = MagicMock()
        mock_sheet.col_values.return_value = existing_col or []
        mock_sheet.row_count = len(existing_col or [])
        mock_sheet.row_values.return_value = []  # no header present

        with (
            patch("pm_job_agent.integrations.sheets.Path.exists", return_value=True),
            patch("pm_job_agent.integrations.sheets.Credentials.from_service_account_file"),
            patch("pm_job_agent.integrations.sheets.gspread.authorize") as mock_auth,
        ):
            mock_auth.return_value.open_by_key.return_value.sheet1 = mock_sheet
            client = SheetsClient("sheet123", Path("fake/sa.json"))
            client._sheet = mock_sheet
        return client, mock_sheet

    def test_appends_all_jobs_when_none_exist(self):
        client, mock_sheet = self._make_client()
        jobs = [_job("src:1"), _job("src:2")]
        count = client.append_jobs(jobs, existing_ids=set())
        assert count == 2
        mock_sheet.append_rows.assert_called_once()

    def test_skips_already_present_jobs(self):
        client, mock_sheet = self._make_client()
        jobs = [_job("src:1"), _job("src:2"), _job("src:3")]
        count = client.append_jobs(jobs, existing_ids={"src:1", "src:3"})
        assert count == 1
        appended_rows = mock_sheet.append_rows.call_args[0][0]
        assert len(appended_rows) == 1
        assert appended_rows[0][0] == "src:2"  # job_id is first column

    def test_returns_zero_when_all_jobs_already_present(self):
        client, mock_sheet = self._make_client()
        jobs = [_job("src:1"), _job("src:2")]
        count = client.append_jobs(jobs, existing_ids={"src:1", "src:2"})
        assert count == 0
        mock_sheet.append_rows.assert_not_called()

    def test_marks_new_column_correctly(self):
        client, mock_sheet = self._make_client()
        jobs = [_job("src:1"), _job("src:2")]
        client.append_jobs(jobs, new_job_ids={"src:1"}, existing_ids=set())
        appended_rows = mock_sheet.append_rows.call_args[0][0]
        # row[8] is the 'new' column (index 8 in _SHEET_COLUMNS)
        assert appended_rows[0][8] == "yes"   # src:1 is new
        assert appended_rows[1][8] == ""      # src:2 is not new

    def test_skips_jobs_with_no_id(self):
        client, mock_sheet = self._make_client()
        job_no_id = RankedJobDict(
            id="",
            title="No ID Job",
            company="Testco",
            url="https://example.com",
            source="test",
            description_snippet="",
            score=0.5,
        )
        count = client.append_jobs([job_no_id], existing_ids=set())
        assert count == 0
        mock_sheet.append_rows.assert_not_called()

    def test_raises_sheets_error_on_api_failure(self):
        import gspread
        client, mock_sheet = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": {"code": 500, "message": "Internal error", "status": "INTERNAL"}}
        mock_sheet.append_rows.side_effect = gspread.exceptions.APIError(mock_response)
        with pytest.raises(SheetsError):
            client.append_jobs([_job("src:1")], existing_ids=set())

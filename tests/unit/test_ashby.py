"""Tests for the Ashby posting API client."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pm_job_agent.integrations.ashby import AshbyClient, AshbyError


def _mock_response(status_code: int, json_body: dict[str, Any]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_body
    return mock


_SAMPLE = {
    "apiVersion": "1",
    "jobs": [
        {
            "id": "dea8c3c1-dead-beef-ca11-abad1dea",
            "title": "Senior Product Manager",
            "location": "Remote",
            "jobUrl": "https://jobs.ashbyhq.com/testco/jobs/uuid-one",
            "applyUrl": "https://jobs.ashbyhq.com/testco/application",
            "descriptionPlain": "Build AI roadmap.",
            "publishedAt": "2026-01-01T12:00:00+00:00",
        },
        {
            "id": "eae8c3c2-dead-beef-ca11-abcd2dea",
            "title": "Engineering Manager",
            "location": "San Francisco, CA",
            "jobUrl": "https://jobs.ashbyhq.com/testco/jobs/uuid-two",
            "descriptionPlain": "Lead infra.",
            "publishedAt": "2026-01-02T00:00:00Z",
        },
    ],
}


class TestAshbyClientFetchJobs:
    def test_filters_by_title_keyword(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200, _SAMPLE)):
            client = AshbyClient()
            jobs = client.fetch_jobs("testco", title_keywords=["Product Manager"])

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Senior Product Manager"

    def test_returns_all_jobs_when_no_keywords(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200, _SAMPLE)):
            client = AshbyClient()
            jobs = client.fetch_jobs("testco", title_keywords=[])

        assert len(jobs) == 2

    def test_maps_fields_to_job_dict(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200, _SAMPLE)):
            client = AshbyClient()
            jobs = client.fetch_jobs("testco", title_keywords=["Senior Product"])

        job = jobs[0]
        assert job["id"] == "ashby:testco:dea8c3c1-dead-beef-ca11-abad1dea"
        assert job["company"] == "testco"

    def test_company_label_overrides_company(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200, _SAMPLE)):
            client = AshbyClient()
            jobs = client.fetch_jobs(
                "testco", title_keywords=["Senior Product"], company_label="Ashby Labs"
            )
        job = jobs[0]
        assert job["company"] == "Ashby Labs"
        assert job["source"] == "ashby"
        assert job["url"] == "https://jobs.ashbyhq.com/testco/jobs/uuid-one"
        assert job["location"] == "Remote"
        assert job["source_posted_at"] == "2026-01-01T12:00:00+00:00"

    def test_404_returns_empty(self) -> None:
        with patch("httpx.get", return_value=_mock_response(404, {})):
            client = AshbyClient()
            jobs = client.fetch_jobs("gone", title_keywords=[])

        assert jobs == []

    def test_raises_on_other_http_errors(self) -> None:
        with patch("httpx.get", return_value=_mock_response(500, {})):
            client = AshbyClient()
            with pytest.raises(AshbyError, match="HTTP 500"):
                client.fetch_jobs("testco", title_keywords=[])

    def test_raises_on_network_error(self) -> None:
        with patch("httpx.get", side_effect=httpx.RequestError("boom")):
            client = AshbyClient()
            with pytest.raises(AshbyError, match="Network error"):
                client.fetch_jobs("testco", title_keywords=[])

    def test_raises_on_invalid_json(self) -> None:
        mock = MagicMock()
        mock.status_code = 200
        mock.json.side_effect = ValueError("not json")

        with patch("httpx.get", return_value=mock):
            client = AshbyClient()
            with pytest.raises(AshbyError, match="invalid JSON"):
                client.fetch_jobs("testco", title_keywords=[])

    def test_raises_on_jobs_not_a_list(self) -> None:
        with patch(
            "httpx.get",
            return_value=_mock_response(200, {"apiVersion": "1", "jobs": {}}),
        ):
            client = AshbyClient()
            with pytest.raises(AshbyError, match="unexpected response shape"):
                client.fetch_jobs("testco", title_keywords=[])

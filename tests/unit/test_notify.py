"""Tests for the email digest notification agent."""

from __future__ import annotations

import email as email_lib
from unittest.mock import MagicMock, patch

import pytest

from pm_job_agent.agents.notify import (
    _build_html,
    _build_plain,
    make_notify_node,
    notify,
    send_digest_email,
)
from pm_job_agent.config.settings import Settings
from pm_job_agent.services.types import RankedJobDict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**overrides) -> Settings:
    """Return a Settings instance with email fields pre-filled for testing."""
    defaults = dict(
        gmail_sender="sender@gmail.com",
        gmail_app_password="test-app-password",
        notify_email="recipient@gmail.com",
        notify_top_n=10,
        default_llm_provider="stub",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _job(
    title="AI PM",
    company="Acme",
    location="Remote",
    score=0.4,
    url="https://example.com/job",
    job_id="test:1",
) -> RankedJobDict:
    return RankedJobDict(
        id=job_id,
        title=title,
        company=company,
        location=location,
        url=url,
        source="test",
        description_snippet="Some description",
        score=score,
    )


SAMPLE_JOBS = [_job(title=f"PM Role {i}", job_id=f"test:{i}", score=round(0.6 - i * 0.1, 1)) for i in range(5)]
SAMPLE_NEW_IDS = {j["id"] for j in SAMPLE_JOBS}
SAMPLE_DIGEST = "Strong match for AI-focused companies."
SAMPLE_PATH = "outputs/run_20260101_120000.csv"
ALL_JOB_COUNT = len(SAMPLE_JOBS)


# ---------------------------------------------------------------------------
# send_digest_email — SMTP interaction
# ---------------------------------------------------------------------------

class TestSendDigestEmail:
    def test_sends_via_smtp(self) -> None:
        settings = _settings()
        with patch("pm_job_agent.agents.notify.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server

            send_digest_email(SAMPLE_JOBS, ALL_JOB_COUNT, SAMPLE_DIGEST, SAMPLE_PATH, settings=settings)

        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("sender@gmail.com", "test-app-password")
        mock_server.sendmail.assert_called_once()

    def test_subject_contains_new_job_count(self) -> None:
        settings = _settings()
        captured_msg: list[str] = []
        with patch("pm_job_agent.agents.notify.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server
            mock_server.sendmail.side_effect = lambda f, t, msg: captured_msg.append(msg)

            send_digest_email(SAMPLE_JOBS, ALL_JOB_COUNT, SAMPLE_DIGEST, SAMPLE_PATH, settings=settings)

        assert captured_msg, "sendmail was not called"
        parsed = email_lib.message_from_string(captured_msg[0])
        decoded_subject = str(email_lib.header.make_header(email_lib.header.decode_header(parsed["Subject"])))
        assert "[pm-job-agent]" in decoded_subject
        assert "5 new role" in decoded_subject

    def test_subject_says_nothing_new_when_no_jobs(self) -> None:
        settings = _settings()
        captured_msg: list[str] = []
        with patch("pm_job_agent.agents.notify.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server
            mock_server.sendmail.side_effect = lambda f, t, msg: captured_msg.append(msg)

            send_digest_email([], ALL_JOB_COUNT, SAMPLE_DIGEST, SAMPLE_PATH, settings=settings)

        parsed = email_lib.message_from_string(captured_msg[0])
        decoded_subject = str(email_lib.header.make_header(email_lib.header.decode_header(parsed["Subject"])))
        assert "Nothing new today" in decoded_subject

    def test_uses_correct_smtp_credentials(self) -> None:
        settings = _settings(gmail_sender="other@gmail.com", gmail_app_password="secret-pw")
        with patch("pm_job_agent.agents.notify.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server

            send_digest_email([], ALL_JOB_COUNT, SAMPLE_DIGEST, SAMPLE_PATH, settings=settings)

        mock_server.login.assert_called_once_with("other@gmail.com", "secret-pw")


# ---------------------------------------------------------------------------
# notify node — skip conditions, filtering, and error handling
# ---------------------------------------------------------------------------

class TestNotifyNode:
    def test_skips_when_no_app_password(self, caplog) -> None:
        settings = _settings(gmail_app_password=None)
        state = {"ranked_jobs": SAMPLE_JOBS, "new_job_ids": list(SAMPLE_NEW_IDS),
                 "digest": SAMPLE_DIGEST, "output_path": SAMPLE_PATH}

        with patch("pm_job_agent.agents.notify.smtplib.SMTP") as mock_smtp_cls:
            result = notify(state, settings=settings)

        mock_smtp_cls.assert_not_called()
        assert result == {}

    def test_skips_when_sender_missing(self, caplog) -> None:
        settings = _settings(gmail_sender=None)
        state = {"ranked_jobs": SAMPLE_JOBS, "new_job_ids": list(SAMPLE_NEW_IDS),
                 "digest": SAMPLE_DIGEST, "output_path": SAMPLE_PATH}

        with patch("pm_job_agent.agents.notify.smtplib.SMTP") as mock_smtp_cls:
            result = notify(state, settings=settings)

        mock_smtp_cls.assert_not_called()
        assert result == {}

    def test_skips_when_recipient_missing(self, caplog) -> None:
        settings = _settings(notify_email=None)
        state = {"ranked_jobs": SAMPLE_JOBS, "new_job_ids": list(SAMPLE_NEW_IDS),
                 "digest": SAMPLE_DIGEST, "output_path": SAMPLE_PATH}

        with patch("pm_job_agent.agents.notify.smtplib.SMTP") as mock_smtp_cls:
            result = notify(state, settings=settings)

        mock_smtp_cls.assert_not_called()
        assert result == {}

    def test_returns_empty_dict_on_smtp_error(self) -> None:
        """SMTP failure must not raise — pipeline should complete normally."""
        settings = _settings()
        state = {"ranked_jobs": SAMPLE_JOBS, "new_job_ids": list(SAMPLE_NEW_IDS),
                 "digest": SAMPLE_DIGEST, "output_path": SAMPLE_PATH}

        with patch("pm_job_agent.agents.notify.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.side_effect = ConnectionRefusedError("SMTP unreachable")
            result = notify(state, settings=settings)

        assert result == {}

    def test_filters_to_new_jobs_only(self) -> None:
        """Only jobs whose ID is in new_job_ids should be passed to send_digest_email."""
        settings = _settings()
        new_job = _job(title="New Role", job_id="new:1")
        old_job = _job(title="Old Role", job_id="old:1")
        state = {
            "ranked_jobs": [new_job, old_job],
            "new_job_ids": ["new:1"],
            "digest": SAMPLE_DIGEST,
            "output_path": SAMPLE_PATH,
        }

        with patch("pm_job_agent.agents.notify.send_digest_email") as mock_send:
            notify(state, settings=settings)

        call_args = mock_send.call_args
        sent_new_jobs = call_args[0][0]
        assert len(sent_new_jobs) == 1
        assert sent_new_jobs[0]["id"] == "new:1"

    def test_sends_nothing_new_when_all_jobs_seen(self) -> None:
        """If new_job_ids is empty, send_digest_email is still called (nothing new message)."""
        settings = _settings()
        state = {
            "ranked_jobs": SAMPLE_JOBS,
            "new_job_ids": [],
            "digest": SAMPLE_DIGEST,
            "output_path": SAMPLE_PATH,
        }

        with patch("pm_job_agent.agents.notify.send_digest_email") as mock_send:
            notify(state, settings=settings)

        call_args = mock_send.call_args
        sent_new_jobs = call_args[0][0]
        assert sent_new_jobs == []

    def test_make_notify_node_returns_callable(self) -> None:
        settings = _settings(gmail_app_password=None)
        node = make_notify_node(settings)
        assert callable(node)

    def test_node_handles_empty_state_gracefully(self) -> None:
        """Node should not crash when state keys are missing."""
        settings = _settings(gmail_app_password=None)
        node = make_notify_node(settings)
        result = node({})
        assert result == {}


# ---------------------------------------------------------------------------
# HTML / plain-text builders
# ---------------------------------------------------------------------------

class TestBuildHtml:
    def test_contains_job_titles(self) -> None:
        # Only tier-eligible roles are listed; ensure at least one listed role appears.
        jobs = [
            _job(title="High", job_id="high:1", score=0.9),
            _job(title="Next", job_id="next:1", score=0.6),
            _job(title="Low", job_id="low:1", score=0.2),
        ]
        html_out = _build_html(
            jobs,
            len(jobs),
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=10,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "High" in html_out
        assert "Next" in html_out
        assert "Low" not in html_out

    def test_respects_top_n_limit(self) -> None:
        jobs = [_job(title=f"Role {i}", job_id=f"test:{i}", score=0.9) for i in range(10)]
        html = _build_html(
            jobs,
            len(jobs),
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "Role 0" in html
        assert "Role 2" in html
        assert "Role 3" not in html

    def test_contains_digest_text(self) -> None:
        html = _build_html(
            SAMPLE_JOBS,
            ALL_JOB_COUNT,
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=10,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert SAMPLE_DIGEST in html

    def test_contains_csv_path(self) -> None:
        html = _build_html(
            SAMPLE_JOBS,
            ALL_JOB_COUNT,
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=10,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert SAMPLE_PATH in html

    def test_job_urls_are_hyperlinks(self) -> None:
        html = _build_html(
            [_job(url="https://example.com/job1", score=0.9)],
            1,
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=10,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert 'href="https://example.com/job1"' in html

    def test_shows_nothing_new_message_when_empty(self) -> None:
        html = _build_html(
            [],
            ALL_JOB_COUNT,
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=10,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "No new roles found today" in html

    def test_renders_markdownish_digest_as_html(self) -> None:
        digest = "- One\n- Two\n\nThis is **bold**."
        html_out = _build_html(
            [_job(score=0.9)],
            1,
            digest,
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        # Digest's first sentence should appear; formatting is rendered safely.
        assert "One" in html_out
        assert "<strong>bold</strong>" in html_out

    def test_includes_sheet_link_when_configured(self) -> None:
        sheet_url = "https://docs.google.com/spreadsheets/d/abc123"
        html_out = _build_html(
            [_job(score=0.9)],
            1,
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url=sheet_url,
        )
        assert 'Click here for full list of roles' in html_out
        assert sheet_url in html_out

    def test_says_no_relevant_roles_when_all_new_below_thresholds(self) -> None:
        jobs = [_job(title="Low", job_id="low:1", score=0.2)]
        html_out = _build_html(
            jobs,
            1,
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "No new highly relevant roles found in this run" in html_out

    def test_does_not_include_table(self) -> None:
        html_out = _build_html(
            SAMPLE_JOBS,
            ALL_JOB_COUNT,
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "<table" not in html_out

    def test_summary_is_first_sentence_of_digest(self) -> None:
        digest = "First sentence. Second sentence."
        html_out = _build_html(
            [_job(score=0.9)],
            1,
            digest,
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        # Stats line should appear before the highlight sentence.
        assert html_out.index("New:") < html_out.index("First sentence.")
        assert "First sentence." in html_out
        assert "Second sentence." not in html_out

    def test_stats_line_includes_counts_names_and_remainder(self) -> None:
        jobs = [
            _job(title="High1", company="Co1", job_id="h1", score=0.90),
            _job(title="High2", company="Co2", job_id="h2", score=0.85),
            _job(title="Next1", company="Co3", job_id="n1", score=0.70),
        ]
        html_out = _build_html(
            jobs,
            len(jobs),
            "Highlight sentence.",
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "New: 3" in html_out
        assert "High-tier: 2" in html_out
        assert "High1 @ Co1" in html_out
        assert "High2 @ Co2" in html_out
        assert "Next-tier: 1" in html_out
        assert "Remainder: 0" in html_out

    def test_role_lines_include_freshness(self) -> None:
        job = _job(title="High1", company="Co1", job_id="h1", score=0.90)
        job["freshness_age_hours"] = 6.0
        job["source_posted_at"] = "6 hours ago"
        html_out = _build_html(
            [job],
            1,
            "Highlight sentence.",
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "6 hours ago" in html_out
        assert "~6h" in html_out


class TestBuildPlain:
    def test_contains_job_titles(self) -> None:
        jobs = [
            _job(title="High", job_id="high:1", score=0.9),
            _job(title="Next", job_id="next:1", score=0.6),
            _job(title="Low", job_id="low:1", score=0.2),
        ]
        plain = _build_plain(
            jobs,
            len(jobs),
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=10,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "High" in plain
        assert "Next" in plain
        assert "Low" not in plain

    def test_respects_top_n_limit(self) -> None:
        jobs = [_job(title=f"Role {i}", job_id=f"test:{i}", score=0.9) for i in range(10)]
        plain = _build_plain(
            jobs,
            len(jobs),
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "Role 0" in plain
        assert "Role 3" not in plain

    def test_contains_generate_command(self) -> None:
        plain = _build_plain(
            SAMPLE_JOBS,
            ALL_JOB_COUNT,
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=10,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "pm-job-agent generate" in plain
        assert SAMPLE_PATH in plain

    def test_shows_nothing_new_message_when_empty(self) -> None:
        plain = _build_plain(
            [],
            ALL_JOB_COUNT,
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=10,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "Nothing new today" in plain

    def test_includes_sheet_link_when_configured(self) -> None:
        sheet_url = "https://docs.google.com/spreadsheets/d/abc123"
        plain = _build_plain(
            [_job(score=0.9)],
            1,
            SAMPLE_DIGEST,
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url=sheet_url,
        )
        assert "Click here for full list of roles" in plain
        assert sheet_url in plain

    def test_summary_is_first_sentence_of_digest(self) -> None:
        digest = "First sentence. Second sentence."
        plain = _build_plain(
            [_job(score=0.9)],
            1,
            digest,
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert plain.index("New:") < plain.index("First sentence.")
        assert "First sentence." in plain
        assert "Second sentence." not in plain

    def test_stats_line_includes_counts_names_and_remainder(self) -> None:
        jobs = [
            _job(title="High1", company="Co1", job_id="h1", score=0.90),
            _job(title="High2", company="Co2", job_id="h2", score=0.85),
            _job(title="Next1", company="Co3", job_id="n1", score=0.70),
        ]
        plain = _build_plain(
            jobs,
            len(jobs),
            "Highlight sentence.",
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "New: 3" in plain
        assert "High-tier: 2" in plain
        assert "High1 @ Co1" in plain
        assert "High2 @ Co2" in plain
        assert "Next-tier: 1" in plain
        assert "Remainder: 0" in plain

    def test_role_lines_include_freshness(self) -> None:
        job = _job(title="High1", company="Co1", job_id="h1", score=0.90)
        job["freshness_age_hours"] = 6.0
        job["source_posted_at"] = "6 hours ago"
        plain = _build_plain(
            [job],
            1,
            "Highlight sentence.",
            SAMPLE_PATH,
            top_n=3,
            high_score_min=0.80,
            next_score_min=0.50,
            sheets_url="",
        )
        assert "6 hours ago" in plain
        assert "~6h" in plain

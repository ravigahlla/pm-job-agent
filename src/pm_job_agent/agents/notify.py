"""Send a formatted HTML email digest after each pipeline run via Gmail SMTP.

The email shows only jobs that are NEW this run (not seen in any previous run).
If no new jobs exist, a short "nothing new today" message is sent so you know
the pipeline ran successfully.

Skips silently if GMAIL_APP_PASSWORD is not configured — the pipeline always
completes regardless of notification status.

Gmail setup (one-time):
  1. Enable 2-Step Verification on your Google account.
  2. Generate an App Password at https://myaccount.google.com/apppasswords
  3. Add GMAIL_SENDER, GMAIL_APP_PASSWORD, and NOTIFY_EMAIL to .env.
"""

from __future__ import annotations

import html
import logging
import re
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from pm_job_agent.config.settings import Settings, get_settings
from pm_job_agent.graphs.state import CoreLoopState
from pm_job_agent.services.types import RankedJobDict

logger = logging.getLogger(__name__)

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


def send_digest_email(
    new_jobs: list[RankedJobDict],
    all_job_count: int,
    digest: str,
    output_path: str,
    *,
    settings: Settings,
) -> None:
    """Build and send the HTML digest email. Raises on SMTP errors."""
    if new_jobs:
        subject = (
            f"[pm-job-agent] {len(new_jobs)} new role{'s' if len(new_jobs) != 1 else ''} "
            f"\u2013 {date.today().isoformat()}"
        )
    else:
        subject = f"[pm-job-agent] Nothing new today \u2013 {date.today().isoformat()}"

    sheets_url = (
        f"https://docs.google.com/spreadsheets/d/{settings.google_sheets_id}"
        if settings.google_sheets_id
        else ""
    )
    html = _build_html(
        new_jobs,
        all_job_count,
        digest,
        output_path,
        top_n=settings.notify_top_n,
        high_score_min=settings.notify_high_score_min,
        next_score_min=settings.notify_next_score_min,
        sheets_url=sheets_url,
    )
    plain = _build_plain(
        new_jobs,
        all_job_count,
        digest,
        output_path,
        top_n=settings.notify_top_n,
        high_score_min=settings.notify_high_score_min,
        next_score_min=settings.notify_next_score_min,
        sheets_url=sheets_url,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.gmail_sender
    msg["To"] = settings.notify_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    password = settings.gmail_app_password.get_secret_value()
    with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.gmail_sender, password)
        server.sendmail(settings.gmail_sender, settings.notify_email, msg.as_string())

    logger.info(
        "Digest email sent to %s (%d new jobs, %d total).",
        settings.notify_email,
        len(new_jobs),
        all_job_count,
    )


def notify(state: CoreLoopState, *, settings: Settings) -> dict:
    """LangGraph node: send email digest if credentials are configured."""
    if not settings.gmail_app_password:
        logger.info(
            "GMAIL_APP_PASSWORD is not set — skipping email notification. "
            "Add it to .env to enable the digest email."
        )
        return {}

    if not settings.gmail_sender or not settings.notify_email:
        logger.warning(
            "GMAIL_APP_PASSWORD is set but GMAIL_SENDER or NOTIFY_EMAIL is missing — "
            "skipping email notification."
        )
        return {}

    all_ranked = state.get("ranked_jobs") or []
    new_job_ids = set(state.get("new_job_ids") or [])
    new_jobs = [j for j in all_ranked if j.get("id") in new_job_ids]

    digest = state.get("digest") or ""
    output_path = state.get("output_path") or ""

    try:
        send_digest_email(
            new_jobs,
            len(all_ranked),
            digest,
            output_path,
            settings=settings,
        )
    except Exception:
        # Notification failure must not crash the pipeline — the CSV is already written.
        logger.exception("Failed to send digest email — run completed normally.")

    return {}


def make_notify_node(settings: Settings):
    def _node(state: CoreLoopState) -> dict:
        return notify(state, settings=settings)

    return _node


# --- HTML / plain-text builders ---

def _build_html(
    new_jobs: list[RankedJobDict],
    all_job_count: int,
    digest: str,
    output_path: str,
    *,
    top_n: int,
    high_score_min: float,
    next_score_min: float,
    sheets_url: str,
) -> str:
    summary_sentence = _first_sentence(digest)
    highlights_section = _build_highlights_section_html(
        new_jobs,
        summary_sentence=summary_sentence,
        top_n=top_n,
        high_score_min=high_score_min,
        next_score_min=next_score_min,
    )
    tracker_section = (
        f'<p><a href="{html.escape(sheets_url)}">Click here for full list of roles</a></p>'
        if sheets_url
        else ""
    )
    nothing_new_section = (
        f'<p style="color:#666;">No new roles found today — '
        f"all {all_job_count} discovered job{'s' if all_job_count != 1 else ''} "
        f"were already seen in a previous run.</p>"
        if not new_jobs
        else ""
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         color: #1a1a1a; max-width: 780px; margin: 0 auto; padding: 24px; }}
  h2 {{ color: #111; margin-bottom: 4px; }}
  .digest {{ background: #f5f5f5; border-left: 3px solid #888;
            padding: 12px 16px; border-radius: 4px; }}
  .digest p {{ margin: 0 0 10px 0; }}
  .digest p:last-child {{ margin-bottom: 0; }}
  .digest ul {{ margin: 8px 0 0 18px; padding: 0; }}
  .score {{ font-weight: 600; text-align: center; }}
  a {{ color: #0066cc; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .footer {{ margin-top: 24px; font-size: 13px; color: #666; border-top: 1px solid #ddd;
             padding-top: 16px; }}
  code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 12px; }}
</style>
</head>
<body>
<h2>pm-job-agent &mdash; {date.today().isoformat()}</h2>
{highlights_section}
{tracker_section}
{nothing_new_section}
<div class="footer">
  <p>CSV saved to: <code>{output_path}</code></p>
  <p>To generate tailored documents, open the CSV, set <code>flagged</code> to <code>yes</code>
  for roles you want, then run:<br>
  <code>pm-job-agent generate {output_path}</code></p>
</div>
</body>
</html>"""


def _build_highlights_section_html(
    new_jobs: list[RankedJobDict],
    *,
    summary_sentence: str,
    top_n: int,
    high_score_min: float,
    next_score_min: float,
) -> str:
    high = [j for j in new_jobs if float(j.get("score", 0.0)) >= high_score_min]
    next_tier = [
        j
        for j in new_jobs
        if next_score_min <= float(j.get("score", 0.0)) < high_score_min
    ]

    stats_line = _build_stats_line(
        new_jobs,
        high=high,
        next_tier=next_tier,
        high_score_min=high_score_min,
        next_score_min=next_score_min,
    )

    section = [
        '<h3 style="margin:16px 0 6px 0;">New highlights</h3>',
        f'<p style="color:#333;"><strong>{html.escape(stats_line)}</strong></p>',
        f"<p>{_render_markdownish_to_html(summary_sentence)}</p>",
    ]

    if not new_jobs:
        return "\n".join(section)

    def _format_freshness(job: RankedJobDict) -> str:
        age = job.get("freshness_age_hours", None)
        source_posted_at = (job.get("source_posted_at") or "").strip()
        age_str = ""
        if isinstance(age, (int, float)) and age >= 0:
            if age < 48:
                age_str = f"~{int(round(age))}h"
            else:
                age_str = f"~{int(round(age / 24.0))}d"

        if age_str and source_posted_at and isinstance(age, (int, float)) and age < 48:
            return f"{source_posted_at} ({age_str})"
        if age_str:
            return age_str
        if source_posted_at:
            return source_posted_at
        return "freshness unknown"

    def _role_list(items: list[RankedJobDict]) -> str:
        parts: list[str] = []
        for j in items[:top_n]:
            url = html.escape(j.get("url", "") or "")
            title = html.escape(j.get("title", "") or "")
            company = html.escape(j.get("company", "") or "")
            location = html.escape(j.get("location", "") or "") or "(location not specified)"
            score = float(j.get("score", 0.0))
            freshness = html.escape(_format_freshness(j))
            role = f'<a href="{url}"><strong>{title}</strong></a>' if url else f"<strong>{title}</strong>"
            parts.append(
                "<li>"
                f"{role} — {company} — {html.escape(location)} — {score:.2f} — {freshness}"
                "</li>"
            )
        return ("<ul>" + "".join(parts) + "</ul>") if parts else "<p style=\"color:#666;\">(none)</p>"

    if high:
        section.append(
            f"<p><strong>Highly relevant roles</strong> (score ≥ {high_score_min:.2f}):</p>"
        )
        section.append(_role_list(high))
    if next_tier:
        section.append(
            f"<p><strong>Next tier roles</strong> (score {next_score_min:.2f}–{high_score_min:.2f}):</p>"
        )
        section.append(_role_list(next_tier))
    if not high and not next_tier:
        section.append(
            f"<p><strong>No new highly relevant roles found in this run.</strong> "
            f"({len(new_jobs)} new total; below {next_score_min:.2f} score.)</p>"
        )
    return "\n".join(section)


def _build_plain(
    new_jobs: list[RankedJobDict],
    all_job_count: int,
    digest: str,
    output_path: str,
    *,
    top_n: int,
    high_score_min: float,
    next_score_min: float,
    sheets_url: str,
) -> str:
    summary_sentence = _first_sentence(digest)
    high = [j for j in new_jobs if float(j.get("score", 0.0)) >= high_score_min]
    next_tier = [
        j
        for j in new_jobs
        if next_score_min <= float(j.get("score", 0.0)) < high_score_min
    ]
    stats_line = _build_stats_line(
        new_jobs,
        high=high,
        next_tier=next_tier,
        high_score_min=high_score_min,
        next_score_min=next_score_min,
    )
    lines = [
        f"pm-job-agent — {date.today().isoformat()}",
        "",
        "New highlights:",
        stats_line,
        summary_sentence,
        "",
    ]

    lines += _build_tier_lists_plain(
        new_jobs,
        top_n=top_n,
        high_score_min=high_score_min,
        next_score_min=next_score_min,
    )

    if sheets_url:
        lines += ["", f"Click here for full list of roles: {sheets_url}"]

    if not new_jobs:
        lines += [
            "",
            f"Nothing new today — all {all_job_count} discovered jobs were already seen.",
        ]

    lines += [
        "",
        f"CSV: {output_path}",
        "To generate documents: set flagged=yes in the CSV, then run:",
        f"  pm-job-agent generate {output_path}",
    ]
    return "\n".join(lines)


def _build_tier_lists_plain(
    new_jobs: list[RankedJobDict],
    *,
    top_n: int,
    high_score_min: float,
    next_score_min: float,
) -> list[str]:
    high = [j for j in new_jobs if float(j.get("score", 0.0)) >= high_score_min]
    next_tier = [
        j
        for j in new_jobs
        if next_score_min <= float(j.get("score", 0.0)) < high_score_min
    ]

    def _format_freshness(job: RankedJobDict) -> str:
        age = job.get("freshness_age_hours", None)
        source_posted_at = (job.get("source_posted_at") or "").strip()
        age_str = ""
        if isinstance(age, (int, float)) and age >= 0:
            if age < 48:
                age_str = f"~{int(round(age))}h"
            else:
                age_str = f"~{int(round(age / 24.0))}d"

        if age_str and source_posted_at and isinstance(age, (int, float)) and age < 48:
            return f"{source_posted_at} ({age_str})"
        if age_str:
            return age_str
        if source_posted_at:
            return source_posted_at
        return "freshness unknown"

    def _fmt(j: RankedJobDict) -> str:
        location = (j.get("location") or "").strip() or "(location not specified)"
        return (
            f"- {j.get('title','')} — {j.get('company','')} — {location} — "
            f"{float(j.get('score',0.0)):.2f} — {_format_freshness(j)}"
        )

    out: list[str] = []
    out.append(f"Highly relevant roles (score ≥ {high_score_min:.2f}):")
    if high:
        out.extend([_fmt(j) for j in high[:top_n]])
    else:
        out.append("- (none)")
    out.append("")
    out.append(f"Next tier roles (score {next_score_min:.2f}–{high_score_min:.2f}):")
    if next_tier:
        out.extend([_fmt(j) for j in next_tier[:top_n]])
    else:
        out.append("- (none)")

    if new_jobs and not high and not next_tier:
        out += ["", "No new highly relevant roles found in this run."]

    return out


def _build_stats_line(
    new_jobs: list[RankedJobDict],
    *,
    high: list[RankedJobDict],
    next_tier: list[RankedJobDict],
    high_score_min: float,
    next_score_min: float,
    max_names: int = 3,
) -> str:
    new_count = len(new_jobs)
    high_count = len(high)
    next_count = len(next_tier)
    remainder = max(0, new_count - high_count - next_count)

    if new_count == 0:
        return "New: 0."

    names = []
    for j in high[:max_names]:
        title = (j.get("title") or "").strip()
        company = (j.get("company") or "").strip()
        if title and company:
            names.append(f"{title} @ {company}")
        elif title:
            names.append(title)
        if len(names) >= max_names:
            break

    name_block = f" ({'; '.join(names)})" if names else ""
    return (
        f"New: {new_count}. "
        f"High-tier: {high_count}{name_block} (≥ {high_score_min:.2f}). "
        f"Next-tier: {next_count} ({next_score_min:.2f}–{high_score_min:.2f}). "
        f"Remainder: {remainder}."
    )


_FIRST_SENTENCE_RE = re.compile(r"^(.+?[.!?])(\s|$)", flags=re.DOTALL)


def _first_sentence(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    match = _FIRST_SENTENCE_RE.match(raw)
    return (match.group(1).strip() if match else raw).strip()


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _render_markdownish_to_html(text: str) -> str:
    """Render a small safe subset of markdown-ish text into HTML.

    Supports:
      - paragraphs separated by blank lines
      - bullet lists using '- ' prefixes
      - **bold**

    Always escapes HTML first (no raw HTML passthrough).
    """
    raw = (text or "").strip()
    if not raw:
        return "<p>(no digest)</p>"

    escaped = html.escape(raw)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)

    lines = escaped.splitlines()
    blocks: list[str] = []
    buf: list[str] = []

    def flush_buf() -> None:
        nonlocal buf
        if not buf:
            return
        blocks.append("<p>" + "<br>".join(buf) + "</p>")
        buf = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            flush_buf()
            i += 1
            continue

        if line.startswith("- "):
            flush_buf()
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append("<li>" + lines[i].strip()[2:] + "</li>")
                i += 1
            blocks.append("<ul>" + "".join(items) + "</ul>")
            continue

        buf.append(line)
        i += 1

    flush_buf()
    return "\n".join(blocks)

"""Send a formatted HTML email digest after each pipeline run via Gmail SMTP.

Skips silently if GMAIL_APP_PASSWORD is not configured — the pipeline always
completes regardless of notification status.

Gmail setup (one-time):
  1. Enable 2-Step Verification on your Google account.
  2. Generate an App Password at https://myaccount.google.com/apppasswords
  3. Add GMAIL_SENDER, GMAIL_APP_PASSWORD, and NOTIFY_EMAIL to .env.
"""

from __future__ import annotations

import logging
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
    ranked_jobs: list[RankedJobDict],
    digest: str,
    output_path: str,
    *,
    settings: Settings,
) -> None:
    """Build and send the HTML digest email. Raises on SMTP errors."""
    subject = (
        f"[pm-job-agent] {len(ranked_jobs)} roles found \u2013 {date.today().isoformat()}"
    )
    html = _build_html(ranked_jobs, digest, output_path, settings.notify_top_n)
    plain = _build_plain(ranked_jobs, digest, output_path, settings.notify_top_n)

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

    logger.info("Digest email sent to %s (%d jobs).", settings.notify_email, len(ranked_jobs))


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

    ranked_jobs = state.get("ranked_jobs") or []
    digest = state.get("digest") or ""
    output_path = state.get("output_path") or ""

    try:
        send_digest_email(ranked_jobs, digest, output_path, settings=settings)
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
    ranked_jobs: list[RankedJobDict],
    digest: str,
    output_path: str,
    top_n: int,
) -> str:
    rows = _job_rows_html(ranked_jobs[:top_n])
    total = len(ranked_jobs)
    shown = min(top_n, total)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         color: #1a1a1a; max-width: 780px; margin: 0 auto; padding: 24px; }}
  h2 {{ color: #111; margin-bottom: 4px; }}
  p.digest {{ background: #f5f5f5; border-left: 3px solid #888;
              padding: 12px 16px; border-radius: 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 16px; font-size: 14px; }}
  th {{ background: #222; color: #fff; text-align: left; padding: 8px 10px; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #e5e5e5; vertical-align: top; }}
  tr:hover td {{ background: #fafafa; }}
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
<p class="digest">{digest}</p>
<p>Showing top {shown} of {total} scored roles:</p>
<table>
  <thead>
    <tr>
      <th>#</th><th>Score</th><th>Role</th><th>Company</th><th>Location</th>
    </tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>
<div class="footer">
  <p>CSV saved to: <code>{output_path}</code></p>
  <p>To generate tailored documents, open the CSV, set <code>flagged</code> to <code>yes</code>
  for roles you want, then run:<br>
  <code>pm-job-agent generate {output_path}</code></p>
</div>
</body>
</html>"""


def _job_rows_html(jobs: list[RankedJobDict]) -> str:
    rows = []
    for i, job in enumerate(jobs, start=1):
        url = job.get("url", "")
        title = job.get("title", "")
        link = f'<a href="{url}">{title}</a>' if url else title
        rows.append(
            f"    <tr>"
            f'<td>{i}</td>'
            f'<td class="score">{job.get("score", 0):.1f}</td>'
            f"<td>{link}</td>"
            f'<td>{job.get("company", "")}</td>'
            f'<td>{job.get("location", "")}</td>'
            f"</tr>"
        )
    return "\n".join(rows)


def _build_plain(
    ranked_jobs: list[RankedJobDict],
    digest: str,
    output_path: str,
    top_n: int,
) -> str:
    lines = [
        f"pm-job-agent — {date.today().isoformat()}",
        "",
        digest,
        "",
        f"Top {min(top_n, len(ranked_jobs))} of {len(ranked_jobs)} roles:",
        "-" * 60,
    ]
    for i, job in enumerate(ranked_jobs[:top_n], start=1):
        lines.append(
            f"{i:>2}. [{job.get('score', 0):.1f}] {job.get('title', '')} "
            f"@ {job.get('company', '')} — {job.get('location', '')}"
        )
        if job.get("url"):
            lines.append(f"     {job['url']}")
    lines += [
        "",
        f"CSV: {output_path}",
        f"To generate documents: set flagged=yes in the CSV, then run:",
        f"  pm-job-agent generate {output_path}",
    ]
    return "\n".join(lines)

"""Google Sheets integration for the cross-run job tracker.

Uses a service account for authentication — no browser interaction required,
so this works headlessly in GitHub Actions as well as locally.

Setup (one-time):
  1. Create a Google Cloud project and enable the Google Sheets API.
  2. Create a service account and download its JSON key to private/service_account.json.
  3. Share your tracking Sheet with the service account's client_email (Editor access).
  4. Set GOOGLE_SHEETS_ID in .env to the Sheet ID from the URL.

Sheet columns written by this client:
  job_id | title | company | location | url | score | source | discovered_date
  | source_posted_at | new | status | notes | resume_note | cover_letter | score_rationale

  - ``discovered_date`` is the date this pipeline first appended the row (ISO), not the
    employer's original post date. Use ``source_posted_at`` when the job source provides it.
  - Columns up to `new` are populated on append; never overwritten on re-sync.
  - `status` and `notes` are yours to edit — the pipeline never touches them.
  - `resume_note` and `cover_letter` are reserved for the generate command (future).
  - `score_rationale` is populated by the scoring agent.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from pm_job_agent.services.types import RankedJobDict

logger = logging.getLogger(__name__)

# Columns written on initial append (order determines column position in the Sheet).
_SHEET_COLUMNS = [
    "job_id",
    "title",
    "company",
    "location",
    "url",
    "score",
    "source",
    "discovered_date",
    "source_posted_at",
    "new",
    "status",
    "notes",
    "resume_note",
    "cover_letter",
    "score_rationale",
]

# Scopes required for reading and writing Sheets.
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]


class SheetsError(Exception):
    """Raised when the Sheets client encounters an unrecoverable error."""


class SheetsClient:
    """Read and append rows to a Google Sheet using a service account."""

    def __init__(self, sheet_id: str, service_account_path: Path) -> None:
        """
        Args:
            sheet_id: The Google Sheet ID (the long alphanumeric string in the URL).
            service_account_path: Path to the service account JSON key file.

        Raises:
            SheetsError: If the credentials file is missing or authentication fails.
        """
        if not service_account_path.exists():
            raise SheetsError(
                f"Service account file not found: {service_account_path}. "
                "See README 'Google Sheets setup' for instructions."
            )

        try:
            creds = Credentials.from_service_account_file(
                str(service_account_path), scopes=_SCOPES
            )
            gc = gspread.authorize(creds)
            self._sheet = gc.open_by_key(sheet_id).sheet1
        except gspread.exceptions.APIError as exc:
            raise SheetsError(f"Google Sheets API error during auth: {exc}") from exc
        except Exception as exc:
            raise SheetsError(f"Failed to open Sheet '{sheet_id}': {exc}") from exc

    def get_existing_ids(self) -> set[str]:
        """Return the set of job_ids already present in the Sheet.

        Reads only the first column (job_id) to minimise API quota usage.
        Returns an empty set if the Sheet is blank or has only a header row.
        """
        try:
            values = self._sheet.col_values(1)  # column A = job_id
        except gspread.exceptions.APIError as exc:
            raise SheetsError(f"Failed to read existing job IDs: {exc}") from exc

        # Skip the header row if present.
        if values and values[0] == "job_id":
            values = values[1:]

        return set(filter(None, values))

    def append_jobs(
        self,
        jobs: list[RankedJobDict],
        new_job_ids: set[str] | None = None,
        existing_ids: set[str] | None = None,
    ) -> int:
        """Append jobs to the Sheet, skipping any already present by job_id.

        Args:
            jobs: Ranked jobs from the pipeline.
            new_job_ids: IDs flagged as new by the deduplicate node (for the `new` column).
            existing_ids: Pre-fetched set of IDs already in the Sheet. If None,
                          get_existing_ids() is called automatically.

        Returns:
            Number of rows actually appended.

        Raises:
            SheetsError: On any API failure.
        """
        if existing_ids is None:
            existing_ids = self.get_existing_ids()

        new_job_ids = new_job_ids or set()
        today = date.today().isoformat()

        rows_to_append = []
        for job in jobs:
            job_id = job.get("id", "")
            if not job_id or job_id in existing_ids:
                continue

            rows_to_append.append([
                job_id,
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("url", ""),
                job.get("score", ""),
                job.get("source", ""),
                today,
                job.get("source_posted_at", ""),
                "yes" if job_id in new_job_ids else "",
                "",  # status — user fills in
                "",  # notes — user fills in
                "",  # resume_note — generate command fills in
                "",  # cover_letter — generate command fills in
                job.get("score_rationale", ""),
            ])

        if not rows_to_append:
            logger.info("No new jobs to append to Sheet (all already present).")
            return 0

        try:
            # Write header row if the sheet is empty.
            if not existing_ids and self._sheet.row_count == 0 or not self._is_header_present():
                self._sheet.append_row(_SHEET_COLUMNS)

            self._sheet.append_rows(rows_to_append, value_input_option="RAW")
        except gspread.exceptions.APIError as exc:
            raise SheetsError(f"Failed to append rows to Sheet: {exc}") from exc

        logger.info("Appended %d job(s) to Google Sheet.", len(rows_to_append))
        return len(rows_to_append)

    def _is_header_present(self) -> bool:
        """Return True if the first row looks like the expected header."""
        try:
            first_row = self._sheet.row_values(1)
            return first_row == _SHEET_COLUMNS
        except gspread.exceptions.APIError:
            return False

# pm-job-agent

Multi-agent job hunting system: LangGraph orchestration, job discovery (Greenhouse + LinkedIn via Apify), scoring against your background, tailored documents on demand, and CSV export. See `.cursorrules` for goals and phases.

## Contents

- [Architecture](#architecture)
- [Setup](#setup)
  - [Virtual environment](#virtual-environment-recommended)
  - [Bootstrap script](#bootstrap-script-macos--linux--wsl)
  - [After git clone](#after-git-clone-or-git-pull-on-a-new-machine)
  - [Configuration](#configuration)
- [Usage](#usage)
  - [Run the pipeline](#run-the-pipeline)
  - [Generate documents for flagged roles](#generate-documents-for-flagged-roles)
- [Layout](#layout)
- [Automated daily runs](#automated-daily-runs)
- [Tests](#tests)
- [Docker](#docker)
- [Roadmap](#roadmap)

---

**What runs today:** A two-step workflow:

1. **`pm-job-agent run`** — discovers jobs from Greenhouse boards and LinkedIn (via Apify), scores each role with LLM semantic scoring (keyword pre-filter + scoring model call against your career context), runs an LLM digest, writes a timestamped CSV to `outputs/`, syncs new jobs to a Google Sheet tracker (if configured), and sends an HTML email digest (if Gmail credentials are configured). Document generation does **not** happen automatically.
2. **`pm-job-agent generate <csv>`** — reads a previous run CSV, generates a tailored resume note and cover letter opening for every row you flagged `yes` in the `flagged` column, and writes the results back into the same file.

LLM providers (Anthropic, OpenAI, Gemini, Ollama) are fully wired and swap via `DEFAULT_LLM_PROVIDER` in `.env` — no code changes needed.

**Not in code yet:** Slack channel ingestion, Slack notifications, additional job sources (YCombinator, TrueUp, Indeed), predictive company intelligence (funding signals → proactive outreach).

## Architecture

```mermaid
flowchart TB
  subgraph prep [You_prepare]
    writeContext[Update_private_career_context]
    writeEnv[Set_keys_paths_in_env]
  end

  subgraph run [pm-job-agent_run]
    loadBg[Load_background_into_state]
    gather[Discover_jobs_Greenhouse_LinkedIn]
    rank[Score_each_role_vs_you]
    dedup[Deduplicate_vs_seen_jobs]
    digest[LLM_digest]
    persist[Write_CSV_new_col_update_seen_jobs]
    syncSheets[Sync_new_jobs_to_Google_Sheet]
    notifyEmail["Email_new_roles_only"]
  end

  subgraph review [You_review]
    openCSV[Open_CSV_set_flagged_yes]
  end

  subgraph generate [pm-job-agent_generate_csv]
    readFlagged[Read_flagged_rows]
    genDocs[LLM_resume_note_cover_letter]
    writeBack[Write_back_to_same_CSV]
  end

  writeContext --> writeEnv
  writeEnv --> loadBg
  loadBg --> gather
  gather --> rank
  rank --> dedup
  dedup --> digest
  digest --> persist
  persist --> syncSheets
  syncSheets --> notifyEmail
  notifyEmail --> openCSV
  openCSV --> readFlagged
  readFlagged --> genDocs
  genDocs --> writeBack
```

## Setup

### Virtual environment (recommended)

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows (cmd): .venv\Scripts\activate.bat
pip install --upgrade pip
pip install -e ".[dev]"
```

`.venv/` is gitignored. Deactivate with `deactivate` when finished.

### Bootstrap script (macOS / Linux / WSL)

```bash
chmod +x scripts/bootstrap.sh   # first time only, if needed
./scripts/bootstrap.sh
source .venv/bin/activate
```

This creates `.venv` if missing, upgrades `pip`, runs `pip install -e ".[dev]"`, and copies `.env.example` → `.env` only when `.env` does not exist (never overwrites).

### After `git clone` or `git pull` on a new machine

**In the remote (GitHub):** source code, `pyproject.toml`, `scripts/bootstrap.sh`, `.env.example`, `Dockerfile`, tests, README.

**Not in the remote (gitignored):** recreate or copy these yourself.

| Path / item | What to do |
|-------------|------------|
| `private/` | Not in Git. Three files matter: `agent-context.md` (career context for scoring/generation), `search_profile.yaml` (keywords, board tokens, LinkedIn queries), and `scoring_criteria.md` (optional personalised scoring rubric injected into the LLM system prompt). Without `agent-context.md` and `search_profile.yaml`, discovery returns zero jobs but the run does not crash. |
| `.env` | Not in Git. Run `./scripts/bootstrap.sh` to create from `.env.example`, then fill in real keys. |
| `.venv/` | Not in Git. Run `./scripts/bootstrap.sh` or `pip install -e ".[dev]"` manually. |
| `outputs/` | Gitignored. Created automatically on first run. |

**Order after clone:**

1. Install Python 3.9+ and Git.
2. `cd` into the repo root.
3. `./scripts/bootstrap.sh`
4. Restore `private/` and fill in `.env` with real secrets.
5. `source .venv/bin/activate` and run `pytest`.

### Configuration

1. **Environment variables** — copy the template and edit locally:

   ```bash
   cp .env.example .env
   ```

2. **LLM provider** — install the SDK and set the key in `.env`:

   | Provider | Install | `.env` keys |
   |----------|---------|-------------|
   | Anthropic | `pip install -e ".[anthropic]"` | `ANTHROPIC_API_KEY`, optionally `ANTHROPIC_MODEL` |
   | OpenAI | `pip install -e ".[openai]"` | `OPENAI_API_KEY`, optionally `OPENAI_MODEL` |
   | Gemini | `pip install -e ".[gemini]"` | `GOOGLE_API_KEY`, optionally `GEMINI_MODEL` |
   | Ollama (local) | `pip install -e ".[ollama]"` | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
   | All providers | `pip install -e ".[llm-all]"` | — |

   Set `DEFAULT_LLM_PROVIDER=anthropic` (or your chosen provider) in `.env`. The default is `stub` — makes no API calls, used for CI and runs without keys.

3. **LinkedIn via Apify** — get a free API token at [console.apify.com/account/integrations](https://console.apify.com/account/integrations) and add it to `.env`:

   ```
   APIFY_API_TOKEN=apify_api_xxxxxxxxxxxx
   ```

   Without this key, LinkedIn discovery is silently skipped and Greenhouse runs normally.

4. **Email digest (optional)** — after each run, the pipeline can send a formatted HTML email with the top-N scored jobs and the LLM digest summary. Requires a Gmail App Password (not your account password):

   1. Enable 2-Step Verification on your Google account.
   2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) and create an App Password for "Mail".
   3. Add to `.env`:

   ```
   GMAIL_SENDER=you@gmail.com
   GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
   NOTIFY_EMAIL=you@gmail.com
   NOTIFY_TOP_N=20
   ```

   Without these keys, the notify step is silently skipped — the run completes normally and only the CSV is written.

5. **Google Sheets tracker (optional)** — after each run, new jobs are appended to a single persistent Google Sheet. This is your cross-run tracker: sort by score, update `status` (applied / interested / skipped), add notes. The pipeline never overwrites your edits.

   **One-time setup:**

   1. Go to [console.cloud.google.com](https://console.cloud.google.com), create a project, and enable the **Google Sheets API**.
   2. Under **IAM & Admin → Service Accounts**, create a service account. Under its **Keys** tab, add a key → JSON. Save the downloaded file as `private/service_account.json` (gitignored).
   3. Create a blank Google Sheet. Copy its ID from the URL — the long alphanumeric string between `/d/` and `/edit`.
   4. Share the Sheet with the service account's `client_email` (found in the JSON key file) — give it **Editor** access.
   5. Add to `.env`:

   ```
   GOOGLE_SHEETS_ID=your_sheet_id_here
   # GOOGLE_SERVICE_ACCOUNT_PATH defaults to private/service_account.json
   ```

   **Sheet columns written by the pipeline:**

   | Column | Set by |
   |--------|--------|
   | `job_id`, `title`, `company`, `location`, `url`, `score`, `source`, `discovered_date`, `new` | Pipeline on append (never overwritten) |
   | `status`, `notes` | You — pipeline never touches these |
   | `resume_note`, `cover_letter` | Reserved for `pm-job-agent generate` (future) |

   Without these settings, the `sync_sheets` step is silently skipped — the run completes normally with only the CSV written.

   **For GitHub Actions:** add `GOOGLE_SHEETS_ID` and `GOOGLE_SERVICE_ACCOUNT_JSON` (full JSON content of the key file) as repository secrets.

6. **Career context** — add or edit `private/agent-context.md` (gitignored). Set `AGENT_CONTEXT_PATH` in `.env` if you want a different path.

6. **Search profile** — edit `private/search_profile.yaml`:

   ```yaml
   target_titles:
     - "Product Manager"
     - "Senior PM"

   include_keywords:
     - "AI"
     - "LLM"

   exclude_keywords:
     - "Intern"

   greenhouse_board_tokens:
     - anthropic
     - linear

   linkedin_search_queries:
     - "AI Product Manager"
     - "Senior PM AI"
   ```

   `greenhouse_board_tokens` are the slugs at the end of `boards.greenhouse.io/<token>` URLs. `linkedin_search_queries` are sent directly to LinkedIn Jobs search — be specific for better results. Without this file, discovery returns zero jobs.

## Usage

### Run the pipeline

```bash
pm-job-agent run
```

Runs discovery (Greenhouse + LinkedIn) → scoring → digest → CSV → email. Produces `outputs/run_YYYYMMDD_HHMMSS.csv` with a `flagged` column (empty by default). If `GMAIL_APP_PASSWORD` is set, sends an HTML email digest to `NOTIFY_EMAIL` with the top `NOTIFY_TOP_N` scored roles.

```bash
pm-job-agent run --json   # print full graph state as JSON (includes agent_context — treat as sensitive)
```

### Generate documents for flagged roles

Open the CSV, set `flagged = yes` for the roles you want to apply to, then:

```bash
pm-job-agent generate outputs/run_YYYYMMDD_HHMMSS.csv
```

Reads every `flagged = yes` row, calls the LLM for a tailored resume note and cover letter opening for each, and writes the results back into the same CSV. Unflagged rows are untouched.

### Evaluate and refine scoring quality

The LLM scorer is only as good as the rubric in `private/scoring_criteria.md`. Use this workflow to spot where it's over- or under-scoring and tighten it:

**Step 1 — Sample jobs across score buckets**

```bash
python scripts/sample_for_review.py          # 3 jobs per bucket (~12 total)
python scripts/sample_for_review.py --n 5    # larger sample
python scripts/sample_for_review.py --seed 42  # reproducible sample
```

Pools all `outputs/run_*.csv` files, stratifies into STRONG / PROMISING / BORDERLINE / WEAK, prints each job with its score and rationale, and writes `private/sample_for_review.csv`.

**Step 2 — Fill in your scores**

Open `private/sample_for_review.csv` and fill in `your_score` (1–5) and `your_notes` for each job. Look for patterns where the LLM consistently diverges from your judgment.

**Step 3 — Update the rubric**

Edit `private/scoring_criteria.md` to correct the patterns you found (e.g. "downgrade pre-Series A roles", "ignore titles without AI scope").

**Step 4 — Re-score the Sheet**

```bash
python scripts/rescore_sheet.py --write
```

Re-evaluates all Sheet rows with the updated rubric and writes back `score` and `score_rationale`.

### Local development (no API keys required)

Use the `--provider` flag to override the LLM provider for a single command without editing `.env`. This is the recommended workflow for local testing:

```bash
ollama pull llama3.2          # one-time model download (~2 GB); skip if already pulled
pm-job-agent run --provider ollama
pm-job-agent generate outputs/run_*.csv --provider ollama
```

Requires [Ollama](https://ollama.com) installed and running (`ollama serve`). `llama3.2` produces reliable structured JSON output and is the recommended model for scoring. All other settings (search profile, output directory, Google Sheets, email digest) are unaffected by `--provider`.

`--provider` accepts any configured provider: `stub | anthropic | openai | gemini | ollama`. `stub` is useful for smoke-testing the pipeline shape without any LLM calls.

## Layout

| Path | Role |
|------|------|
| `src/pm_job_agent/` | Application package (`config`, `models`, `integrations`, `agents`, `graphs`, `services`, `cli`) |
| `tests/unit/` | Fast tests, mocked HTTP and LLM calls |
| `scripts/` | One-off local scripts |
| `private/` | **Local only** — career context, search profile |
| `outputs/` | **Gitignored** — timestamped CSV run files |

Inside `src/pm_job_agent/`:

| Path | Role |
|------|------|
| `config/` | `Settings` from `.env`; `SearchProfile` loaded from `private/search_profile.yaml` |
| `agents/` | Pipeline nodes: `context`, `discovery`, `scoring`, `deduplicate`, `digest`, `persist`, `sync_sheets`, `notify`, `generation` |
| `graphs/` | LangGraph compile (`build_core_loop_graph`) |
| `models/` | `LLMClient` protocol, `StubLLM`, `get_llm_client()` factory; `providers/` holds Anthropic, OpenAI, Gemini, Ollama |
| `services/` | Shared types (`JobDict`, `RankedJobDict`, `DocumentDict`) and `redact_pii()` |
| `integrations/` | `greenhouse.py`: Greenhouse board client. `linkedin.py`: LinkedIn via Apify Actor. `sheets.py`: Google Sheets tracker |
| `cli/` | `main.py` (subcommands: `run`, `generate`); `generate_cmd.py` (on-demand generation logic) |

## Automated daily runs

The pipeline runs automatically on weekday mornings via GitHub Actions (`.github/workflows/daily_run.yml`). The cron fires at a time chosen to avoid Anthropic peak-demand windows.

**Repository secrets required** (Settings → Secrets and variables → Actions):

| Secret | What it holds |
|--------|---------------|
| `AGENT_CONTEXT_MD` | Contents of `private/agent-context.md` |
| `SCORING_CRITERIA_MD` | Contents of `private/scoring_criteria.md` (optional; omit if not using personalised scoring criteria) |
| `SEARCH_PROFILE_YAML` | Contents of `private/search_profile.yaml` |
| `ANTHROPIC_API_KEY` | LLM provider key |
| `APIFY_API_TOKEN` | LinkedIn scraping |
| `GMAIL_APP_PASSWORD` | Gmail app password for digest email |
| `GMAIL_SENDER` | Sender address |
| `NOTIFY_EMAIL` | Recipient address |

**Optional secrets (Google Sheets tracker):**

| Secret | What it holds |
|--------|---------------|
| `GOOGLE_SHEETS_ID` | Sheet ID from the URL — enables cross-run tracker |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full contents of `private/service_account.json` |

`private/seen_jobs.json` is persisted between runs via `actions/cache` keyed on the day's date. This is what prevents the same jobs from appearing in the digest every day.

To trigger a manual run: Actions tab → `Daily PM Job Agent Run` → `Run workflow`.

## Tests

```bash
pytest
```

## Docker

```bash
docker build -t pm-job-agent .
```

The build context excludes `private/`, `.env`, and virtualenvs via `.dockerignore`.

## Roadmap

```mermaid
flowchart LR
  p1["Phase 1\nCore Loop\n✓ Shipped Mar 27–31 2026"]
  p2["Phase 2\nSignal Quality\n← Next"]
  p3["Phase 3\nIntelligence Layer"]
  p4["Phase 4\nScale and Ops"]

  p1 --> p2 --> p3 --> p4

  p1 --- s1["Greenhouse + LinkedIn discovery\nLLM semantic scoring + personalised criteria\nCheap scoring model config\nLLM digest\nCSV + email digest\nDeduplication\nGoogle Sheets tracker\nGitHub Actions cron\nOn-demand document generation"]

  p2 --- s2["More sources: YC, TrueUp, Indeed\nAuto-verify Greenhouse tokens\nEval framework improvements"]

  p3 --- s3["Explainability: why a role scored highly\nApplication memory + outcome tracking\nPredictive company intelligence\nFunding signals → proactive outreach"]

  p4 --- s4["Slack channel ingestion\nStreamlit local web UI\nPython 3.11+ upgrade\nSheets UI improvements"]
```

### Shipped

**Phase 1 — Core Loop** _(Mar 27–30 2026)_
Scaffold → Greenhouse discovery → keyword scoring → real LLM providers → on-demand document generation → LinkedIn/Apify scraping → cross-run deduplication → email digest → GitHub Actions cron → Google Sheets tracker.

**`feature/scoring-v2`** _(Mar 31 2026)_
See entry below.

---

### Next up — three branches

**`feature/scoring-v2`** ✓ Shipped Mar 31 2026
Replaced keyword scoring with LLM semantic scoring (keyword pre-filter + per-job LLM call against `agent-context.md`). Added `SCORING_LLM_PROVIDER` / `SCORING_MODEL` for model tiering, `SCORING_CRITERIA_PATH` to inject a personalised rubric into the system prompt, `score_rationale` field in CSV and Sheet, `--provider` CLI flag for local Ollama testing, `scripts/eval_scoring.py` for oracle-based quality validation, and `scripts/rescore_sheet.py` to back-fill v2 scores on existing Sheet rows.

**Quality validation (Mar 31 2026):** Ran `eval_scoring.py` against today's 191-job run (20-job oracle sample): MAE 0.189, Spearman 0.621. Scoring model is directionally correct and identifies domain/seniority gaps accurately; slight conservative bias (~0.19 below oracle) expected given cheaper scoring model. Pre-filter correctly drops non-AI-adjacent roles. Ran `rescore_sheet.py --write` against all 244 historical Sheet rows: average score rose from 0.139 (keyword noise) to 0.307 (semantic), 87 large changes (>0.30). Notable rescores: `Principal PM, AI @ Webflow` 0.40 → 0.82, `Product Manager, Subscription & Payments @ Webflow` 0.40 → 0.72.

**`feature/sourcing-v2`** _(depends on scoring-v2 first)_
Auto-verify Greenhouse tokens at startup so dead boards fail silently instead of polluting logs. Add Apify-based scrapers for YC Jobs, TrueUp, and/or Indeed. Tighten LinkedIn queries for better signal-to-noise.

Key decisions: which Apify actors to use (needs research at apify.com/store); per-source job cap config.

Known sourcing quality issues to fix in this branch:
- **Meta duplicates** — ~20 identical "Product Manager @ Meta" rows in the Sheet from the same scrape; need cross-run deduplication by (company, title) not just job_id
- **Generic LinkedIn listings** — roles like "Product Manager @ Meta" with no description snippet reach the LLM with insufficient context; explore requiring a minimum description length before LLM scoring

**`feature/sheets-ui`** _(depends on scoring-v2 first)_
Format `title` as `=HYPERLINK(url, title)` for one-click access. Score as percentage. Document a filter view setup for daily review. Low value until data quality upstream is fixed.

Key decisions: `USER_ENTERED` vs `RAW` for append (risk: job titles containing `=` misinterpreted as formulas).

### Phase 3 — Intelligence layer

- **Explainability** — store LLM rationale per job in CSV and Sheet; surface top reasons in digest
- **Application memory** — track outcomes (applied, interviewed, rejected); recalibrate scoring over time; likely needs SQLite in `private/`
- **Predictive company intelligence** — monitor funding signals (Crunchbase, Harmonic) for companies likely to hire PMs before they post; separate "watchlist" section in digest email

### Phase 4 — Scale and ops

- **Slack ingestion** — ingest job posts from a channel (bot needs `channels:history` scope)
- **Streamlit UI** — local web app for reviewing, filtering, updating status; most demonstrable as portfolio artifact
- **Python 3.11+ upgrade** — `google-auth` and `urllib3` both warn on 3.9 (EOL); low risk, removes noise

### LLM cost efficiency (cross-cutting)

This applies across all phases and should be revisited whenever a new LLM-heavy feature is added.

- **Model tiering** — use cheap models (Haiku, GPT-4o-mini, Gemini Flash) for high-volume structured tasks (scoring, classification) and reserve stronger models (Sonnet, GPT-4o) for quality-sensitive generation (resume notes, cover letters, digest). Controlled via `SCORING_LLM_PROVIDER` / `SCORING_MODEL` settings added in `feature/scoring-v2`.
- **Batching** — where possible, score multiple jobs in a single LLM call rather than one call per job. Reduces latency and token overhead from repeated system prompts. Tradeoff: harder to parse structured output reliably; test carefully.
- **Prompt caching** — Anthropic and OpenAI both support prompt caching for repeated system prompt content. `agent-context.md` is a prime candidate — it's sent on every scoring call and never changes within a run. Can reduce input token cost by 80%+ on cached content.
- **Pre-filtering** — keep keyword matching as a fast, free first pass to eliminate obvious non-matches before any LLM call. Only jobs that pass a minimum keyword threshold get LLM-scored. Reduces LLM call volume by ~30-50% with minimal quality loss.
- **Token budgets** — cap `description_snippet` length before sending to the LLM. The current 500-char snippet is reasonable; don't increase it without measuring cost impact.

### Tech debt

| Item | Severity | Notes |
|------|----------|-------|
| Python 3.9 EOL | Medium | `google-auth` will eventually drop support; warnings on every run |
| Keyword scoring | High | Fixed — shipped in `feature/scoring-v2` |
| LLM scoring latency | Medium | 150-200 calls/run at ~0.3s each = ~60s added; batching strategy needed |
| Greenhouse 404s | Low | Auto-verify in `feature/sourcing-v2` will fix permanently |
| GitHub Actions cache key | Low | Fixed — key is now `seen-jobs-v1-${{ github.run_id }}` with `restore-keys` fallback; each run saves a unique entry and restores the most recent |
| gspread `update()` argument order | Low | Fixed — `rescore_sheet.py` now uses named args `update(values=..., range_name=...)` |
| Meta/LinkedIn duplicates | Medium | ~20 identical "Product Manager @ Meta" rows from same scrape; dedup by (company, title) needed in `feature/sourcing-v2` |

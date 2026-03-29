# pm-job-agent

Multi-agent job hunting system: LangGraph orchestration, job discovery (Greenhouse + LinkedIn via Apify), scoring against your background, tailored documents on demand, and CSV export. See `.cursorrules` for goals and phases.

**What runs today:** A two-step workflow:

1. **`pm-job-agent run`** — discovers jobs from Greenhouse boards and LinkedIn (via Apify), scores each role with keyword matching, runs an LLM digest, and writes a timestamped CSV to `outputs/`. Document generation does **not** happen automatically.
2. **`pm-job-agent generate <csv>`** — reads a previous run CSV, generates a tailored resume note and cover letter opening for every row you flagged `yes` in the `flagged` column, and writes the results back into the same file.

LLM providers (Anthropic, OpenAI, Gemini, Ollama) are fully wired and swap via `DEFAULT_LLM_PROVIDER` in `.env` — no code changes needed.

**Not in code yet:** Google Sheets sync, Slack channel ingestion, Slack notifications.

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
    digest[LLM_digest]
    persist[Write_CSV_flagged_col_empty]
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
  rank --> digest
  digest --> persist
  persist --> openCSV
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
| `private/` | Not in Git. Two files matter: `agent-context.md` (career context for scoring/generation) and `search_profile.yaml` (keywords, board tokens, LinkedIn queries). Without these, discovery returns zero jobs but the run does not crash. |
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

4. **Career context** — add or edit `private/agent-context.md` (gitignored). Set `AGENT_CONTEXT_PATH` in `.env` if you want a different path.

5. **Search profile** — edit `private/search_profile.yaml`:

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

Runs discovery (Greenhouse + LinkedIn) → scoring → digest → CSV. Produces `outputs/run_YYYYMMDD_HHMMSS.csv` with a `flagged` column (empty by default).

```bash
pm-job-agent run --json   # print full graph state as JSON (includes agent_context — treat as sensitive)
```

### Generate documents for flagged roles

Open the CSV, set `flagged = yes` for the roles you want to apply to, then:

```bash
pm-job-agent generate outputs/run_YYYYMMDD_HHMMSS.csv
```

Reads every `flagged = yes` row, calls the LLM for a tailored resume note and cover letter opening for each, and writes the results back into the same CSV. Unflagged rows are untouched.

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
| `agents/` | Pipeline nodes: `context`, `discovery`, `scoring`, `digest`, `persist`, `generation` |
| `graphs/` | LangGraph compile (`build_core_loop_graph`) |
| `models/` | `LLMClient` protocol, `StubLLM`, `get_llm_client()` factory; `providers/` holds Anthropic, OpenAI, Gemini, Ollama |
| `services/` | Shared types (`JobDict`, `RankedJobDict`, `DocumentDict`) and `redact_pii()` |
| `integrations/` | `greenhouse.py`: Greenhouse board client. `linkedin.py`: LinkedIn via Apify Actor |
| `cli/` | `main.py` (subcommands: `run`, `generate`); `generate_cmd.py` (on-demand generation logic) |

## Tests

```bash
pytest
```

## Docker

```bash
docker build -t pm-job-agent .
```

The build context excludes `private/`, `.env`, and virtualenvs via `.dockerignore`.

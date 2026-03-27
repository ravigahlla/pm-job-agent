# pm-job-agent

Multi-agent job hunting system: LangGraph orchestration, job discovery (Greenhouse, Adzuna), scoring against your background, tailored documents, and Slack delivery (see `.cursorrules` for goals and phases).

## Architecture

High-level data flow: triggers run the LangGraph pipeline, which pulls jobs from board APIs, reads **local** career context (not in Git), calls an **LLM** through a swappable adapter, and produces ranked output plus optional **Slack** notifications. **API keys** and paths come from environment variables (`.env` locally, **GitHub Secrets** in CI).

```mermaid
flowchart TB
  subgraph trigger [Run_triggers]
    dev[Developer_CLI_or_Docker]
    cron[GitHub_Actions_cron]
  end

  subgraph secrets [Secrets_and_config]
    envVars[Environment_variables]
  end

  subgraph localOnly [Gitignored_local]
    career[private_career_context]
  end

  langGraph[LangGraph_pipeline]

  subgraph integrations [External_HTTP_APIs]
    ghAPI[Greenhouse]
    adzAPI[Adzuna]
    slack[Slack]
  end

  llm[LLM_adapter]

  subgraph out [Outputs]
    artifacts[Ranks_resume_and_cover_text]
    optionalOut["outputs_or_var_on_disk"]
  end

  dev --> langGraph
  cron --> langGraph
  envVars --> langGraph
  career -->|"AGENT_CONTEXT_PATH"| langGraph
  langGraph --> ghAPI
  langGraph --> adzAPI
  langGraph --> llm
  langGraph --> artifacts
  langGraph --> slack
  langGraph --> optionalOut
```

Package layout mirrors this flow: `integrations/` for HTTP clients, `agents/` and `graphs/` for LangGraph, `models/` for the LLM wrapper, `config/` for settings, `services/` for scoring and generation orchestration (see **Layout** below).

## Setup

### Virtual environment (recommended)

**Yes — use a virtual environment** on every machine (laptop, desktop, or Pi). It keeps dependencies out of your system Python, avoids version clashes across projects, and matches what most tutorials and CI images assume.

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows (cmd): .venv\Scripts\activate.bat
pip install --upgrade pip
pip install -e ".[dev]"
```

`.venv/` is gitignored. Deactivate with `deactivate` when finished.

### Bootstrap script (macOS / Linux / WSL)

From the repo root, one shot:

```bash
chmod +x scripts/bootstrap.sh   # first time only, if needed
./scripts/bootstrap.sh
```

This creates `.venv` if missing, upgrades `pip`, runs `pip install -e ".[dev]"`, and copies `.env.example` → `.env` **only when `.env` does not exist** (never overwrites). Then activate:

```bash
source .venv/bin/activate
```

Use `PYTHON=/path/to/python3.12 ./scripts/bootstrap.sh` if `python3` is not the interpreter you want. **Windows (cmd/PowerShell):** use the manual venv steps above, or run the script under **Git Bash / WSL**.

### After `git clone` or `git pull` on a new machine

`git` only updates **tracked** files. It does **not** restore local-only material. On every new computer (including a **Raspberry Pi** after you clone or pull this repo), you still need the items below.

**In the remote (GitHub):** source code, `pyproject.toml`, `scripts/bootstrap.sh`, `.env.example`, `Dockerfile`, tests, README, etc.

**Not in the remote (gitignored or never committed):** recreate or copy these yourself.

| Path / item | What to do |
|-------------|------------|
| `private/` | Not in Git. Restore from your own backup (USB, encrypted sync, etc.) or recreate files such as `private/agent-context.md`. Without this, scoring and generation have no career context unless you point `AGENT_CONTEXT_PATH` elsewhere. |
| `.env` | Not in Git. After clone, run `./scripts/bootstrap.sh` to create `.env` from `.env.example` **only if** `.env` is missing; then fill in real API keys. Or copy a backed-up `.env` onto the machine (bootstrap will not overwrite an existing `.env`). |
| `.venv/` | Not in Git. Run `./scripts/bootstrap.sh` from the repo root, or create a venv and `pip install -e ".[dev]"` manually. |
| `outputs/`, `var/` | Gitignored scratch/output dirs; created as needed. |

**Suggested order after clone or `git pull` on a fresh environment:**

1. Install **Git** and **Python 3.9+** (see the hardware table below). On Debian/Ubuntu-based systems you may need `build-essential` (and sometimes `python3-venv`) before bootstrap if packages must compile from source (common on **ARM** / Pi when wheels are missing).
2. `cd` into the repo root.
3. `./scripts/bootstrap.sh` (creates `.venv` and installs the package; seeds `.env` only if absent).
4. Restore **`private/`** and ensure **`.env`** holds your real secrets (if bootstrap created `.env`, replace placeholders).
5. `source .venv/bin/activate` and run `pytest`. In **Cursor / VS Code**, set **Python: Select Interpreter** to `./.venv/bin/python` so the editor matches the venv.

Pulling new commits on a machine **that already has** `.venv`, `private/`, and `.env` usually only requires `git pull`; re-run `./scripts/bootstrap.sh` if `pyproject.toml` dependencies changed or you want a clean reinstall (`rm -rf .venv` first).

**Raspberry Pi:** Phase 1 is not optimized for Pi (see `.cursorrules`). Expect slower `pip` installs and possible extra build tools on **ARM**. If dependency installs fail, install compilers (`sudo apt install build-essential python3-dev`) and retry. For a low-friction path, run the agent on a laptop or in **GitHub Actions** and use the Pi only if you accept that friction.

### Recommended hardware and OS

| Context | Notes |
|--------|--------|
| **Day-to-day development** | macOS or Linux on a normal laptop/desktop is ideal. This project calls **remote LLM and job APIs** in Phase 1; you do not need a GPU. **8 GB RAM** is workable; **16 GB** is comfortable if you run Docker and a browser together. |
| **Clean reinstall / new machine** | Install Python 3.9+ (3.11+ preferred), Git, then follow the venv steps above. Restore secrets via `.env` or your password manager; restore career files under `private/` manually or from your own backup (they are not in Git). |
| **Docker** | Matches CI/production-like runs on **x86_64 or arm64** with Docker Desktop / Engine. Official images are multi-arch where noted; builds are slower on low-power ARM. |
| **Raspberry Pi** | Phase 1 is **not** scoped to Raspberry Pi (see `.cursorrules`). If you still clone there: use a **64-bit** OS, Python **3.11+** if available, `python3 -m venv .venv`, and expect **slow** installs or missing wheels for some scientific/ML stacks as the project grows—build tools (`build-essential`) may be required. Prefer running the agent on your laptop or in **GitHub Actions**; use the Pi only if you accept tinkering. |

**Prerequisite:** Python **3.9+** on your PATH (3.11+ recommended; the `Dockerfile` uses 3.12).

1. **Environment variables** — copy the template and edit locally (file is gitignored). Skip `cp` if `./scripts/bootstrap.sh` already created `.env`.

   ```bash
   cp .env.example .env
   ```

   Put real API keys and tokens only in `.env` or your shell. In GitHub Actions, use repository **Secrets**, not committed files.

2. **Career context** — add or edit `private/agent-context.md` (gitignored). Optional: set `AGENT_CONTEXT_PATH` in `.env` to another path for CI or different machines.

## Layout

| Path | Role |
|------|------|
| `src/pm_job_agent/` | Application package (`config`, `models`, `integrations`, `agents`, `graphs`, `services`, `cli`) |
| `tests/unit/` | Fast tests, mocked HTTP |
| `tests/integration/` | Tests that call real APIs (optional; skip without keys) |
| `scripts/` | One-off local scripts |
| `docker/` | Extra container assets (optional) |
| `private/` | **Local only** — resume, project write-ups, agent context |

Generated artifacts that might contain PII should go under `outputs/` or `var/` (both gitignored).

## Tests

```bash
pytest
```

## Docker

```bash
docker build -t pm-job-agent .
```

The build context excludes `private/`, `.env`, and virtualenvs via `.dockerignore`.

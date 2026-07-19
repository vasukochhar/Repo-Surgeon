# Repo Surgeon

Repo Surgeon is an autonomous codebase-modernization pipeline built for OpenAI Build Week 2026. Point it at a repo and it establishes a test baseline, researches real breaking changes, executes dependency upgrades and security fixes inside a sandbox, proves its own generated tests actually catch bugs, and opens small, risk-graded pull requests — unattended.

## Status

| Component | Owner | Status |
| --- | --- | --- |
| Orchestrator, job state machine, Surgeon self-correction loop, Codex runner, FastAPI/SSE endpoints | Vasu | Done |
| Sandbox, Scout (stack detection, baseline, coverage), security scanners, Verifier (baseline diff, affected tests, mutation testing) | Faaiz | Done |
| Dashboard (Next.js) | Anubhav | Done |
| Evidence-backed Researcher, GitHub Reviewer/PR creation, CI watcher + bounded repair loop | Mayank | Done — enabled in real mode; demo forks need selected targets |

The pipeline runs end to end in mock mode by default. Real mode enables each production stage when its required credentials and local tools are available.

## What it does once every piece is real

1. **Submit.** A user pastes a repo URL into the dashboard.
2. **Scout** (Faaiz, real) clones the repo into a Docker sandbox, detects the stack, runs the existing test suite/build for a baseline, and scans dependencies with OSV-Scanner/pip-audit/npm audit.
3. **Researcher** (Mayank) resolves compact PyPI/npm metadata first, applies a deterministic security/major/minor/patch policy, and uses GPT web search only where migration or advisory research is warranted. It validates version-specific structured research cards against the detected dependencies and retains claim-to-primary-source evidence.
4. **Planner** (Vasu, real) turns the profile and breaking-change map into a risk-ordered upgrade plan: security fixes first, then patch, minor, major.
5. **Surgeon** (Vasu + Faaiz, real) runs Codex headless per item with only that package's bounded research card, then Faaiz's Verifier runs affected tests and the required final full suite/build, diffs against baseline, and feeds failures back to Codex (capped at 5 attempts before flagging `needs_human`). A no-mapping affected-test fallback is reused instead of immediately running the same full suite twice. Coverage is final-candidate-only, and mutation testing requires both tests and source changes.
6. **Reviewer** (Mayank) splits green items into small, risk-graded PRs. Each PR contains its evidence link, verification record, confidence grade, and rollback note.
7. **CI watcher** (Mayank) polls GitHub check runs; on failure it extracts the failing check output, asks Codex for a focused repair on the PR branch, pushes a fix commit, and rechecks (capped at two repairs).
8. **Dashboard** (Anubhav, real) shows all of this live: a pipeline stepper, the scout report, the upgrade plan, per-item attempt/score cards with a diff viewer, and the resulting PR links.

Mock and real implementations share the same contracts, so the dashboard and orchestrator do not change when switching modes.

## Pipeline

```text
QUEUED -> SCOUTING -> RESEARCHING -> PLANNING -> OPERATING
      -> REVIEWING -> WATCHING_CI -> DONE

Terminal states: NEEDS_HUMAN, FAILED
```

For each upgrade item, the Surgeon follows this loop:

```text
Codex edit -> verify -> green
                    \-> pass failure logs back to Codex -> retry (max 5)
```

An item that is still failing after five attempts becomes `needs_human`; the pipeline never forces a broken upgrade.

## Repository layout

```text
repo_surgeon/
  contracts.py      Shared Pydantic schemas; source of truth for integrations
  interfaces.py     Protocols for all teammate boundaries
  orchestrator.py   Pipeline state machine
  planner.py        Mock fallback and OpenAI Responses planner
  surgeon.py        Codex/verify self-correction loop
  codex_runner.py   Real and mock Codex runners
  events.py         Async event bus used by SSE
  jobstore.py       In-memory job registry
  app.py            FastAPI application
  researcher.py     GPT-5.6 web-search research with source validation
  research/         Registry providers, routing policy, cache, token budgets, summarization
  github_layer.py   Git branch/worktree management and GitHub PR creation
  ci.py             Check-run watcher and bounded Codex repair loop
  mocks/            Mock services used by the safe default mode
  sandbox/          Docker sandbox manager, command runner, network policy
  scout/            Stack detection, baseline runner, coverage, dependency collection
  security/         OSV-Scanner / pip-audit / npm audit parsing and normalization
  verifier/         Regression-aware verification, affected tests, mutation testing, quality score
dashboard/          Next.js dashboard (submit a repo, watch the live pipeline, view diffs/PRs/scores)
docs/               Implementation plans
tests/              Backend test suite (pytest)
```

## Setup

Prerequisites:

- Python 3.12+
- Node.js/npm (dashboard, and to install the Codex CLI)
- Git
- Docker (only needed for real-mode sandbox execution)

Install the backend:

```powershell
py -m pip install -e ".[dev]"
```

If `py` is not on PATH, use the bundled Python runtime:

```powershell
$py = "C:\Users\MSI1\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py -m pip install -e ".[dev]"
```

Run the backend tests:

```powershell
& $py -m pytest -q
```

## Run the mock demo

Start the API:

```powershell
& $py -m uvicorn repo_surgeon.app:app --host 127.0.0.1 --port 8000
```

In another terminal, create a job:

```powershell
$job = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/jobs" `
  -ContentType "application/json" `
  -Body '{"repo_url":"https://example.invalid/demo.git"}'

Invoke-RestMethod "http://127.0.0.1:8000/jobs/$($job.job_id)"
```

The default application uses mocks, so this demo does not call OpenAI or modify a repository.

## Dashboard

The dashboard lives in [`dashboard/`](dashboard) (Next.js 16 + Tailwind). It proxies every API call through `/api/backend/*` to the FastAPI backend, so no CORS configuration is needed.

```powershell
cd dashboard
npm install
npm run dev
```

Open `http://localhost:3000` with the backend running on `:8000` (set `BACKEND_URL` in `dashboard/.env.local` to point elsewhere). Submitting a repo URL creates a job and opens its live page: a pipeline stepper, the scout report, the upgrade plan, per-item cards with live test counts and a diff viewer, mutation/test-quality scores (populated in real mode; mock mode shows placeholders), and PR links. See [`docs/DASHBOARD_IMPLEMENTATION_PLAN.md`](docs/DASHBOARD_IMPLEMENTATION_PLAN.md) for the full design.

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /jobs` | Create and asynchronously run a job. Body: `{ "repo_url": "..." }`. |
| `GET /jobs` | List all jobs (id, repo URL, state, error). |
| `GET /jobs/{job_id}` | Read the current state, results, PRs, error, repo profile, and upgrade plan. |
| `GET /jobs/{job_id}/events` | Server-sent event stream for the dashboard. |

## Live Codex runner

Install the standalone CLI:

```powershell
npm install --global @openai/codex
codex --version
```

Set these environment variables in the terminal that will run the live command:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
$env:CODEX_API_KEY = $env:OPENAI_API_KEY
```

`RealCodexRunner` invokes `codex exec --sandbox workspace-write`, supplies migration and failure context, captures the resulting Git patch, and removes any temporary `AGENTS.md` it created. The live smoke test has been verified by updating an isolated fixture from `requests==2.31.0` to `requests==2.32.3`.

## Live GPT planner

`Planner()` intentionally defaults to a mock-safe fallback plan. To use the OpenAI Responses API, construct the planner with:

```python
planner = Planner.from_openai()
```

Planner, Researcher, and the optional OpenAI summarizer use only `gpt-5.6-luna`. Set both `REPO_SURGEON_MODEL` and `REPO_SURGEON_RESEARCH_MODEL` to that exact value; a different explicit or environment model is rejected instead of silently activating another model. The OpenAI key must be available as `OPENAI_API_KEY`.

## Dependency research policy and budgets

Research is registry-first and remains sequential with the existing single-worktree orchestrator. Security upgrades always receive advisory/fixed-version research; major upgrades receive migration research; minor upgrades use web research only when registry or constraint metadata signals compatibility work; ordinary patches use registry metadata; non-vulnerable transitive dependencies remain metadata-only. Candidates are prioritized security, major, minor, then patch and processed in configurable batches without a ten-package cutoff. Every result is marked `researched`, `metadata_only`, `cached`, `deferred`, `failed`, or `budget_exceeded`.

OpenAI research defaults to one package and one concurrent request. The application owns the single retry layer (SDK retries are disabled): temporary request- or token-rate limits use up to five total attempts with randomized exponential backoff, while provider reset headers can extend the wait. Quota, billing, project-usage, model-access, and unknown rate-limit failures are not blindly retried; affected research is explicitly deferred while registry-only packages continue. Safe metrics retain categories, attempts, waits, request IDs, and provider-reported token counts without prompts, page contents, credentials, or authorization headers.

The file-backed cache key includes ecosystem, normalized package, current and target versions, and research schema version. Security entries default to a one-day TTL; ordinary migration information defaults to 30 days. Cache write/read failures degrade safely, and `.repo-surgeon-cache/` is ignored by Git.

The Planner receives a compact research index, not full cards or page text. The target is 8,000 tokens and the enforced absolute maximum is 20,000; lowest-priority non-security entries are explicitly budget-deferred if necessary. Each Surgeon call receives only its current package card, capped at 1,500 estimated tokens. Provider token usage is recorded separately from deterministic estimates. See [`.env.example`](.env.example) for every research, cache, context, summarization, coverage, and mutation setting.

## Real-mode credentials and safety

Copy [`.env.example`](.env.example) to `.env`, then set `REPO_SURGEON_MODE=real`, `OPENAI_API_KEY`, and `GITHUB_TOKEN`. The GitHub token needs repository contents and pull-request read/write access; Actions/check-run read access is needed for CI watching. `GITHUB_TOKEN` is not required to construct the application, but jobs cannot open or watch live PRs without it.

The Python application reads standard environment variables; load the local `.env` file into your shell before starting it:

```bash
cp .env.example .env
# Edit .env with your credentials, then:
set -a && source .env && set +a
.venv/bin/python -m uvicorn repo_surgeon.app:app --host 127.0.0.1 --port 8000
```

On PowerShell, set the same values with `$env:VARIABLE = "value"` before running Uvicorn. `.env` is ignored by Git, so credentials are not committed.

Real mode is deliberately opt-in: it creates remote branches and pull requests only for the repository URL submitted to that job. The reviewer creates one branch per green upgrade, and the CI repair loop is capped at two fix commits per PR; a persistent failure is reported as `needs_human` rather than silently retried forever.

The plan's separate demo-fork task is not performed automatically: it needs the team to choose 2–3 source repositories and authorize forks in the GitHub account. This repository contains the pipeline needed to seed and process those chosen demos, but does not create external forks on startup.

Beyond choosing demo sources, remaining product work is limited to optional live GPT planning and dashboard visual polish.

## Faaiz services and real mode

Faaiz's production Sandbox, Scout, security, and Verifier services integrate through Vasu's existing protocols. The default remains safe mock mode. Set `REPO_SURGEON_MODE=real` to construct the real services; imports never start Docker or scanners.

```text
RealSandbox -> RealScout -> RepoProfile -> Surgeon edits
                                      -> affected-test hook -> RealVerifier -> mutation score
```

Build and run the isolated runtimes with:

```powershell
docker build -t repo-surgeon-python -f docker/python/Dockerfile .
docker build -t repo-surgeon-node -f docker/node/Dockerfile .
$env:REPO_SURGEON_MODE = "real"
python -m uvicorn repo_surgeon.app:app
```

Real mode expects Docker and Git. OSV-Scanner, pip-audit, mutmut, npm audit, and project-local Stryker are classified as unavailable when absent. Sandbox execution applies memory, CPU, PID, capability, privilege, mount, timeout, and phase-based network controls. Dependency installation may use the network; execution defaults to no network. Hostname allow-list enforcement requires an external proxy and is not provided by native Docker bridge mode. Host execution is disabled unless explicitly enabled for development.

Scout detects Python and JavaScript/TypeScript manifests, lockfiles, package managers, commands, and root workspaces. It captures baseline failures, dependency trees, coverage JSON, and normalized scanner findings. A deterministic `repo_profile.json` is written in the Repo Surgeon temporary output directory, outside the inspected repository. Its main fields include `schema_version`, `repository`, `stack`, `commands`, `baseline`, `coverage_result`, `dependencies`, and `security_report`.

Verifier loads the workspace-scoped profile, runs affected tests before the original full suite/build, and treats only new failures or a build regression as fatal. If affected-test selection cannot safely map files, its full-suite fallback is the final full-suite result and is not repeated. Coverage runs only for a green final candidate by default. Targeted mutmut or project-local Stryker runs occur only when both tests and production sources materially changed and are non-fatal when unavailable. Verification records elapsed duration, command count, and which optional stages actually ran. Quality scoring reweights mutation, changed-code coverage, and stability when inputs are absent.

Current limits: Python and JavaScript/TypeScript only; root-level monorepo commands only; phase-based rather than hostname-based network rules; external scanner availability varies; mutation testing is targeted and capped.

```powershell
python -m pytest -q
python -m compileall repo_surgeon
```

## Current verification status

- Backend: run `python -m pytest -q` for the current exact count; the suite covers the mock pipeline end to end (`QUEUED` → `DONE`), structured research routing/cache/budgets, verifier command policy, Surgeon retry behavior, and the job-list/profile/plan API additions.
- Real `codex exec`: smoke-tested with a writable sandbox and a captured Git patch.
- Dashboard: manually verified end to end against the mock pipeline — live stepper, scores, diff viewer, and PR panel render correctly; a stale job ID after a backend restart shows a friendly "not found" page instead of crashing; two concurrent jobs in separate tabs don't cross-contaminate events; `npm run build` and `npm run lint` both pass clean.

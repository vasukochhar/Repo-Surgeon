# Repo Surgeon

Repo Surgeon is an autonomous codebase-modernization pipeline built for OpenAI Build Week 2026. Point it at a repo and it establishes a test baseline, researches real breaking changes, executes dependency upgrades and security fixes inside a sandbox, proves its own generated tests actually catch bugs, and opens small, risk-graded pull requests — unattended.

## Status

| Component | Owner | Status |
| --- | --- | --- |
| Orchestrator, job state machine, Surgeon self-correction loop, Codex runner, FastAPI/SSE endpoints | Vasu | Done |
| Sandbox, Scout (stack detection, baseline, coverage), security scanners, Verifier (baseline diff, affected tests, mutation testing) | Faiz | Done |
| Dashboard (Next.js) | Anubhav | Done |
| Real Researcher, real Reviewer/PR creation, CI watcher | Mayank | Pending — mocked today |

The pipeline runs end to end today using mocks for the pending pieces, so the dashboard, orchestrator, and real Sandbox/Scout/Verifier can all be exercised now without waiting on the rest.

## What it does once every piece is real

1. **Submit.** A user pastes a repo URL into the dashboard.
2. **Scout** (Faiz, real) clones the repo into a Docker sandbox, detects the stack, runs the existing test suite/build for a baseline, and scans dependencies with OSV-Scanner/pip-audit/npm audit.
3. **Researcher** (Mayank, still mocked) asks GPT-5.6 with web search to fetch the real changelog, migration guide, and known issues for every outdated or vulnerable dependency.
4. **Planner** (Vasu, real) turns the profile and breaking-change map into a risk-ordered upgrade plan: security fixes first, then patch, minor, major.
5. **Surgeon** (Vasu + Faiz, real) runs Codex headless per item with the breaking-change context injected, then Faiz's Verifier re-runs affected and full tests, diffs against baseline, and feeds failures back to Codex (capped at 5 attempts before flagging `needs_human`). It also mutation-tests any new/changed tests to score how many injected bugs they actually catch.
6. **Reviewer** (Mayank, still mocked) splits green items into small PRs ordered by risk, each with an explanation, evidence links, test/mutation scores, a confidence grade, and a rollback note.
7. **CI watcher** (Mayank, still mocked) polls each PR's checks; on failure it pulls the logs, feeds them back to the Surgeon, and pushes a fix commit — repeating until CI passes.
8. **Dashboard** (Anubhav, real) shows all of this live: a pipeline stepper, the scout report, the upgrade plan, per-item attempt/score cards with a diff viewer, and the resulting PR links.

Once Mayank's Researcher/Reviewer/CI-watcher land, steps 3, 6, and 7 switch from mock data to real GPT research and real GitHub PRs — nothing else in the pipeline or dashboard needs to change, since they were built against the same contracts the mocks already satisfy.

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
  mocks/            Mock Researcher, Reviewer (Scout/Sandbox/Verifier mocks retained for tests)
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

Open `http://localhost:3000` with the backend running on `:8000` (set `BACKEND_URL` in `dashboard/.env.local` to point elsewhere). Submitting a repo URL creates a job and opens its live page: a pipeline stepper, the scout report, the upgrade plan, per-item cards with live test counts and a diff viewer, mutation/test-quality scores (populated in real mode; mock mode shows placeholders), and PR links — mock PRs are labeled as such until Mayank's Reviewer replaces them. See [`docs/DASHBOARD_IMPLEMENTATION_PLAN.md`](docs/DASHBOARD_IMPLEMENTATION_PLAN.md) for the full design.

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

It uses `REPO_SURGEON_MODEL` when set, otherwise `gpt-5.6`. The OpenAI key must be available as `OPENAI_API_KEY`.

## Still pending

1. Replace mock `Researcher` and `Reviewer` (real PR creation) with Mayank's implementations, and wire in the CI watcher through the existing `WATCHING_CI` hook.
2. Use the live GPT planner when real API-backed upgrade plans are desired instead of the mock fallback behavior.
3. Dashboard UI/UX polish — the current dashboard is functionally complete (every pipeline stage, score, diff, and PR is wired up and live) but intentionally plain; visual design is open for a follow-up pass.

## Faiz services and real mode

Faiz's production Sandbox, Scout, security, and Verifier services integrate through Vasu's existing protocols. The default remains safe mock mode. Set `REPO_SURGEON_MODE=real` to construct the real services; imports never start Docker or scanners.

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

Verifier loads the workspace-scoped profile, runs affected tests before the original full suite/build, and treats only new failures or a build regression as fatal. Targeted mutmut or project-local Stryker runs occur only when tests changed and are non-fatal when unavailable. Quality scoring reweights mutation, changed-code coverage, and stability when inputs are absent.

Current limits: Python and JavaScript/TypeScript only; root-level monorepo commands only; phase-based rather than hostname-based network rules; external scanner availability varies; mutation testing is targeted and capped.

```powershell
python -m pytest -q
python -m compileall repo_surgeon
```

## Current verification status

- Backend: 46/46 tests pass (`python -m pytest -q`), covering the mock pipeline end to end (`QUEUED` → `DONE`), Surgeon retry behavior (fail-then-pass and five-iteration `needs_human` paths), and the job-list/profile/plan API additions.
- Real `codex exec`: smoke-tested with a writable sandbox and a captured Git patch.
- Dashboard: manually verified end to end against the mock pipeline — live stepper, scores, diff viewer, and PR panel render correctly; a stale job ID after a backend restart shows a friendly "not found" page instead of crashing; two concurrent jobs in separate tabs don't cross-contaminate events; `npm run build` and `npm run lint` both pass clean.

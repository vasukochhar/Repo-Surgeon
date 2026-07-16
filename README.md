# Repo Surgeon - Orchestrator & Agent Pipeline

Repo Surgeon is an autonomous codebase-modernization pipeline for OpenAI Build Week 2026. This repository currently contains **Vasu's component**: the mock-first orchestrator and Surgeon execution pipeline.

It can run an unattended upgrade job end to end today using mocks, emit progress events for a dashboard, and use the local Codex CLI to make focused real edits when enabled.

## Scope and ownership

Vasu owns:

- Shared Pydantic JSON contracts
- Stage interfaces and mock implementations
- The job state machine and in-memory job store
- Upgrade planning and deterministic risk ordering
- The Surgeon self-correction loop, capped at five attempts
- The Codex CLI runner
- FastAPI job and SSE endpoints

The real Sandbox/Scout/Verifier services are owned by Faiz. The real Researcher, Reviewer, PR, and CI-watcher integrations are owned by Mayank. The dashboard is owned by Anubhav.

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
  mocks/            Mock Scout, Researcher, Verifier, Reviewer, Sandbox
tests/              Orchestrator, planner, and Surgeon tests
```

## Setup

Prerequisites:

- Python 3.12+
- Node.js/npm (only needed to install the Codex CLI)
- Git

Install the project:

```powershell
py -m pip install -e ".[dev]"
```

If `py` is not on PATH, use the bundled Python runtime:

```powershell
$py = "C:\Users\MSI1\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py -m pip install -e ".[dev]"
```

Run tests:

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

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /jobs` | Create and asynchronously run a job. Body: `{ "repo_url": "..." }`. |
| `GET /jobs/{job_id}` | Read the current state, results, PRs, and error, if any. |
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

## Still pending - teammate and final integration work

1. Replace mock `Sandbox`, `Scout`, `Verifier`, `Researcher`, and `Reviewer` implementations with the teammates' real services.
2. Agree and freeze [`contracts.py`](repo_surgeon/contracts.py) with Faiz and Mayank. This is the source of truth for every integration seam.
3. Connect Anubhav's dashboard to `GET /jobs/{job_id}/events` for live SSE progress updates.
4. Use the live GPT planner when real API-backed upgrade plans are desired instead of the mock fallback behavior.
5. Add Mayank's CI watcher through the existing `WATCHING_CI` hook.

## Current verification status

- Mock pipeline: verified from `QUEUED` to `DONE`.
- Surgeon retry behavior: verified for fail-then-pass and five-iteration `needs_human` paths.
- FastAPI job creation/status: smoke-tested.
- Real `codex exec`: smoke-tested with a writable sandbox and a captured Git patch.

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

# Repo Surgeon — Dashboard Implementation Plan (Anubhav's component)

> **Audience:** an AI coding agent (Claude Sonnet) implementing this unattended.
> **Repo:** `E:\openai\Repo-Surgeon` (Python backend already exists and works — do NOT restructure it).
> **Goal:** build the Next.js dashboard described in the team plan: submit a repo URL, watch the
> live pipeline, view diffs, PR links, and test-quality/mutation scores. Plus a few small,
> additive FastAPI changes the dashboard needs.

---

## 0. Context — what already exists (verified 2026-07-17)

The backend is real and working. `python -m pytest -q` passes **44/44** from the repo root.

| Component | Owner | Status |
|---|---|---|
| FastAPI app, orchestrator state machine, job store, event bus | Vasu | ✅ done, tested |
| Surgeon self-correction loop (max 5 iterations → `needs_human`) | Vasu | ✅ done, tested |
| Codex runner (mock + real `codex exec`), GPT planner (mock fallback + Responses API) | Vasu | ✅ done |
| Docker sandbox, Scout (stack detect / baseline / coverage / deps), security scanners, Verifier (baseline diff, affected tests, mutmut/Stryker mutation, quality score) | Faiz | ✅ done, tested |
| Researcher, Reviewer (PR creation), CI watcher | Mayank | ❌ still mocks — `app.py` uses `MockResearcher()` / `MockReviewer()` even in real mode |
| **Dashboard** | **Anubhav** | ❌ **does not exist — this plan builds it** |

Run the backend for development (from repo root, Windows):

```powershell
python -m pip install -e ".[dev]"
python -m uvicorn repo_surgeon.app:app --host 127.0.0.1 --port 8000
```

Default mode is **mock**: a job flows through every stage in <1s with no Docker, no OpenAI calls,
no repo modification. This is the mode to build and test the dashboard against.

---

## 1. Exact backend contract (as implemented today)

### 1.1 Endpoints (`repo_surgeon/app.py`)

| Endpoint | Request | Response |
|---|---|---|
| `POST /jobs` | `{"repo_url": "https://..."}` | `{"job_id": "<uuid>"}` — job runs asynchronously immediately |
| `GET /jobs/{job_id}` | — | `{"id", "repo_url", "state", "results", "prs", "error"}` (404 if unknown) |
| `GET /jobs/{job_id}/events` | — | SSE stream, `text/event-stream`; each message is `data: <Event JSON>\n\n` |

### 1.2 Job states (`repo_surgeon/jobstore.py` → `JobState`, lowercase strings)

```
queued → scouting → researching → planning → operating → reviewing → watching_ci → done
Terminal: done | needs_human | failed
```

### 1.3 SSE Event shape (`repo_surgeon/contracts.py` → `Event`)

```json
{"job_id": "uuid", "stage": "scouting", "type": "started", "ts": "2026-07-17T12:00:00Z", "payload": {}}
```

Event types actually emitted today:
- `started` / `completed` — once per stage (stage = current `JobState` value)
- `iteration` — during `operating`, payload: `{"item_id": "...", "iteration": 1, "passed": true}`
- `completed` with stage `done`/`needs_human` — final success event
- `failed` — payload: `{"error": "..."}`

**Important:** `EventBus.subscribe` **replays full history first**, then streams live. A client
connecting late still receives every past event. The stream never sends a terminal sentinel —
the client must close the `EventSource` itself when it sees a terminal state.

### 1.4 Result objects inside `GET /jobs/{id}`

`results`: list of `SurgeonResult` → `{item_id, status: "green"|"needs_human"|"failed", iterations, files_changed: [...], patch: "<unified diff>"}`
`prs`: list of `PRResult` → `{url, item_ids: [...]}` (mock URL until Mayank's reviewer lands)

### 1.5 Known gaps the dashboard needs fixed (Phase 2 makes these additive changes)

1. `GET /jobs/{id}` omits `job.profile` (RepoProfile) and `job.plan` (UpgradePlan) even though the
   Job dataclass holds them — the dashboard can't show dependencies, vulnerabilities, baseline, or
   the upgrade plan table without them.
2. No `GET /jobs` list endpoint — the home page can't enumerate jobs.
3. Mutation score / test-quality score (`VerifyResult.test_quality_score`,
   `mutation_report.score`) are computed by the Verifier but **discarded** — `Surgeon.operate`
   only publishes `{item_id, iteration, passed}` and `SurgeonResult` doesn't carry them. The demo
   script literally says "the agent's new tests caught 87% of injected bugs", so this must be surfaced.
4. No CORS middleware — solved by proxying through Next.js rewrites (preferred; SSE works through
   Next rewrites) so no backend CORS change is needed.

---

## 2. Phase overview

| Phase | Deliverable | Depends on |
|---|---|---|
| 1 | Next.js scaffold in `dashboard/` with proxy to the API | — |
| 2 | Small additive FastAPI changes (jobs list, profile/plan in job JSON, verify scores in events) | — |
| 3 | TypeScript types + API client + `useJobEvents` SSE hook | 1, 2 |
| 4 | Home page: submit form + recent jobs list | 3 |
| 5 | Job detail page: pipeline stepper, live event log, plan table, item cards | 3 |
| 6 | Diff viewer, PR links, scores panel | 5 |
| 7 | Polish: reconnect, error states, dark theme, responsive | 4–6 |
| 8 | End-to-end verification checklist | all |

Work strictly in this order. Each phase ends with its acceptance check passing.

---

## Phase 1 — Scaffold

1. From repo root: `npx create-next-app@latest dashboard --typescript --tailwind --eslint --app --src-dir --no-import-alias` (accept defaults otherwise; no Turbopack flag needed).
2. Add API proxy in `dashboard/next.config.ts`:

```ts
const nextConfig = {
  async rewrites() {
    return [{ source: "/api/backend/:path*",
              destination: `${process.env.BACKEND_URL ?? "http://127.0.0.1:8000"}/:path*` }];
  },
};
export default nextConfig;
```

All browser calls go to `/api/backend/...` — same origin, no CORS, and SSE streams pass through.
3. Add `dashboard/.env.example` with `BACKEND_URL=http://127.0.0.1:8000`.
4. Append to root `.gitignore`: `dashboard/node_modules/`, `dashboard/.next/`, `dashboard/.env*.local`.

**Accept:** `npm run dev` inside `dashboard/` serves a page on :3000, and with uvicorn running,
`curl -X POST http://localhost:3000/api/backend/jobs -H "Content-Type: application/json" -d '{"repo_url":"https://example.invalid/demo.git"}'` returns a `job_id`.

## Phase 2 — Additive backend changes (keep diffs minimal; do not refactor)

These touch Vasu's files. Make the smallest possible additive edits; run `python -m pytest -q`
after each and keep all 44 tests green.

1. **Jobs list.** In `jobstore.py` add `def list(self) -> list[Job]: return list(self._jobs.values())`.
   In `app.py` add:

```python
@app.get("/jobs")
async def list_jobs() -> list[dict]:
    return [{"id": j.id, "repo_url": j.repo_url, "state": j.state, "error": j.error}
            for j in store.list()]
```

2. **Expose profile + plan.** In `app.py`'s `get_job`, add to the returned dict:
   `"profile": job.profile.model_dump(mode="json") if job.profile else None` and
   `"plan": job.plan.model_dump(mode="json") if job.plan else None`
   (results/prs are already serialized by FastAPI — leave them).
3. **Surface verify scores.** In `surgeon.py`, extend the published `iteration` event payload with:

```python
payload={"item_id": item.id, "iteration": iteration, "passed": verify.passed,
         "tests_passed": verify.tests_passed, "tests_failed": verify.tests_failed,
         "newly_failing_tests": verify.newly_failing_tests,
         "test_quality_score": verify.test_quality_score,
         "mutation_score": verify.mutation_report.score if verify.mutation_report else None}
```

   `Event.payload` is `dict[str, Any]` — no schema change, mocks unaffected.
4. Add a test in `tests/` asserting `GET /jobs` returns the created job and `GET /jobs/{id}`
   includes `profile` and `plan` after a mock run (use `httpx.AsyncClient` /
   `fastapi.testclient.TestClient` consistent with existing test style in `tests/test_orchestrator.py`).

**Accept:** all previous tests plus the new one pass.

## Phase 3 — Types, API client, SSE hook

Create `dashboard/src/lib/types.ts` mirroring the backend contract (§1). Key types:
`JobState` union, `Event`, `SurgeonResult`, `PRResult`, `UpgradeItem`, `UpgradePlan`,
`RepoProfile` (only the fields the UI uses: `language`, `package_manager`, `test_runner`,
`baseline {tests_passed, tests_failed, build_ok, coverage, failing_tests}`, `dependencies[]`,
`security_report {total, counts_by_severity, findings[]}`), `JobDetail` (the `GET /jobs/{id}` shape
including `profile` and `plan`).

`dashboard/src/lib/api.ts`: `createJob(repoUrl)`, `getJob(id)`, `listJobs()` — thin `fetch`
wrappers against `/api/backend`, throwing on non-2xx.

`dashboard/src/hooks/useJobEvents.ts` — the core hook:

```
useJobEvents(jobId) → { events: Event[], job: JobDetail | null, connected: boolean }
```

Behavior:
- Open `new EventSource(`/api/backend/jobs/${jobId}/events`)`; append each parsed message to `events`.
- On any `started`/`completed`/`failed`/`iteration` event, refetch `getJob(id)` (cheap; keeps
  `state`, `results`, `prs`, `profile`, `plan` in sync without a websocket).
- Derive current state from the latest event stage + the fetched job; when state is terminal
  (`done` | `needs_human` | `failed`), call `es.close()`.
- On `EventSource` `onerror` while non-terminal: close, wait 2s, reopen (history replay makes
  reconnect idempotent — deduplicate events by `(stage, type, ts, payload.item_id, payload.iteration)`).

**Accept:** a temporary test page logs the full event sequence for a mock job:
`queued→scouting started/completed→…→done completed`.

## Phase 4 — Home page (`/`)

- Header: "Repo Surgeon" + one-line tagline.
- **Submit card:** URL input (validate https:// prefix client-side), "Operate" button →
  `createJob` → `router.push(/jobs/${job_id})`. Disable while in flight; show API error inline.
- **Recent jobs:** fetch `listJobs()` on load + every 5s while the page is visible. Each row:
  short id, repo URL, state badge, link to detail page. Empty state: "No jobs yet — point the
  surgeon at a repository."
- State badge colors (used everywhere): queued=gray, running stages=blue pulse, done=green,
  needs_human=amber, failed=red.

**Accept:** submitting a URL lands on the job page; the home list shows the finished job with a green badge.

## Phase 5 — Job detail page (`/jobs/[id]`)

Client component using `useJobEvents`. Layout top-to-bottom:

1. **Header:** repo URL, job id (copyable), overall state badge, error banner when `failed`
   (show `job.error`).
2. **Pipeline stepper:** the 7 stages `scouting → researching → planning → operating → reviewing →
   watching_ci → done` rendered horizontally. A stage is `complete` if a `completed` event exists
   for it, `active` if `started` without `completed`, else `pending`. `failed` marks the active
   stage red; final state `needs_human` shows an amber flag on the last step.
3. **Scout summary card** (when `job.profile` present): language / package manager / test runner
   chips; baseline "N passed, M failed, build ✓/✗, coverage X%"; dependency count; vulnerability
   count grouped by severity from `security_report.counts_by_severity`.
4. **Upgrade plan table** (when `job.plan` present): one row per `UpgradeItem` — dependency,
   `from_version → to_version`, category badge (security=red, major=orange, minor=blue,
   patch=gray), risk as a 0–100% bar, rationale (truncated, title-attr full text).
5. **Operation item cards** (during/after `operating`): one card per plan item, keyed by
   `item_id`, fed by `iteration` events. Show attempt dots (●○○○○, max 5) — green when
   `passed:true` arrived, red for failed attempts; live counts `tests_passed/tests_failed`;
   final status from `job.results` (`green` → "✓ Green in N iteration(s)",
   `needs_human` → amber "Needs human after 5 attempts").
6. **Live event log:** collapsible, monospace, newest at bottom with auto-scroll; each line
   `[HH:MM:SS] stage type payload-summary`. Cap rendering at the last 500 events.

**Accept:** create a mock job with the page already open — stepper animates through all stages
in real time, item card fills in, log streams. Refresh mid-run — page rebuilds identical state
from history replay.

## Phase 6 — Diff viewer, PRs, scores

1. **Diff viewer:** on each result card, "View patch" expands `SurgeonResult.patch`. Implement a
   ~60-line unified-diff renderer (no heavy deps): split lines; `+` green bg, `-` red bg,
   `@@`/`diff --git`/`index` headers dimmed; horizontal scroll in a `overflow-x-auto` block; also
   list `files_changed` as chips above it. Handle empty patch ("No patch captured — mock mode").
2. **PR panel:** after `reviewing`, list `job.prs` — each `url` as an external link with the
   covered `item_ids`. Label clearly when the URL host is `example.invalid`:
   badge "mock PR (GitHub layer pending)".
3. **Scores panel (the demo centerpiece):** from the latest `iteration` event per item:
   `mutation_score` as a big radial/percent stat ("Injected-bug catch rate"), `test_quality_score`
   with grade word (≥80 strong, ≥60 adequate, else weak — mirrors
   `repo_surgeon/verifier/quality_score.py`). When both are `null` (mock mode), show the panel
   with "—" placeholders and the caption "Available in real mode", so the layout is demo-ready.

**Accept:** mock job shows patch text (mock runner emits one), mock PR link with the badge, and
the scores panel renders with placeholders.

## Phase 7 — Polish

- Dark theme default (judges see dashboards in dark), Tailwind only, no component library.
- Page `<title>`: "Repo Surgeon"; favicon: 🩺 or scalpel emoji via inline SVG.
- Loading skeletons for job fetch; 404 page for unknown job id (backend 404 → friendly message).
- SSE disconnect indicator: small "reconnecting…" pill when `connected === false` and job non-terminal.
- Mobile: stepper collapses to vertical below `md`.
- `npm run build` must pass with zero TypeScript errors — treat this as a gate.

## Phase 8 — End-to-end verification (do all of these before declaring done)

1. Backend: `python -m pytest -q` → all green (44 + new).
2. Start uvicorn (mock mode) + `npm run dev`. Submit `https://example.invalid/demo.git` from the
   UI; verify: stepper completes, item card green, patch viewable, mock PR listed, home page
   lists the job as `done`.
3. Kill uvicorn mid-run of a new job → UI shows reconnecting pill, no crash; restart backend →
   job is gone (in-memory store) → UI shows the 404-friendly state. No unhandled promise errors
   in the browser console.
4. Two jobs concurrently in two tabs — events do not cross between jobs.
5. `npm run build` succeeds.
6. Do NOT commit unless asked; if asked, keep backend and dashboard changes in separate commits.

---

## Out of scope for this plan (tracked elsewhere)

- Mayank's Researcher / Reviewer / CI-watcher (dashboard already handles their mock outputs and
  labels them as such; when real PR URLs appear the panel needs zero changes).
- Real-mode Docker runs (dashboard is transport-agnostic — same events, richer payloads).
- Demo video and Devpost submission (human tasks; the dashboard's job is to look good in them).
- Vercel deployment — local `npm run dev` is fine for the demo since the API is local; if
  deploying, set `BACKEND_URL` to a tunnel (e.g. cloudflared) — do not hardcode.

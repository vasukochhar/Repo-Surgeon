from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from .codex_runner import MockCodexRunner, RealCodexRunner
from .ci import live_ci_watcher
from .events import EventBus
from .jobstore import InMemoryJobStore
from . import live_logs
from .mocks import MockResearcher, MockReviewer, MockSandbox, MockScout, MockVerifier
from .orchestrator import Orchestrator
from .planner import Planner
from .github_layer import GitHubClient, GitHubReviewer
from .researcher import OpenAIResearcher
from .sandbox import AsyncCommandRunner, RealSandbox, SandboxedCommandRunner
from .scout import ProfileRegistry, RealScout
from .surgeon import Surgeon
from .verifier import RealVerifier

# uvicorn only configures its own "uvicorn.*" loggers; without this, every
# logger.info() call in the pipeline (repo_surgeon.*) is silently dropped by
# the root logger's default WARNING level, so the terminal shows request
# lines but nothing about what a job is actually doing.
#
# reconfigure(): the Windows console defaults to cp1252, which mangles every
# non-ASCII character the pipeline logs (em-dashes here, and arbitrary bytes in
# captured test output) into a replacement glyph or a UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
logging.getLogger("repo_surgeon").setLevel(
    logging.DEBUG if os.getenv("REPO_SURGEON_DEBUG", "").lower() in {"1", "true", "yes"} else logging.INFO)
# The OpenAI SDK logs full request/response bodies at DEBUG, which buries the
# pipeline's own output. Keep it at WARNING unless explicitly debugging HTTP.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
# Feeds the /debug dashboard's live log console (see live_logs.py) — a
# temporary testing aid, safe to delete along with debug_dashboard.html.
live_logs.install()


def build_orchestrator(mode: str | None = None, store: InMemoryJobStore | None = None,
                       events: EventBus | None = None) -> Orchestrator:
    mode = (mode or os.getenv("REPO_SURGEON_MODE", "mock")).lower()
    store, events = store or InMemoryJobStore(), events or EventBus()
    if mode == "mock":
        sandbox, scout, verifier, codex = MockSandbox(), MockScout(), MockVerifier(), MockCodexRunner()
        researcher, planner, reviewer, ci_watcher = MockResearcher(), Planner(), MockReviewer(), None
    elif mode == "real":
        host_runner, registry = AsyncCommandRunner(), ProfileRegistry()
        sandbox = RealSandbox(runner=host_runner)
        runner = SandboxedCommandRunner(sandbox)
        codex = RealCodexRunner()
        # codex is passed in so Scout can bootstrap a test suite when none is
        # detected, rather than leaving every upgrade on that repo unverifiable.
        scout, verifier = RealScout(runner, registry, codex=codex), RealVerifier(registry, runner)
        token = os.getenv("GITHUB_TOKEN")
        researcher, planner = OpenAIResearcher.from_openai(), Planner.from_openai()
        reviewer, ci_watcher = GitHubReviewer(GitHubClient(token)), live_ci_watcher(token)
    else:
        raise ValueError("REPO_SURGEON_MODE must be 'mock' or 'real'")
    return Orchestrator(store, events, sandbox, scout, researcher, planner,
        Surgeon(codex, verifier, events), reviewer, ci_watcher)


app = FastAPI(title="Repo Surgeon")
store, events = InMemoryJobStore(), EventBus()
orchestrator = build_orchestrator(store=store, events=events)

# asyncio only holds a *weak* reference to a task created via create_task —
# with nothing else referencing it, the task is eligible for garbage
# collection mid-run and the job silently stops advancing (typically noticed
# during the long-running scouting stage, which has the most await points and
# elapsed time for GC to strike). Keeping a strong reference here, and
# dropping it via the done-callback once the job finishes, is the standard
# fix: https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
_background_jobs: set[asyncio.Task] = set()


class CreateJob(BaseModel): repo_url: str


@app.post("/jobs")
async def create_job(request: CreateJob) -> dict[str, str]:
    job = store.create(request.repo_url)
    task = asyncio.create_task(orchestrator.run(job.id))
    _background_jobs.add(task)
    task.add_done_callback(_background_jobs.discard)
    return {"job_id": job.id}


@app.get("/jobs")
async def list_jobs() -> list[dict]:
    return [{"id": j.id, "repo_url": j.repo_url, "state": j.state, "error": j.error} for j in store.list()]


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = store.get(job_id)
    if not job: raise HTTPException(404, "Job not found")
    return {"id": job.id, "repo_url": job.repo_url, "state": job.state, "results": job.results, "prs": job.prs,
            "error": job.error, "profile": job.profile.model_dump(mode="json") if job.profile else None,
            "plan": job.plan.model_dump(mode="json") if job.plan else None}


@app.get("/jobs/{job_id}/events")
async def get_events(job_id: str) -> StreamingResponse:
    if not store.get(job_id): raise HTTPException(404, "Job not found")
    async def stream():
        async for event in events.subscribe(job_id): yield f"data: {json.dumps(event.model_dump(mode='json'))}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")


# --- Live pipeline transparency ------------------------------------------
# Full log lines (not just the coarse stage events already on /jobs/{id}/events)
# and the per-stage data-flow dumps written to test_results/, both scoped to
# one job so the real dashboard can render them live during a run.

@app.get("/jobs/{job_id}/logs/stream")
async def job_logs_stream(job_id: str, after: int = 0) -> StreamingResponse:
    if not store.get(job_id):
        raise HTTPException(404, "Job not found")
    async def stream():
        cursor = after
        while True:
            # Every pipeline log line is written "[job_id] ...", so filtering
            # on that substring scopes a global handler to this one job
            # without threading job_id through every logger.info() call.
            for entry in live_logs.since(cursor):
                cursor = entry["seq"]
                if job_id in entry["message"]:
                    yield f"data: {json.dumps(entry)}\n\n"
            await asyncio.sleep(0.3)
    return StreamingResponse(stream(), media_type="text/event-stream")


def _trace_job_dir(job_id: str) -> Path:
    if not store.get(job_id):
        raise HTTPException(404, "Job not found")
    return Path(os.getenv("REPO_SURGEON_TRACE_DIR", "test_results")) / job_id


@app.get("/jobs/{job_id}/trace")
async def job_trace_list(job_id: str) -> dict:
    root = _trace_job_dir(job_id)
    if not root.is_dir():
        return {"files": []}
    return {"files": sorted(p.name for p in root.iterdir() if p.suffix == ".json")}


@app.get("/jobs/{job_id}/trace/{filename}")
async def job_trace_file(job_id: str, filename: str) -> dict:
    root = _trace_job_dir(job_id)
    # Strip any path components from the filename before joining: job_id is
    # already validated against the store, this keeps the join from escaping
    # the job's own trace directory no matter what filename is requested.
    path = root / Path(filename).name
    if not path.is_file():
        raise HTTPException(404, "Trace file not found")
    return json.loads(path.read_text(encoding="utf-8"))

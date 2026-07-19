from __future__ import annotations
import asyncio
import json
import logging
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from .codex_runner import MockCodexRunner, RealCodexRunner
from .ci import live_ci_watcher
from .events import EventBus
from .jobstore import InMemoryJobStore
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
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
logging.getLogger("repo_surgeon").setLevel(logging.INFO)


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
        scout, verifier, codex = RealScout(runner, registry), RealVerifier(registry, runner), RealCodexRunner()
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


class CreateJob(BaseModel): repo_url: str


@app.post("/jobs")
async def create_job(request: CreateJob) -> dict[str, str]:
    job = store.create(request.repo_url); asyncio.create_task(orchestrator.run(job.id)); return {"job_id": job.id}


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

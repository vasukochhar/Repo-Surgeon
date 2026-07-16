from __future__ import annotations
import asyncio
import json
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from .codex_runner import MockCodexRunner, RealCodexRunner
from .events import EventBus
from .jobstore import InMemoryJobStore
from .mocks import MockResearcher, MockReviewer, MockSandbox, MockScout, MockVerifier
from .orchestrator import Orchestrator
from .planner import Planner
from .sandbox import AsyncCommandRunner, RealSandbox, SandboxedCommandRunner
from .scout import ProfileRegistry, RealScout
from .surgeon import Surgeon
from .verifier import RealVerifier


def build_orchestrator(mode: str | None = None, store: InMemoryJobStore | None = None,
                       events: EventBus | None = None) -> Orchestrator:
    mode = (mode or os.getenv("REPO_SURGEON_MODE", "mock")).lower()
    store, events = store or InMemoryJobStore(), events or EventBus()
    if mode == "mock":
        sandbox, scout, verifier, codex = MockSandbox(), MockScout(), MockVerifier(), MockCodexRunner()
    elif mode == "real":
        host_runner, registry = AsyncCommandRunner(), ProfileRegistry()
        sandbox = RealSandbox(runner=host_runner)
        runner = SandboxedCommandRunner(sandbox)
        scout, verifier, codex = RealScout(runner, registry), RealVerifier(registry, runner), RealCodexRunner()
    else:
        raise ValueError("REPO_SURGEON_MODE must be 'mock' or 'real'")
    return Orchestrator(store, events, sandbox, scout, MockResearcher(), Planner(),
        Surgeon(codex, verifier, events), MockReviewer())


app = FastAPI(title="Repo Surgeon")
store, events = InMemoryJobStore(), EventBus()
orchestrator = build_orchestrator(store=store, events=events)


class CreateJob(BaseModel): repo_url: str


@app.post("/jobs")
async def create_job(request: CreateJob) -> dict[str, str]:
    job = store.create(request.repo_url); asyncio.create_task(orchestrator.run(job.id)); return {"job_id": job.id}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = store.get(job_id)
    if not job: raise HTTPException(404, "Job not found")
    return {"id": job.id, "repo_url": job.repo_url, "state": job.state, "results": job.results, "prs": job.prs, "error": job.error}


@app.get("/jobs/{job_id}/events")
async def get_events(job_id: str) -> StreamingResponse:
    if not store.get(job_id): raise HTTPException(404, "Job not found")
    async def stream():
        async for event in events.subscribe(job_id): yield f"data: {json.dumps(event.model_dump(mode='json'))}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")

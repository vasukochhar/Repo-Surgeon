from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .codex_runner import MockCodexRunner
from .events import EventBus
from .jobstore import InMemoryJobStore
from .mocks import MockResearcher, MockReviewer, MockSandbox, MockScout, MockVerifier
from .orchestrator import Orchestrator
from .planner import Planner
from .surgeon import Surgeon

app = FastAPI(title="Repo Surgeon")
store, events = InMemoryJobStore(), EventBus()
orchestrator = Orchestrator(store, events, MockSandbox(), MockScout(), MockResearcher(), Planner(),
    Surgeon(MockCodexRunner(), MockVerifier(), events), MockReviewer())


class CreateJob(BaseModel):
    repo_url: str


@app.post("/jobs")
async def create_job(request: CreateJob) -> dict[str, str]:
    job = store.create(request.repo_url)
    asyncio.create_task(orchestrator.run(job.id))
    return {"job_id": job.id}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"id": job.id, "repo_url": job.repo_url, "state": job.state, "results": job.results, "prs": job.prs, "error": job.error}


@app.get("/jobs/{job_id}/events")
async def get_events(job_id: str) -> StreamingResponse:
    if not store.get(job_id):
        raise HTTPException(404, "Job not found")
    async def stream():
        async for event in events.subscribe(job_id):
            yield f"data: {json.dumps(event.model_dump(mode='json'))}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")

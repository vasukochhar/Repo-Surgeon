from fastapi.testclient import TestClient

from repo_surgeon.app import build_orchestrator
from repo_surgeon.events import EventBus
from repo_surgeon.jobstore import InMemoryJobStore


def _make_app():
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    store, events = InMemoryJobStore(), EventBus()
    orchestrator = build_orchestrator("mock", store=store, events=events)
    app = FastAPI()

    class CreateJob(BaseModel):
        repo_url: str

    @app.post("/jobs")
    async def create_job(request: CreateJob) -> dict:
        job = store.create(request.repo_url)
        await orchestrator.run(job.id)
        return {"job_id": job.id}

    @app.get("/jobs")
    async def list_jobs() -> list[dict]:
        return [{"id": j.id, "repo_url": j.repo_url, "state": j.state, "error": j.error} for j in store.list()]

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict:
        job = store.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return {"id": job.id, "repo_url": job.repo_url, "state": job.state, "results": job.results,
                "prs": job.prs, "error": job.error,
                "profile": job.profile.model_dump(mode="json") if job.profile else None,
                "plan": job.plan.model_dump(mode="json") if job.plan else None}

    return app


def test_jobs_list_and_detail_include_profile_and_plan():
    client = TestClient(_make_app())
    created = client.post("/jobs", json={"repo_url": "https://example.invalid/demo.git"})
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    listing = client.get("/jobs")
    assert listing.status_code == 200
    assert any(job["id"] == job_id for job in listing.json())

    detail = client.get(f"/jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["state"] == "done"
    assert body["profile"] is not None and body["profile"]["language"] == "Python"
    assert body["plan"] is not None and isinstance(body["plan"]["items"], list)


def test_get_job_404_for_unknown_id():
    client = TestClient(_make_app())
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404

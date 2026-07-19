from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from .contracts import PRResult, RepoProfile, ResearchMetrics, SurgeonResult, UpgradePlan


class JobState(str, Enum):
    QUEUED = "queued"
    SCOUTING = "scouting"
    RESEARCHING = "researching"
    PLANNING = "planning"
    OPERATING = "operating"
    REVIEWING = "reviewing"
    WATCHING_CI = "watching_ci"
    DONE = "done"
    NEEDS_HUMAN = "needs_human"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    repo_url: str
    state: JobState = JobState.QUEUED
    profile: RepoProfile | None = None
    research_metrics: ResearchMetrics | None = None
    stage_durations: dict[str, float] = field(default_factory=dict)
    plan: UpgradePlan | None = None
    results: list[SurgeonResult] = field(default_factory=list)
    prs: list[PRResult] = field(default_factory=list)
    error: str | None = None


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, repo_url: str) -> Job:
        job = Job(id=str(uuid4()), repo_url=repo_url)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return list(self._jobs.values())

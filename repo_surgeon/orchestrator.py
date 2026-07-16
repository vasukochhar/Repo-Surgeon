from __future__ import annotations

from pathlib import Path

from .contracts import Event, PRRequest
from .events import EventBus
from .interfaces import ResearcherService, ReviewerService, SandboxClient, ScoutService
from .jobstore import InMemoryJobStore, Job, JobState
from .planner import Planner
from .surgeon import Surgeon


class Orchestrator:
    def __init__(self, store: InMemoryJobStore, events: EventBus, sandbox: SandboxClient, scout: ScoutService,
                 researcher: ResearcherService, planner: Planner, surgeon: Surgeon, reviewer: ReviewerService) -> None:
        self.store, self.events, self.sandbox, self.scout, self.researcher = store, events, sandbox, scout, researcher
        self.planner, self.surgeon, self.reviewer = planner, surgeon, reviewer

    async def run(self, job_id: str, workdir: Path | None = None) -> Job:
        job = self.store.get(job_id)
        if not job:
            raise KeyError(job_id)
        owned_workspace = workdir is None
        try:
            workdir = workdir or await self.sandbox.clone(job.repo_url)
            job.profile = await self._stage(job, JobState.SCOUTING, lambda: self.scout.profile(workdir))
            changes = await self._stage(job, JobState.RESEARCHING, lambda: self.researcher.research(job.profile))
            job.plan = await self._stage(job, JobState.PLANNING, lambda: self.planner.build_plan(job.profile, changes))
            await self._stage(job, JobState.OPERATING, self._operate(job, workdir, changes))
            green_items = [item for item in job.plan.items if any(r.item_id == item.id and r.status.value == "green" for r in job.results)]
            job.prs = await self._stage(job, JobState.REVIEWING, lambda: self.reviewer.open_prs(
                PRRequest(items=green_items, branch=f"repo-surgeon/{job.id}", evidence=job.results)))
            await self._stage(job, JobState.WATCHING_CI, self._watch_ci())
            job.state = JobState.NEEDS_HUMAN if any(r.status.value == "needs_human" for r in job.results) else JobState.DONE
            await self._emit(job, "completed")
        except Exception as error:
            job.state, job.error = JobState.FAILED, str(error)
            await self._emit(job, "failed", {"error": job.error})
        finally:
            cleanup_profile = getattr(self.scout, "cleanup_profile", None)
            if cleanup_profile and workdir is not None:
                try:
                    await cleanup_profile(workdir)
                except Exception as cleanup_error:
                    if job.error is None:
                        job.state, job.error = JobState.FAILED, f"profile cleanup failed: {cleanup_error}"
            cleanup = getattr(self.sandbox, "cleanup", None)
            if owned_workspace and cleanup and workdir is not None:
                try:
                    await cleanup(workdir)
                except Exception as cleanup_error:
                    if job.error is None:
                        job.state, job.error = JobState.FAILED, f"workspace cleanup failed: {cleanup_error}"
        return job

    async def _operate(self, job: Job, workdir: Path, changes) -> None:
        assert job.plan is not None
        for item in job.plan.items:
            job.results.append(await self.surgeon.operate(job.id, workdir, item, changes))

    async def _watch_ci(self) -> None:
        """Hook for Mayank's CI watcher integration."""

    async def _stage(self, job: Job, state: JobState, action):
        job.state = state
        await self._emit(job, "started")
        result = await (action() if callable(action) else action)
        await self._emit(job, "completed")
        return result

    async def _emit(self, job: Job, event_type: str, payload: dict | None = None) -> None:
        await self.events.publish(Event(job_id=job.id, stage=job.state.value, type=event_type, payload=payload or {}))

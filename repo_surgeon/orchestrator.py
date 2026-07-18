from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from .contracts import Event, PRRequest
from .events import EventBus
from .interfaces import CIWatcherService, ResearcherService, ReviewerService, SandboxClient, ScoutService
from .jobstore import InMemoryJobStore, Job, JobState
from .planner import Planner
from .surgeon import Surgeon


class Orchestrator:
    def __init__(self, store: InMemoryJobStore, events: EventBus, sandbox: SandboxClient, scout: ScoutService,
                 researcher: ResearcherService, planner: Planner, surgeon: Surgeon, reviewer: ReviewerService,
                 ci_watcher: CIWatcherService | None = None) -> None:
        self.store, self.events, self.sandbox, self.scout, self.researcher = store, events, sandbox, scout, researcher
        self.planner, self.surgeon, self.reviewer = planner, surgeon, reviewer
        self.ci_watcher = ci_watcher

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
                PRRequest(items=green_items, branch=f"repo-surgeon/{job.id}", evidence=job.results,
                          repo_url=job.repo_url, workdir=str(workdir))))
            job.prs = await self._stage(job, JobState.WATCHING_CI, lambda: self._watch_ci(job.prs, workdir))
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
            # Each reviewer branch must contain only this upgrade. Production
            # sandboxes are fresh clones, so restoring HEAD after capturing the
            # item's patch gives the next Surgeon run an equally clean baseline.
            await self._restore_worktree(workdir)

    @staticmethod
    async def _restore_worktree(workdir: Path) -> None:
        probe = await asyncio.to_thread(subprocess.run, ["git", "rev-parse", "--is-inside-work-tree"],
                                        cwd=workdir, text=True, capture_output=True, check=False)
        if probe.returncode:
            return
        restored = await asyncio.to_thread(subprocess.run, ["git", "restore", "--source=HEAD", "--staged", "--worktree", "."],
                                             cwd=workdir, text=True, capture_output=True, check=False)
        if restored.returncode:
            raise RuntimeError(f"could not restore clean item workspace: {restored.stderr.strip()}")
        cleaned = await asyncio.to_thread(subprocess.run, ["git", "clean", "-fd"], cwd=workdir,
                                           text=True, capture_output=True, check=False)
        if cleaned.returncode:
            raise RuntimeError(f"could not clean item workspace: {cleaned.stderr.strip()}")

    async def _watch_ci(self, prs, workdir: Path):
        """Watch real GitHub checks when configured; mock mode remains no-op."""
        if self.ci_watcher is None:
            return prs
        return await self.ci_watcher.watch(prs, workdir)

    async def _stage(self, job: Job, state: JobState, action):
        job.state = state
        await self._emit(job, "started")
        result = await (action() if callable(action) else action)
        await self._emit(job, "completed")
        return result

    async def _emit(self, job: Job, event_type: str, payload: dict | None = None) -> None:
        await self.events.publish(Event(job_id=job.id, stage=job.state.value, type=event_type, payload=payload or {}))

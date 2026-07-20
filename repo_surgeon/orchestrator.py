from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
import traceback
from collections.abc import Iterable
from pathlib import Path

from .contracts import Event, PRRequest
from .events import EventBus
from .interfaces import CIWatcherService, ResearcherService, ReviewerService, SandboxClient, ScoutService
from .jobstore import InMemoryJobStore, Job, JobState
from .planner import Planner
from .surgeon import Surgeon
from .trace import JobTracer, NullTracer, reset_tracer, set_tracer

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, store: InMemoryJobStore, events: EventBus, sandbox: SandboxClient, scout: ScoutService,
                 researcher: ResearcherService, planner: Planner, surgeon: Surgeon, reviewer: ReviewerService,
                 ci_watcher: CIWatcherService | None = None) -> None:
        self.store, self.events, self.sandbox, self.scout, self.researcher = store, events, sandbox, scout, researcher
        self.planner, self.surgeon, self.reviewer = planner, surgeon, reviewer
        self.ci_watcher = ci_watcher
        # Replaced per-job in run(); NullTracer keeps _stage() safe for callers
        # that drive a stage directly in tests.
        self.tracer: JobTracer | NullTracer = NullTracer()
        self._durations: dict[str, float] = {}

    async def run(self, job_id: str, workdir: Path | None = None) -> Job:
        job = self.store.get(job_id)
        if not job:
            raise KeyError(job_id)
        owned_workspace = workdir is None
        tracer = JobTracer(job_id)
        token = set_tracer(tracer)
        self.tracer = tracer
        self._durations = {}
        logger.info("[%s] starting: %s", job_id, job.repo_url)
        tracer.write("job", "input", {"repo_url": job.repo_url, "job_id": job_id,
                                      "mode": os.getenv("REPO_SURGEON_MODE", "mock"),
                                      "planner_model": os.getenv("REPO_SURGEON_MODEL"),
                                      "research_model": os.getenv("REPO_SURGEON_RESEARCH_MODEL"),
                                      "services": {name: type(service).__name__ for name, service in
                                                   (("sandbox", self.sandbox), ("scout", self.scout),
                                                    ("researcher", self.researcher), ("planner", self.planner),
                                                    ("surgeon", self.surgeon), ("reviewer", self.reviewer),
                                                    ("ci_watcher", self.ci_watcher))}})
        try:
            workdir = workdir or await self.sandbox.clone(job.repo_url)
            logger.info("[%s] workspace ready at %s", job_id, workdir)
            tracer.write("clone", "output", {"workdir": workdir, "owned": owned_workspace})
            job.profile = await self._stage(job, JobState.SCOUTING, lambda: self.scout.profile(workdir),
                                            trace_input={"workdir": workdir})
            self._log_profile(job_id, job.profile)
            changes = await self._stage(job, JobState.RESEARCHING, lambda: self.researcher.research(job.profile))
            job.plan = await self._stage(job, JobState.PLANNING, lambda: self.planner.build_plan(job.profile, changes))
            await self._stage(job, JobState.OPERATING, self._operate(job, workdir, changes),
                              trace_input={"plan": job.plan, "changes": changes, "workdir": workdir})
            green_items = [item for item in job.plan.items if any(r.item_id == item.id and r.status.value == "green" for r in job.results)]
            pr_request = PRRequest(items=green_items, branch=f"repo-surgeon/{job.id}", evidence=job.results,
                                   repo_url=job.repo_url, workdir=str(workdir))
            logger.info("[%s] %d/%d item(s) green, opening PR(s) on branch %s",
                        job_id, len(green_items), len(job.plan.items), pr_request.branch)
            job.prs = await self._stage(job, JobState.REVIEWING,
                                        lambda: self.reviewer.open_prs(pr_request),
                                        trace_input=pr_request)
            job.prs = await self._stage(job, JobState.WATCHING_CI, lambda: self._watch_ci(job.prs, workdir),
                                        trace_input={"prs": job.prs, "watcher": type(self.ci_watcher).__name__})
            job.state = JobState.NEEDS_HUMAN if any(r.status.value == "needs_human" for r in job.results) else JobState.DONE
            logger.info("[%s] finished: %s (%d PR(s), %d result(s))", job_id, job.state.value, len(job.prs), len(job.results))
            await self._emit(job, "completed")
        except Exception as error:
            job.state, job.error = JobState.FAILED, str(error)
            logger.exception("[%s] failed", job_id)
            tracer.write("job", "error", {"error": str(error), "type": type(error).__name__,
                                          "state_at_failure": job.state.value,
                                          "traceback": traceback.format_exc()})
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
            tracer.write("job", "summary", {
                "state": job.state.value, "error": job.error, "repo_url": job.repo_url,
                "plan_items": [i.model_dump(mode="json") for i in job.plan.items] if job.plan else [],
                "results": job.results, "prs": job.prs,
                "stage_durations_seconds": self._durations,
            })
            logger.info("[%s] trace written to %s", job_id, tracer.dir.resolve() if tracer.enabled else "(disabled)")
            reset_tracer(token)
        return job

    @staticmethod
    def _log_profile(job_id: str, profile) -> None:
        """Scout's result decides everything downstream — surface it, don't just store it."""
        if profile is None:
            return
        logger.info("[%s] profile: language=%s manager=%s runner=%s | %d dependency(ies), "
                    "%d vulnerability(ies) | baseline %d passed / %d failed, build_ok=%s, coverage=%s",
                    job_id, profile.language, profile.package_manager, profile.test_runner,
                    len(profile.dependencies), len(profile.vulnerabilities),
                    profile.baseline.tests_passed, profile.baseline.tests_failed,
                    profile.baseline.build_ok, profile.baseline.coverage)
        if profile.language == "unsupported":
            logger.warning("[%s] scout could not identify the stack — no manifest at the repo root; "
                           "every later stage will be empty", job_id)
        if not profile.dependencies:
            logger.warning("[%s] scout found no dependencies — nothing to upgrade", job_id)
        for scanner in profile.security_report.scanners:
            logger.info("[%s] scanner %s: %s (%d finding(s)) %s", job_id, scanner.scanner,
                        scanner.status.value, scanner.findings_count, scanner.message)

    async def _operate(self, job: Job, workdir: Path, changes) -> None:
        assert job.plan is not None
        # Scout's bootstrapped test files (see scout/service.py's
        # _bootstrap_tests): scratch fixtures every item verifies against, but
        # never part of any single item's own migration. Passed to Surgeon so
        # CodexRunner keeps them out of each item's diff/PR, and to
        # _restore_worktree so `git clean` between items doesn't delete them
        # out from under the remaining items.
        preserve_paths = job.profile.bootstrap_test_paths if job.profile else []
        for index, item in enumerate(job.plan.items, 1):
            logger.info("[%s] operating %d/%d: %s %s -> %s", job.id, index, len(job.plan.items),
                       item.dependency, item.from_version, item.to_version)
            result = await self.surgeon.operate(job.id, workdir, item, changes, preserve_paths=preserve_paths)
            job.results.append(result)
            logger.info("[%s] item %s: %s after %d iteration(s)", job.id, item.dependency,
                       result.status.value, result.iterations)
            # Each reviewer branch must contain only this upgrade. Production
            # sandboxes are fresh clones, so restoring HEAD after capturing the
            # item's patch gives the next Surgeon run an equally clean baseline.
            await self._restore_worktree(workdir, preserve_paths=preserve_paths)

    @staticmethod
    async def _reclaim_permissions(workdir: Path) -> None:
        """Best-effort ACL reset before touching the tree.

        Codex's own `--sandbox workspace-write` execution runs pytest/PowerShell
        as a *separate* subprocess from this orchestrator, and on Windows that
        can leave directories it created (`.pytest_cache/`, `tests/`) with ACLs
        this process can't traverse — `git clean` below then fails outright with
        "Permission denied" opening the directory, even though it's the same
        Windows user. `icacls /reset` restores inherited default permissions;
        it's a no-op elsewhere and failures here are swallowed since it's purely
        a best-effort unlock before the real (checked) restore/clean below.
        """
        if os.name != "nt":
            return
        await asyncio.to_thread(subprocess.run, ["icacls", str(workdir), "/reset", "/T", "/Q"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                check=False, timeout=60)

    @classmethod
    async def _restore_worktree(cls, workdir: Path, preserve_paths: Iterable[str] = ()) -> None:
        probe = await asyncio.to_thread(subprocess.run, ["git", "rev-parse", "--is-inside-work-tree"],
                                        cwd=workdir, text=True, capture_output=True, encoding="utf-8",
                                        errors="replace", check=False, timeout=30)
        if probe.returncode:
            return
        await cls._reclaim_permissions(workdir)
        restored = await asyncio.to_thread(subprocess.run, ["git", "restore", "--source=HEAD", "--staged", "--worktree", "."],
                                             cwd=workdir, text=True, capture_output=True, encoding="utf-8",
                                             errors="replace", check=False, timeout=30)
        if restored.returncode:
            raise RuntimeError(f"could not restore clean item workspace: {restored.stderr.strip()}")
        # Excluded from the clean scope entirely: on Windows, a cache dir
        # created by a *sandboxed* Codex child process (e.g. `.pytest_cache`
        # from Codex running pytest under its own `--sandbox workspace-write`
        # restricted account) can end up with no ACL entry for this process at
        # all — not even permission to reset the ACL — so `git clean` can
        # never remove it no matter how many times it's retried. These are
        # exactly the regenerable, pipeline-irrelevant paths GENERATED_PATHS
        # (codex_runner.py) and SANDBOX_MANAGED_DIRS (verifier/service.py)
        # already exclude from diffs/change detection, so leaving one behind
        # between items is harmless.
        clean = ["git", "clean", "-fd", "-e", ".pytest_cache", "-e", "**/__pycache__",
                 "-e", ".mypy_cache", "-e", ".ruff_cache", "-e", "node_modules",
                 "-e", ".turbo", "-e", ".next", "-e", "coverage", "-e", ".nyc_output"]
        # Scout's bootstrapped test files must physically survive between
        # items too — they're excluded from the clean scope by their literal
        # path, same as the cache dirs above, so the next item still has a
        # test suite to verify against.
        for path in preserve_paths:
            clean += ["-e", path]
        cleaned = await asyncio.to_thread(subprocess.run, clean, cwd=workdir,
                                           text=True, capture_output=True, encoding="utf-8",
                                           errors="replace", check=False, timeout=30)
        if cleaned.returncode:
            # One retry after a fresh ACL reset: a transient AV/indexer lock on
            # a just-created file is the other common cause of this exact
            # error on Windows, and it usually clears within a second or two.
            await cls._reclaim_permissions(workdir)
            cleaned = await asyncio.to_thread(subprocess.run, clean, cwd=workdir,
                                              text=True, capture_output=True, encoding="utf-8",
                                              errors="replace", check=False, timeout=30)
            if cleaned.returncode:
                raise RuntimeError(f"could not clean item workspace: {cleaned.stderr.strip()}")

    async def _watch_ci(self, prs, workdir: Path):
        """Watch real GitHub checks when configured; mock mode remains no-op."""
        if self.ci_watcher is None:
            return prs
        return await self.ci_watcher.watch(prs, workdir)

    async def _stage(self, job: Job, state: JobState, action, trace_input=None):
        job.state = state
        stage = state.value
        logger.info("[%s] %s: started", job.id, stage)
        if trace_input is not None:
            self.tracer.write(stage, "input", trace_input)
        await self._emit(job, "started")
        started = time.monotonic()
        try:
            result = await (action() if callable(action) else action)
        except Exception as error:
            elapsed = time.monotonic() - started
            logger.error("[%s] %s: FAILED after %.1fs — %s: %s", job.id, stage, elapsed,
                         type(error).__name__, error)
            self.tracer.write(stage, "error", {"error": str(error), "type": type(error).__name__,
                                               "duration_seconds": round(elapsed, 2),
                                               "traceback": traceback.format_exc()})
            raise
        elapsed = time.monotonic() - started
        self._durations[stage] = round(elapsed, 2)
        logger.info("[%s] %s: completed (%.1fs)", job.id, stage, elapsed)
        if result is not None:
            self.tracer.write(stage, "output", result, duration_seconds=round(elapsed, 2))
        await self._emit(job, "completed")
        return result

    async def _emit(self, job: Job, event_type: str, payload: dict | None = None) -> None:
        await self.events.publish(Event(job_id=job.id, stage=job.state.value, type=event_type, payload=payload or {}))

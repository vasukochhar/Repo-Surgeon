from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from .contracts import BreakingChanges, Event, SurgeonResult, SurgeonStatus, UpgradeItem
from .events import EventBus
from .interfaces import CodexRunner, VerifierService
from .trace import current_tracer

logger = logging.getLogger(__name__)


class Surgeon:
    def __init__(self, runner: CodexRunner, verifier: VerifierService, events: EventBus, max_iterations: int = 2) -> None:
        self.runner, self.verifier, self.events, self.max_iterations = runner, verifier, events, max_iterations

    async def operate(self, job_id: str, workdir: Path, item: UpgradeItem, changes: BreakingChanges,
                      preserve_paths: Iterable[str] = ()) -> SurgeonResult:
        tracer = current_tracer()
        files: list[str] = []; latest_patch = ""; failure_context: str | None = None; last_verify = None
        change = changes.changes.get(item.dependency)
        stage = f"operate_{item.dependency}"
        tracer.write(stage, "input", {"item": item, "migration_notes": change,
                                      "has_migration_notes": change is not None,
                                      "workdir": workdir, "max_iterations": self.max_iterations})
        if change is None:
            logger.warning("[%s] %s: no migration notes from research — Codex edits blind", job_id, item.dependency)
        for iteration in range(1, self.max_iterations + 1):
            logger.info("[%s] %s: iteration %d/%d — invoking Codex (failure_context: %s)", job_id, item.dependency,
                       iteration, self.max_iterations,
                       f"{len(failure_context)} chars" if failure_context else "none")
            tracer.write(f"{stage}_iter{iteration}", "codex_input",
                         {"item": item, "migration_notes": change, "failure_context": failure_context})
            try:
                edit = await self.runner.edit(workdir, item, change, failure_context, preserve_paths=preserve_paths)
            except RuntimeError as error:
                # A Codex crash (quota exhausted, apply_patch mismatch, timeout)
                # is an item-level failure, not a job-level one: the remaining
                # plan items are independent and may still succeed. Without
                # this, one crash killed the whole job and threw away every
                # earlier item's finished result.
                logger.warning("[%s] %s: iteration %d Codex crashed — flagging item for a human "
                               "and moving on: %s", job_id, item.dependency, iteration, error)
                tracer.write(f"{stage}_iter{iteration}", "codex_error", {"error": str(error)})
                result = SurgeonResult(item_id=item.id, status=SurgeonStatus.NEEDS_HUMAN, iterations=iteration,
                    files_changed=list(dict.fromkeys(files)), patch=latest_patch, verification=last_verify)
                tracer.write(stage, "output", result)
                return result
            files.extend(edit.files_changed)
            logger.info("[%s] %s: iteration %d Codex edit touched %d file(s) %s, verifying",
                       job_id, item.dependency, iteration, len(edit.files_changed), edit.files_changed)
            if not edit.files_changed:
                logger.warning("[%s] %s: iteration %d — Codex changed nothing; verify will re-test "
                               "an unmodified tree", job_id, item.dependency, iteration)
            tracer.write(f"{stage}_iter{iteration}", "codex_output", edit)
            # Real runners return a snapshot of the working-tree diff. The newest
            # snapshot is apply-able by the GitHub reviewer; concatenating snapshots is not.
            if edit.patch:
                latest_patch = edit.patch
            verify = await self.verifier.verify(item, workdir)
            last_verify = verify
            logger.info("[%s] %s: iteration %d verify %s (%d passed, %d failed, newly failing: %s, "
                       "build_ok=%s, coverage %s -> %s, mutation=%s)", job_id, item.dependency, iteration,
                       "PASSED" if verify.passed else "FAILED", verify.tests_passed, verify.tests_failed,
                       verify.newly_failing_tests or "none", verify.build_ok,
                       verify.coverage_before, verify.coverage_after,
                       verify.mutation_report.score if verify.mutation_report else None)
            if not verify.passed:
                logger.info("[%s] %s: iteration %d failure context fed back to Codex:\n%s", job_id,
                           item.dependency, iteration, verify.concise_failure_context or verify.logs[-800:])
            tracer.write(f"{stage}_iter{iteration}", "verify_output", verify)
            await self.events.publish(Event(job_id=job_id, stage="operating", type="iteration",
                payload={"item_id": item.id, "iteration": iteration, "passed": verify.passed,
                    "tests_passed": verify.tests_passed, "tests_failed": verify.tests_failed,
                    "newly_failing_tests": verify.newly_failing_tests,
                    "test_quality_score": verify.test_quality_score,
                    "mutation_score": verify.mutation_report.score if verify.mutation_report else None}))
            if verify.passed:
                result = SurgeonResult(item_id=item.id, status=SurgeonStatus.GREEN, iterations=iteration,
                    files_changed=list(dict.fromkeys(files)), patch=latest_patch, verification=verify)
                logger.info("[%s] %s: GREEN after %d iteration(s)", job_id, item.dependency, iteration)
                tracer.write(stage, "output", result)
                return result
            failure_context = verify.logs
        logger.info("[%s] %s: needs_human after %d iterations", job_id, item.dependency, self.max_iterations)
        result = SurgeonResult(item_id=item.id, status=SurgeonStatus.NEEDS_HUMAN, iterations=self.max_iterations,
            files_changed=list(dict.fromkeys(files)), patch=latest_patch, verification=last_verify)
        tracer.write(stage, "output", result)
        return result

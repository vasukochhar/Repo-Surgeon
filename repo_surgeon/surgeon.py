from __future__ import annotations

import logging
from pathlib import Path

from .contracts import BreakingChanges, Event, SurgeonResult, SurgeonStatus, UpgradeItem
from .events import EventBus
from .interfaces import CodexRunner, VerifierService

logger = logging.getLogger(__name__)


class Surgeon:
    def __init__(self, runner: CodexRunner, verifier: VerifierService, events: EventBus, max_iterations: int = 5) -> None:
        self.runner, self.verifier, self.events, self.max_iterations = runner, verifier, events, max_iterations

    async def operate(self, job_id: str, workdir: Path, item: UpgradeItem, changes: BreakingChanges) -> SurgeonResult:
        files: list[str] = []; latest_patch = ""; failure_context: str | None = None; last_verify = None
        for iteration in range(1, self.max_iterations + 1):
            logger.info("[%s] %s: iteration %d/%d — invoking Codex", job_id, item.dependency,
                       iteration, self.max_iterations)
            edit = await self.runner.edit(workdir, item, changes.changes.get(item.dependency), failure_context)
            files.extend(edit.files_changed)
            logger.info("[%s] %s: iteration %d Codex edit touched %d file(s), verifying",
                       job_id, item.dependency, iteration, len(edit.files_changed))
            # Real runners return a snapshot of the working-tree diff. The newest
            # snapshot is apply-able by the GitHub reviewer; concatenating snapshots is not.
            if edit.patch:
                latest_patch = edit.patch
            verify = await self.verifier.verify(item, workdir)
            last_verify = verify
            logger.info("[%s] %s: iteration %d verify %s (%d passed, %d failed)", job_id, item.dependency,
                       iteration, "PASSED" if verify.passed else "failed", verify.tests_passed, verify.tests_failed)
            await self.events.publish(Event(job_id=job_id, stage="operating", type="iteration",
                payload={"item_id": item.id, "iteration": iteration, "passed": verify.passed,
                    "tests_passed": verify.tests_passed, "tests_failed": verify.tests_failed,
                    "newly_failing_tests": verify.newly_failing_tests,
                    "test_quality_score": verify.test_quality_score,
                    "mutation_score": verify.mutation_report.score if verify.mutation_report else None}))
            if verify.passed:
                return SurgeonResult(item_id=item.id, status=SurgeonStatus.GREEN, iterations=iteration,
                    files_changed=list(dict.fromkeys(files)), patch=latest_patch, verification=verify)
            failure_context = verify.logs
        logger.info("[%s] %s: needs_human after %d iterations", job_id, item.dependency, self.max_iterations)
        return SurgeonResult(item_id=item.id, status=SurgeonStatus.NEEDS_HUMAN, iterations=self.max_iterations,
            files_changed=list(dict.fromkeys(files)), patch=latest_patch, verification=last_verify)

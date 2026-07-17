from __future__ import annotations

from pathlib import Path

from .contracts import BreakingChanges, Event, SurgeonResult, SurgeonStatus, UpgradeItem
from .events import EventBus
from .interfaces import CodexRunner, VerifierService


class Surgeon:
    def __init__(self, runner: CodexRunner, verifier: VerifierService, events: EventBus, max_iterations: int = 5) -> None:
        self.runner, self.verifier, self.events, self.max_iterations = runner, verifier, events, max_iterations

    async def operate(self, job_id: str, workdir: Path, item: UpgradeItem, changes: BreakingChanges) -> SurgeonResult:
        files: list[str] = []; patches: list[str] = []; failure_context: str | None = None
        for iteration in range(1, self.max_iterations + 1):
            edit = await self.runner.edit(workdir, item, changes.changes.get(item.dependency), failure_context)
            files.extend(edit.files_changed); patches.append(edit.patch)
            verify = await self.verifier.verify(item, workdir)
            await self.events.publish(Event(job_id=job_id, stage="operating", type="iteration",
                payload={"item_id": item.id, "iteration": iteration, "passed": verify.passed,
                    "tests_passed": verify.tests_passed, "tests_failed": verify.tests_failed,
                    "newly_failing_tests": verify.newly_failing_tests,
                    "test_quality_score": verify.test_quality_score,
                    "mutation_score": verify.mutation_report.score if verify.mutation_report else None}))
            if verify.passed:
                return SurgeonResult(item_id=item.id, status=SurgeonStatus.GREEN, iterations=iteration,
                    files_changed=list(dict.fromkeys(files)), patch="\n".join(patches))
            failure_context = verify.logs
        return SurgeonResult(item_id=item.id, status=SurgeonStatus.NEEDS_HUMAN, iterations=self.max_iterations,
            files_changed=list(dict.fromkeys(files)), patch="\n".join(patches))

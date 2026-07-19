from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from .contracts import BreakingChanges, ChangeDetail, Event, SurgeonResult, SurgeonStatus, UpgradeItem, VerifyResult
from .events import EventBus
from .interfaces import CodexRunner, VerifierService
from .research.budget import ResearchContextBudgeter
from .research.config import ResearchConfig

logger = logging.getLogger(__name__)


class Surgeon:
    def __init__(self, runner: CodexRunner, verifier: VerifierService, events: EventBus, max_iterations: int = 5,
                 research_escalator: Callable[[ChangeDetail], Awaitable[ChangeDetail]] | None = None) -> None:
        self.runner, self.verifier, self.events, self.max_iterations = runner, verifier, events, max_iterations
        self.research_escalator = research_escalator

    async def operate(self, job_id: str, workdir: Path, item: UpgradeItem, changes: BreakingChanges) -> SurgeonResult:
        files: list[str] = []; latest_patch = ""; failure_context: str | None = None; last_verify = None
        for iteration in range(1, self.max_iterations + 1):
            logger.info("[%s] %s: iteration %d/%d — invoking Codex", job_id, item.dependency,
                       iteration, self.max_iterations)
            card = changes.changes.get(item.dependency)
            if card:
                maximum = ResearchConfig.from_env().surgeon_max_tokens
                card, tokens = ResearchContextBudgeter().surgeon_card(card, maximum)
                changes.metrics.surgeon_context_tokens[item.dependency] = tokens
                if tokens > maximum:
                    changes.changes[item.dependency] = card.model_copy(update={
                        "research_status": "budget_exceeded", "truncated": True,
                        "truncation_reason": "irreducible Surgeon context exceeds absolute limit"})
                    return SurgeonResult(item_id=item.id, status=SurgeonStatus.NEEDS_HUMAN, iterations=0,
                        verification=VerifyResult(item_id=item.id, regression_aware=True,
                            test_execution_failed=True,
                            logs="Research context exceeds the configured Surgeon maximum; no edit was attempted."))
            edit = await self.runner.edit(workdir, item, card, failure_context)
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
            if (card and card.upgrade_type == "patch" and self.research_escalator and
                    (card.research_status == "metadata_only" or
                     (card.research_status == "cached" and not card.research_required))):
                try:
                    changes.changes[item.dependency] = await self.research_escalator(card)
                except Exception as error:
                    logger.warning("[%s] %s: patch research escalation failed: %s",
                                   job_id, item.dependency, type(error).__name__)
            failure_context = verify.logs
        logger.info("[%s] %s: needs_human after %d iterations", job_id, item.dependency, self.max_iterations)
        return SurgeonResult(item_id=item.id, status=SurgeonStatus.NEEDS_HUMAN, iterations=self.max_iterations,
            files_changed=list(dict.fromkeys(files)), patch=latest_patch, verification=last_verify)

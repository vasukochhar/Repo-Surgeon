from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Awaitable, Callable

from . import llm
from .contracts import BreakingChanges, RepoProfile, UpgradeCategory, UpgradePlan
from .trace import current_tracer

logger = logging.getLogger(__name__)

CATEGORY_ORDER = {UpgradeCategory.SECURITY: 0, UpgradeCategory.PATCH: 1,
                  UpgradeCategory.MINOR: 2, UpgradeCategory.MAJOR: 3}
PLAN_TIMEOUT_SECONDS = 120.0
# One UpgradeItem is ~120 tokens of JSON; the plan is capped by the research
# candidate list, so this covers a full plan with reasoning headroom to spare.
PLAN_MAX_OUTPUT_TOKENS = int(os.environ.get("REPO_SURGEON_PLAN_MAX_OUTPUT_TOKENS", "3000"))

# The prompt must spell out these exact field names: naming a schema by class
# name ("UpgradeItem") without defining its shape lets the model invent
# plausible-looking fields (e.g. "current_version" instead of "from_version"),
# which parses as valid JSON but fails UpgradePlan.model_validate every time.
UPGRADE_ITEM_SCHEMA = (
    '{"id": "string, unique per item", "dependency": "string, package name", '
    '"from_version": "string, current version", "to_version": "string, target version", '
    '"category": "one of: security, patch, minor, major", '
    '"risk": "number between 0 and 1, higher is riskier", '
    '"rationale": "short string explaining the upgrade", '
    '"breaking_change_ref": "string URL or null"}'
)


class Planner:
    def __init__(self, responder: Callable[[str], Awaitable[str]] | None = None) -> None:
        self._responder = responder

    @classmethod
    def from_openai(cls, model: str | None = None) -> "Planner":
        """Create the production planner; keep the default constructor mock-first."""
        selected_model = model or os.environ.get("REPO_SURGEON_MODEL", "gpt-5.6-sol")

        async def respond(prompt: str) -> str:
            # Shares the pacing gate with the Researcher, so plan and research
            # calls can never stack up into a burst against the same rate limit.
            return await llm.respond(stage="plan", model=selected_model, prompt=prompt,
                                     max_output_tokens=PLAN_MAX_OUTPUT_TOKENS)
        return cls(respond)

    async def build_plan(self, profile: RepoProfile, changes: BreakingChanges) -> UpgradePlan:
        tracer = current_tracer()
        view = self._planner_view(profile)
        tracer.write("plan", "input", {"planner_view": view, "changes": changes,
                                       "live_model": self._responder is not None})
        if self._responder is None:
            plan = self._fallback_plan(profile, changes)
            logger.info("no live planner configured — fallback plan with %d item(s)", len(plan.items))
            tracer.write("plan", "output", plan, source="fallback")
            return plan
        prompt = (
            'Return strict JSON, no markdown, matching exactly {"items": [UpgradeItem, ...]} '
            f"where each UpgradeItem has exactly this shape: {UPGRADE_ITEM_SCHEMA}. "
            "Use only these exact field names — do not rename or add fields. "
            "Risk-score and order these upgrades (security first, then patch, minor, major). "
            f"Profile: {json.dumps(view)}; "
            f"changes: {changes.model_dump_json()}"
        )
        last_error: Exception | None = None
        raw = ""
        for attempt in range(1, 3):
            try:
                raw = await asyncio.wait_for(self._responder(prompt), timeout=PLAN_TIMEOUT_SECONDS)
                plan = self._sort(UpgradePlan.model_validate(json.loads(self._json_object(raw))))
                logger.info("plan built on attempt %d: %d item(s) — %s", attempt, len(plan.items),
                            [f"{i.dependency} {i.from_version}->{i.to_version} ({i.category.value}, risk {i.risk})"
                             for i in plan.items])
                tracer.write("plan", "output", plan, source="model", attempt=attempt)
                return plan
            except (json.JSONDecodeError, ValueError) as error:
                logger.warning("plan attempt %d returned invalid JSON: %s", attempt, error)
                last_error = error
            except asyncio.TimeoutError as error:
                logger.warning("plan attempt %d timed out after %.0fs", attempt, PLAN_TIMEOUT_SECONDS)
                last_error = error
                break
        tracer.write("plan", "error", {"raw_response": raw, "error": str(last_error)})
        raise ValueError("Planner returned invalid UpgradePlan JSON") from last_error

    @staticmethod
    def _json_object(value: str) -> str:
        value = value.strip()
        if value.startswith("```"):
            value = value.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return value

    @staticmethod
    def _planner_view(profile: RepoProfile) -> dict:
        """Slim the profile for the prompt: raw scanner/command output can exceed
        100K tokens and the planner only needs the structured facts."""
        return {
            "language": profile.language,
            "package_manager": profile.package_manager,
            "test_runner": profile.test_runner,
            "baseline": {"tests_passed": profile.baseline.tests_passed,
                         "tests_failed": profile.baseline.tests_failed,
                         "build_ok": profile.baseline.build_ok,
                         "failing_tests": profile.baseline.failing_tests},
            "dependencies": [{"name": d.name, "version": d.version, "latest_version": d.latest_version,
                              "direct": d.direct, "ecosystem": d.ecosystem}
                             for d in profile.dependencies],
            "vulnerabilities": [{"dependency": v.dependency, "severity": v.severity,
                                 "identifier": v.identifier, "package_version": v.package_version,
                                 "fixed_versions": v.fixed_versions, "fix_available": v.fix_available}
                                for v in profile.vulnerabilities],
        }

    def _fallback_plan(self, profile: RepoProfile, changes: BreakingChanges) -> UpgradePlan:
        from .contracts import UpgradeItem
        vulnerable = {v.dependency for v in profile.vulnerabilities}
        items = [UpgradeItem(id=f"upgrade-{index}", dependency=name, from_version=change.current,
                 to_version=change.target, category=UpgradeCategory.SECURITY if name in vulnerable else UpgradeCategory.MINOR,
                 risk=0.3, rationale="Mock-first fallback plan", breaking_change_ref=change.changelog_url)
                 for index, (name, change) in enumerate(changes.changes.items(), 1)]
        return self._sort(UpgradePlan(items=items))

    def _sort(self, plan: UpgradePlan) -> UpgradePlan:
        return UpgradePlan(items=sorted(plan.items, key=lambda i: (CATEGORY_ORDER[i.category], i.risk)))

    async def diagnose_ci_failure(self, logs: str) -> str:
        if self._responder:
            return await self._responder(f"Give a targeted fix instruction for CI logs:\n{logs}")
        return f"Inspect the failing test and its dependency migration. CI logs: {logs[:500]}"

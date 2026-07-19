from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Awaitable, Callable

from .contracts import BreakingChanges, RepoProfile, UpgradeCategory, UpgradePlan

logger = logging.getLogger(__name__)

CATEGORY_ORDER = {UpgradeCategory.SECURITY: 0, UpgradeCategory.PATCH: 1,
                  UpgradeCategory.MINOR: 2, UpgradeCategory.MAJOR: 3}
PLAN_TIMEOUT_SECONDS = 120.0

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
        client = None

        async def respond(prompt: str) -> str:
            nonlocal client
            if client is None:
                from openai import AsyncOpenAI
                # Keep the SDK's default retry/backoff: a 429 can mean either
                # "out of quota" (retrying never helps) or "over the per-minute
                # token rate" (retrying in a few seconds succeeds) — the SDK
                # can't tell them apart either, so it backs off and retries both.
                # The outer asyncio.wait_for timeout is what actually bounds the
                # worst case, so retries here can never turn into a silent hang.
                client = AsyncOpenAI()
            started = time.monotonic()
            response = await client.responses.create(model=selected_model, input=prompt)
            logger.info("plan call to %s finished in %.1fs", selected_model, time.monotonic() - started)
            return response.output_text
        return cls(respond)

    async def build_plan(self, profile: RepoProfile, changes: BreakingChanges) -> UpgradePlan:
        if self._responder is None:
            return self._fallback_plan(profile, changes)
        prompt = (
            'Return strict JSON, no markdown, matching exactly {"items": [UpgradeItem, ...]} '
            f"where each UpgradeItem has exactly this shape: {UPGRADE_ITEM_SCHEMA}. "
            "Use only these exact field names — do not rename or add fields. "
            "Risk-score and order these upgrades (security first, then patch, minor, major). "
            f"Profile: {json.dumps(self._planner_view(profile))}; "
            f"changes: {changes.model_dump_json()}"
        )
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                raw = await asyncio.wait_for(self._responder(prompt), timeout=PLAN_TIMEOUT_SECONDS)
                plan = self._sort(UpgradePlan.model_validate(json.loads(self._json_object(raw))))
                logger.info("plan built: %d item(s) on attempt %d", len(plan.items), attempt)
                return plan
            except (json.JSONDecodeError, ValueError) as error:
                logger.warning("plan attempt %d returned invalid JSON: %s", attempt, error)
                last_error = error
            except asyncio.TimeoutError as error:
                logger.warning("plan attempt %d timed out after %.0fs", attempt, PLAN_TIMEOUT_SECONDS)
                last_error = error
                break
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

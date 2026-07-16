from __future__ import annotations

import json
import os
from typing import Awaitable, Callable

from .contracts import BreakingChanges, RepoProfile, UpgradeCategory, UpgradePlan

CATEGORY_ORDER = {UpgradeCategory.SECURITY: 0, UpgradeCategory.PATCH: 1,
                  UpgradeCategory.MINOR: 2, UpgradeCategory.MAJOR: 3}


class Planner:
    def __init__(self, responder: Callable[[str], Awaitable[str]] | None = None) -> None:
        self._responder = responder

    @classmethod
    def from_openai(cls, model: str | None = None) -> "Planner":
        """Create the production planner; keep the default constructor mock-first."""
        from openai import AsyncOpenAI
        client = AsyncOpenAI()
        selected_model = model or os.environ.get("REPO_SURGEON_MODEL", "gpt-5.6")

        async def respond(prompt: str) -> str:
            response = await client.responses.create(model=selected_model, input=prompt)
            return response.output_text
        return cls(respond)

    async def build_plan(self, profile: RepoProfile, changes: BreakingChanges) -> UpgradePlan:
        if self._responder is None:
            return self._fallback_plan(profile, changes)
        prompt = ("Return strict JSON matching {items:[UpgradeItem]}. Risk-score and order "
                  f"these upgrades. Profile: {profile.model_dump_json()}; changes: {changes.model_dump_json()}")
        last_error: Exception | None = None
        for _ in range(2):
            try:
                plan = UpgradePlan.model_validate(json.loads(await self._responder(prompt)))
                return self._sort(plan)
            except (json.JSONDecodeError, ValueError) as error:
                last_error = error
        raise ValueError("Planner returned invalid UpgradePlan JSON") from last_error

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

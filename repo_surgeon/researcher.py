"""Evidence-grounded dependency migration research."""
from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable

from .contracts import BreakingChanges, Dependency, RepoProfile

ResearchResponder = Callable[[str], Awaitable[str]]


class OpenAIResearcher:
    """Use Responses web search to produce migration context for the Surgeon.

    The responder seam keeps this service deterministic in tests and lets callers
    substitute a company-approved research provider if required.
    """

    def __init__(self, responder: ResearchResponder | None = None) -> None:
        self._responder = responder

    @classmethod
    def from_openai(cls, model: str | None = None) -> "OpenAIResearcher":
        selected_model = model or os.environ.get("REPO_SURGEON_MODEL", "gpt-5.6")
        client = None

        async def respond(prompt: str) -> str:
            nonlocal client
            if client is None:
                from openai import AsyncOpenAI
                client = AsyncOpenAI()
            response = await client.responses.create(
                model=selected_model,
                tools=[{"type": "web_search"}],
                input=prompt,
            )
            return response.output_text

        return cls(respond)

    async def research(self, profile: RepoProfile) -> BreakingChanges:
        candidates = self._candidates(profile)
        if not candidates:
            return BreakingChanges()
        if self._responder is None:
            raise RuntimeError(
                "Live research requires OpenAIResearcher.from_openai() and OPENAI_API_KEY. "
                "Use mock mode for an offline demo."
            )
        prompt = self._prompt(candidates)
        response = await self._responder(prompt)
        try:
            research = BreakingChanges.model_validate(json.loads(self._json_object(response)))
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError("Researcher returned invalid BreakingChanges JSON") from error
        expected = {dependency.name: dependency for dependency in candidates}
        # Reject model additions and fill the source list from the primary changelog
        # so each planner item can always cite its research provenance.
        research.changes = {
            name: detail.model_copy(update={
                "sources": list(dict.fromkeys(detail.sources + ([detail.changelog_url] if detail.changelog_url else [])))
            })
            for name, detail in research.changes.items()
            if name in expected and detail.current == expected[name].version
        }
        return research

    @staticmethod
    def _candidates(profile: RepoProfile) -> list[Dependency]:
        vulnerable = {finding.dependency: finding for finding in profile.vulnerabilities}
        candidates: list[Dependency] = []
        for dependency in profile.dependencies:
            fixed = vulnerable.get(dependency.name)
            target = dependency.latest_version
            if fixed and fixed.fix_available and fixed.fixed_versions:
                target = fixed.fixed_versions[0]
            if target and target != dependency.version:
                candidates.append(dependency.model_copy(update={"latest_version": target}))
        return candidates

    @staticmethod
    def _prompt(candidates: list[Dependency]) -> str:
        payload = [candidate.model_dump(mode="json") for candidate in candidates]
        return (
            "Research the following dependency upgrades using authoritative primary sources only: "
            "the project changelog/releases, migration guide, and official issue tracker when relevant. "
            "Return strict JSON and no markdown matching "
            '{"changes":{"package":{"current":"...","target":"...","changelog_url":"https://...",'
            '"migration_notes":"focused actionable notes","known_issues":["..."],"sources":["https://..."]}}}. '
            "Every URL must be a source actually used. Do not invent packages or versions. "
            f"Upgrade candidates: {json.dumps(payload)}"
        )

    @staticmethod
    def _json_object(value: str) -> str:
        value = value.strip()
        if value.startswith("```"):
            value = value.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return value

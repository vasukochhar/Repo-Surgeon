"""Evidence-grounded dependency migration research."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable

from .contracts import BreakingChanges, Dependency, RepoProfile

logger = logging.getLogger(__name__)

ResearchResponder = Callable[[str], Awaitable[str]]

# Research is evidence gathering, not reasoning: run it on the cheap fast tier
# and keep the flagship model for the Planner only.
DEFAULT_RESEARCH_MODEL = "gpt-5.6-luna"
# Cap volume so research cost/latency stays bounded on repos with many findings.
MAX_CANDIDATES = 10
RESEARCH_TIMEOUT_SECONDS = 240.0
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class OpenAIResearcher:
    """Use Responses web search to produce migration context for the Surgeon.

    The responder seam keeps this service deterministic in tests and lets callers
    substitute a company-approved research provider if required.
    """

    def __init__(self, responder: ResearchResponder | None = None) -> None:
        self._responder = responder

    @classmethod
    def from_openai(cls, model: str | None = None) -> "OpenAIResearcher":
        selected_model = model or os.environ.get("REPO_SURGEON_RESEARCH_MODEL", DEFAULT_RESEARCH_MODEL)
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
            response = await client.responses.create(
                model=selected_model,
                # "low": the model needs a version number and a source URL per
                # package, not a deep read of each page — "medium" (the
                # default) pulls enough fetched page content into context to
                # burn tens of thousands of tokens per call for no benefit here.
                tools=[{"type": "web_search", "search_context_size": "low"}],
                input=prompt,
            )
            logger.info("research call to %s finished in %.1fs", selected_model, time.monotonic() - started)
            return response.output_text

        return cls(respond)

    async def research(self, profile: RepoProfile) -> BreakingChanges:
        candidates = self._candidates(profile)
        logger.info("researching %d candidate(s): %s", len(candidates), [c.name for c in candidates])
        if not candidates:
            return BreakingChanges()
        if self._responder is None:
            raise RuntimeError(
                "Live research requires OpenAIResearcher.from_openai() and OPENAI_API_KEY. "
                "Use mock mode for an offline demo."
            )
        prompt = self._prompt(candidates)
        try:
            response = await asyncio.wait_for(self._responder(prompt), timeout=RESEARCH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("research timed out after %.0fs; degrading to no migration notes", RESEARCH_TIMEOUT_SECONDS)
            # Degrade rather than hang: the Planner can still order security bumps
            # without migration notes, and the item simply lacks evidence links.
            return BreakingChanges()
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

        def priority(dependency: Dependency) -> tuple[int, str]:
            finding = vulnerable.get(dependency.name)
            severity = (finding.severity or "").lower() if finding else ""
            return (SEVERITY_RANK.get(severity, 4 if finding else 5), dependency.name)

        return sorted(candidates, key=priority)[:MAX_CANDIDATES]

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

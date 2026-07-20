"""Evidence-grounded dependency migration research."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from collections.abc import Awaitable, Callable

from . import llm
from .contracts import BreakingChanges, Dependency, RepoProfile
from .trace import current_tracer

logger = logging.getLogger(__name__)

ResearchResponder = Callable[..., Awaitable[str]]

# Research is evidence gathering, not reasoning: run it on the cheap fast tier
# and keep the flagship model for the Planner only.
DEFAULT_RESEARCH_MODEL = "gpt-5.6-luna"
# A safety ceiling, not a deliberate cost trim: with batching + concurrent
# batches (below), researching more packages costs wall-clock time, not
# rate-limit risk, so there's no reason to silently drop real repos' upgrades.
# This just stops a pathological case (a lockfile-parsing bug that yields
# thousands of "candidates") from spinning the stage forever.
MAX_CANDIDATES = int(os.environ.get("REPO_SURGEON_MAX_CANDIDATES", "500"))
RESEARCH_TIMEOUT_SECONDS = 240.0
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Web search is the pipeline's heaviest token consumer, and measurement shows
# the weight is almost entirely on the *input* side: a two-package call billed
# 27k input tokens (fetched page content) against 1.2k output. Capping output
# therefore does nearly nothing for rate limiting — what matters is never
# letting one call get large. So the candidate list is split into small
# batches. Batches run concurrently (bounded by llm.py's REPO_SURGEON_LLM_
# CONCURRENCY gate, which also staggers each call's *start* by
# REPO_SURGEON_LLM_MIN_INTERVAL) so a 50-dependency repo finishes in
# roughly (batches / concurrency) call-durations instead of finishing
# batch-by-batch back to back.
RESEARCH_BATCH_SIZE = int(os.environ.get("REPO_SURGEON_RESEARCH_BATCH_SIZE", "3"))

# Output budget per batch. Reasoning tokens are drawn from max_output_tokens
# before any JSON is emitted — an observed 578 of them at "low" effort — so the
# reserve below is what stops a budget sized only for the payload from
# truncating mid-string. Truncation is still detected in llm.respond() and
# retried once at double the budget rather than failing the stage.
RESEARCH_REASONING_RESERVE = int(os.environ.get("REPO_SURGEON_RESEARCH_REASONING_RESERVE", "900"))
RESEARCH_TOKENS_PER_CANDIDATE = int(os.environ.get("REPO_SURGEON_RESEARCH_TOKENS_PER_CANDIDATE", "500"))


def research_token_budget(candidate_count: int) -> int:
    override = os.environ.get("REPO_SURGEON_RESEARCH_MAX_OUTPUT_TOKENS")
    if override:
        return int(override)
    return RESEARCH_REASONING_RESERVE + RESEARCH_TOKENS_PER_CANDIDATE * max(1, candidate_count)


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

        async def respond(prompt: str, max_output_tokens: int | None = None) -> str:
            # Pacing, 429 backoff and token accounting all live in llm.respond()
            # so a rate-limit stall shows up in the log instead of as dead air.
            return await llm.respond(
                stage="research",
                model=selected_model,
                prompt=prompt,
                # "low": the model needs a version number and a source URL per
                # package, not a deep read of each page — "medium" (the
                # default) pulls enough fetched page content into context to
                # burn tens of thousands of tokens per call for no benefit here.
                tools=[{"type": "web_search", "search_context_size": "low"}],
                max_output_tokens=max_output_tokens,
                reasoning={"effort": "low"},
            )

        return cls(respond)

    async def _research_batch(self, batch: list[Dependency], number: int,
                              tracer) -> BreakingChanges | None:
        """One batch, retried once at double the output budget if it truncates.

        Returns None when the batch cannot be salvaged, so the caller can keep
        the packages from other batches instead of losing the whole stage.
        """
        logger.info("research batch %d starting: %s", number, [candidate.name for candidate in batch])
        prompt = self._prompt(batch)
        budget = research_token_budget(len(batch))
        for attempt in (1, 2):
            try:
                response = await asyncio.wait_for(self._ask(prompt, budget),
                                                  timeout=RESEARCH_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning("research batch %d timed out after %.0fs", number, RESEARCH_TIMEOUT_SECONDS)
                tracer.write(f"research_batch{number}", "error",
                             {"timeout_seconds": RESEARCH_TIMEOUT_SECONDS, "attempt": attempt})
                return None
            try:
                return BreakingChanges.model_validate(json.loads(self._json_object(response)))
            except (json.JSONDecodeError, ValueError) as error:
                truncated = not self._json_object(response).rstrip().endswith("}")
                logger.warning("research batch %d attempt %d returned unparseable JSON (%d chars, "
                               "looks %s): %s", number, attempt, len(response),
                               "truncated" if truncated else "malformed", error)
                tracer.write(f"research_batch{number}", "error",
                             {"attempt": attempt, "raw_response": response, "parse_error": str(error),
                              "looks_truncated": truncated, "max_output_tokens": budget})
                if attempt == 1 and truncated:
                    budget *= 2
                    logger.info("research batch %d retrying with max_output_tokens=%d", number, budget)
                    continue
                return None
        return None

    async def _ask(self, prompt: str, max_output_tokens: int) -> str:
        """Call the responder, passing the token budget only if it accepts one.

        Tests inject plain ``async def (prompt)`` stubs; the production responder
        takes a budget. Inspecting once keeps both working without a try/except
        that could swallow a genuine TypeError from inside the responder.
        """
        assert self._responder is not None
        try:
            accepts_budget = len(inspect.signature(self._responder).parameters) > 1
        except (TypeError, ValueError):
            accepts_budget = False
        if accepts_budget:
            return await self._responder(prompt, max_output_tokens)
        return await self._responder(prompt)

    async def research(self, profile: RepoProfile) -> BreakingChanges:
        tracer = current_tracer()
        candidates = self._candidates(profile)
        logger.info("researching %d candidate(s) (cap %d): %s",
                    len(candidates), MAX_CANDIDATES, [c.name for c in candidates])
        tracer.write("research", "input", {
            "candidates": candidates,
            "candidate_count": len(candidates),
            "max_candidates": MAX_CANDIDATES,
            "batch_size": RESEARCH_BATCH_SIZE,
            "max_output_tokens_per_batch": research_token_budget(min(RESEARCH_BATCH_SIZE, len(candidates))),
            "profile_dependencies": len(profile.dependencies),
            "profile_vulnerabilities": len(profile.vulnerabilities),
        })
        if not candidates:
            logger.info("no upgrade candidates — skipping the research call entirely")
            tracer.write("research", "output", BreakingChanges(), skipped="no candidates")
            return BreakingChanges()
        if self._responder is None:
            raise RuntimeError(
                "Live research requires OpenAIResearcher.from_openai() and OPENAI_API_KEY. "
                "Use mock mode for an offline demo."
            )
        batches = [candidates[start:start + RESEARCH_BATCH_SIZE]
                   for start in range(0, len(candidates), RESEARCH_BATCH_SIZE)]
        logger.info("research split into %d batch(es) of <=%d package(s), running concurrently "
                    "(gated by REPO_SURGEON_LLM_CONCURRENCY)", len(batches), RESEARCH_BATCH_SIZE)
        outcomes = await asyncio.gather(
            *(self._research_batch(batch, number, tracer) for number, batch in enumerate(batches, 1)))
        research = BreakingChanges()
        for number, (batch, detail) in enumerate(zip(batches, outcomes), 1):
            names = [candidate.name for candidate in batch]
            if detail is None:
                # One bad batch must not cost the whole stage: the packages it
                # covered simply arrive at the Planner without migration notes.
                logger.warning("research batch %d/%d failed; continuing without notes for %s",
                               number, len(batches), names)
                continue
            logger.info("research batch %d/%d ok: %s", number, len(batches), names)
            research.changes.update(detail.changes)
        expected = {dependency.name: dependency for dependency in candidates}
        # Reject model additions and fill the source list from the primary changelog
        # so each planner item can always cite its research provenance.
        returned = dict(research.changes)
        research.changes = {
            name: detail.model_copy(update={
                "sources": list(dict.fromkeys(detail.sources + ([detail.changelog_url] if detail.changelog_url else [])))
            })
            for name, detail in returned.items()
            if name in expected and detail.current == expected[name].version
        }
        rejected = {
            name: ("not a requested package" if name not in expected
                   else f"current {detail.current!r} != profile {expected[name].version!r}")
            for name, detail in returned.items() if name not in research.changes
        }
        if rejected:
            # Silent today: a model that drifts on every version string yields an
            # empty plan with no explanation anywhere. Name each drop.
            logger.warning("research dropped %d/%d package(s) as unusable: %s",
                           len(rejected), len(returned), rejected)
        logger.info("research kept %d change(s): %s", len(research.changes), sorted(research.changes))
        tracer.write("research", "output", {
            "changes": research, "kept": sorted(research.changes),
            "rejected": rejected, "requested": sorted(expected)})
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

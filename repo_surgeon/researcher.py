"""Registry-first, evidence-grounded dependency migration research."""
from __future__ import annotations
import asyncio, inspect, json, logging, os, random, time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from openai import RateLimitError

from .contracts import BreakingChanges, ChangeDetail, Dependency, RepoProfile, ResearchEvidence, ResearchMetrics
from .model_policy import LUNA_MODEL, luna_only_model
from .research.budget import ResearchContextBudgeter, TokenCounter
from .research.cache import CacheRecord, FileResearchCache, InMemoryResearchCache, cache_key
from .research.config import ResearchConfig
from .research.limiter import shared_research_limiter
from .research.policy import ResearchCandidate, ResearchPolicy
from .research.providers import NpmRegistryProvider, PyPIRegistryProvider
from .research.rate_limits import ResearchRateLimited, classify_rate_limit
from .research.summarizer import DeterministicSummarizer, OpenAISummarizer

logger = logging.getLogger(__name__)
ResearchResponder = Callable[[str], Awaitable[str]]
DEFAULT_RESEARCH_MODEL = LUNA_MODEL


class OpenAIResearcher:
    def __init__(self, responder: ResearchResponder | None = None, providers: dict[str, object] | None = None,
                 cache=None, config: ResearchConfig | None = None, summarizer=None,
                 provider_identifier: str | None = None, limiter=None,
                 sleep_fn=None, random_fn=None) -> None:
        self._responder = responder
        self.providers = providers or {}
        self.cache = cache or InMemoryResearchCache()
        self.config = config or ResearchConfig.from_env()
        self.summarizer = summarizer or DeterministicSummarizer()
        self.provider_identifier = provider_identifier
        self.limiter = limiter or shared_research_limiter(self.config.max_concurrent_research)
        self.sleep_fn = sleep_fn or asyncio.sleep
        self.random_fn = random_fn or random.random
        self.policy = ResearchPolicy()
        self.counter = TokenCounter()
        self.last_metrics = ResearchMetrics()
        self._permanent_rate_limit = None

    @classmethod
    def from_openai(cls, model: str | None = None) -> "OpenAIResearcher":
        selected = luna_only_model(model, environment="REPO_SURGEON_RESEARCH_MODEL")
        client = None
        async def respond(prompt: str) -> str:
            nonlocal client
            if client is None:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(max_retries=0)
            kwargs = {"model": selected,
                "tools": [{"type": "web_search", "search_context_size": "low"}], "input": prompt}
            try:
                supports_structured = "text" in inspect.signature(client.responses.create).parameters
            except (TypeError, ValueError):
                supports_structured = False
            if supports_structured:
                kwargs["text"] = {"format": {"type": "json_schema", "name": "repo_surgeon_research",
                    "strict": False, "schema": BreakingChanges.model_json_schema()}}
            response = await client.responses.create(**kwargs)
            usage = getattr(response, "usage", None)
            if usage:
                respond.last_usage = (getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))
            return response.output_text
        respond.last_usage = (None, None)
        config = ResearchConfig.from_env()
        summarizer = (OpenAISummarizer(config.summarizer_model)
                      if config.summarization_enabled and config.summarizer_model else DeterministicSummarizer())
        return cls(respond, {"pypi": PyPIRegistryProvider(), "npm": NpmRegistryProvider()},
            FileResearchCache(config.cache_location), config, summarizer, provider_identifier=selected)

    async def research(self, profile: RepoProfile) -> BreakingChanges:
        started = time.monotonic()
        metrics = ResearchMetrics(dependency_count=len(profile.dependencies),
                                  configured_batch_size=min(5, max(1, self.config.batch_size)))
        registry_failures = await self._enrich_versions(profile)
        metrics.registry_failures = sorted(registry_failures)
        candidates = self.policy.candidates(profile)
        for item in candidates:
            metrics.candidates_by_type[item.upgrade_type] = metrics.candidates_by_type.get(item.upgrade_type, 0) + 1
        changes: dict[str, ChangeDetail] = {
            dependency.name: ChangeDetail(package=dependency.name,
                ecosystem=dependency.ecosystem or profile.package_manager,
                current=dependency.version, target=dependency.version,
                upgrade_type="unknown", research_required=False, research_status="failed",
                migration_notes="Registry metadata lookup failed; no target version was inferred.")
            for dependency in profile.dependencies if dependency.name in registry_failures
        }
        web_candidates = []
        # Keep the original injectable responder seam useful for legacy callers
        # that did not supply registry providers. Production construction always
        # supplies providers and therefore follows the registry-first policy.
        legacy_responder_only = bool(self._responder and not self.providers)
        for candidate in candidates:
            key = cache_key(self._ecosystem(candidate), candidate.dependency.name,
                            candidate.dependency.version, candidate.target)
            try: cached = self.cache.get(key)
            except Exception: cached = None
            if cached:
                metrics.cache_hits += 1
                changes[candidate.dependency.name] = cached.card.model_copy(update={"research_status": "cached"})
                continue
            metrics.cache_misses += 1
            needs_web = self.policy.requires_web(candidate) or legacy_responder_only
            if needs_web and self._responder:
                web_candidates.append(candidate)
            elif needs_web:
                changes[candidate.dependency.name] = self._status_card(
                    candidate, "deferred", "web research provider unavailable")
                metrics.deferred_packages.append(candidate.dependency.name)
            else:
                changes[candidate.dependency.name] = self._metadata_card(candidate)
                metrics.registry_only += 1

        batch_size = min(5, max(1, self.config.batch_size))
        for offset in range(0, len(web_candidates), batch_size):
            batch = web_candidates[offset:offset + batch_size]
            batch_started = time.monotonic()
            prompt = self._prompt(batch)
            returned_tokens = 0
            provider_input = provider_output = None
            attempted_before = metrics.openai_attempted_calls
            waits_before = metrics.retry_wait_seconds
            metrics.estimated_prompt_tokens += self.counter.count(prompt)
            metrics.web_search_calls += 1
            try:
                raw = await self._call_with_retry(prompt, len(batch), metrics)
                returned_tokens = self.counter.count(raw)
                metrics.estimated_returned_output_tokens += returned_tokens
                metrics.returned_output_tokens += returned_tokens
                usage = getattr(self._responder, "last_usage", (None, None))
                provider_input, provider_output = usage
                if usage[0] is not None:
                    metrics.provider_input_tokens = (metrics.provider_input_tokens or 0) + usage[0]
                if usage[1] is not None:
                    metrics.provider_output_tokens = (metrics.provider_output_tokens or 0) + usage[1]
                parsed = BreakingChanges.model_validate(json.loads(self._json_object(raw)))
                self._accept_batch(batch, parsed, changes)
            except asyncio.TimeoutError:
                for candidate in batch: changes[candidate.dependency.name] = self._status_card(candidate, "failed", "web research timed out")
            except (ValueError, json.JSONDecodeError):
                for candidate in batch: changes[candidate.dependency.name] = self._status_card(candidate, "failed", "invalid research response")
            except ResearchRateLimited as error:
                metrics.final_deferred_count += len(batch)
                metrics.deferred_packages.extend(candidate.dependency.name for candidate in batch)
                for candidate in batch:
                    changes[candidate.dependency.name] = self._status_card(
                        candidate, "deferred", error.decision.safe_message)
            except Exception as error:
                logger.warning("research batch failed: %s", type(error).__name__)
                for candidate in batch:
                    changes[candidate.dependency.name] = self._status_card(
                        candidate, "failed", f"research provider failed ({type(error).__name__})")
            metrics.batches.append({"packages": [candidate.dependency.name for candidate in batch],
                "candidate_count": len(batch),
                "candidates_by_type": {kind: sum(candidate.upgrade_type == kind for candidate in batch)
                    for kind in ("security", "major", "minor", "patch")},
                "estimated_prompt_tokens": self.counter.count(prompt),
                "estimated_returned_structured_tokens": returned_tokens,
                "provider_input_tokens": provider_input, "provider_output_tokens": provider_output,
                "duration_seconds": round(time.monotonic() - batch_started, 4), "web_search_calls": 1,
                "openai_attempts": metrics.openai_attempted_calls - attempted_before,
                "retry_wait_seconds": round(metrics.retry_wait_seconds - waits_before, 4)})

        for candidate in candidates:
            card = changes[candidate.dependency.name]
            card.estimated_tokens = self.counter.count(card.model_dump_json())
            if card.estimated_tokens > self.config.card_target_tokens:
                card = await self._shrink(card, metrics)
                changes[candidate.dependency.name] = card
            if card.research_status in {"researched", "metadata_only"}:
                ttl = self.config.security_cache_ttl_seconds if candidate.security else self.config.normal_cache_ttl_seconds
                record = CacheRecord(card=card, source_urls=card.sources,
                    created_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
                    provider=(self.provider_identifier if card.research_status == "researched"
                              else candidate.dependency.metadata_provider))
                try: self.cache.set(cache_key(self._ecosystem(candidate), candidate.dependency.name,
                    candidate.dependency.version, candidate.target), record)
                except Exception: pass
        metrics.duration_seconds = round(time.monotonic() - started, 4)
        result = BreakingChanges(changes=changes, metrics=metrics)
        self.last_metrics = metrics
        logger.info("research dependencies=%d web_calls=%d cache=%d/%d duration=%.2fs",
                    metrics.dependency_count, metrics.web_search_calls, metrics.cache_hits,
                    metrics.cache_misses, metrics.duration_seconds)
        return result

    async def escalate_after_verification(self, card: ChangeDetail) -> ChangeDetail:
        """Web-research a metadata-only patch once verification demonstrates risk."""
        if card.upgrade_type != "patch" or not self._responder:
            return card
        candidate = ResearchCandidate(
            dependency=Dependency(name=card.package, version=card.current, latest_version=card.target,
                ecosystem=card.ecosystem, direct=True),
            target=card.target, upgrade_type="patch", research_required=True,
            reason="verification failure requires migration research")
        prompt = self._prompt([candidate])
        metrics = self.last_metrics
        metrics.estimated_prompt_tokens += self.counter.count(prompt)
        metrics.web_search_calls += 1
        started = time.monotonic()
        estimated_output = 0
        provider_input = provider_output = None
        try:
            raw = await self._call_with_retry(prompt, 1, metrics)
            estimated_output = self.counter.count(raw)
            metrics.estimated_returned_output_tokens += estimated_output
            metrics.returned_output_tokens += estimated_output
            provider_input, provider_output = getattr(self._responder, "last_usage", (None, None))
            if provider_input is not None:
                metrics.provider_input_tokens = (metrics.provider_input_tokens or 0) + provider_input
            if provider_output is not None:
                metrics.provider_output_tokens = (metrics.provider_output_tokens or 0) + provider_output
            parsed = BreakingChanges.model_validate(json.loads(self._json_object(raw)))
            accepted = {}
            self._accept_batch([candidate], parsed, accepted)
            result = accepted[card.package]
            result.estimated_tokens = self.counter.count(result.model_dump_json())
            if result.estimated_tokens > self.config.card_target_tokens:
                result = await self._shrink(result, metrics)
            if result.research_status == "researched":
                now = datetime.now(timezone.utc)
                try:
                    self.cache.set(cache_key(card.ecosystem, card.package, card.current, card.target),
                        CacheRecord(card=result, source_urls=result.sources, created_at=now,
                            expires_at=now + timedelta(seconds=self.config.normal_cache_ttl_seconds),
                            provider=self.provider_identifier))
                except Exception:
                    pass
            return result
        except asyncio.TimeoutError:
            return card.model_copy(update={"research_status": "failed",
                "truncation_reason": "verification-triggered research timed out"})
        except ResearchRateLimited as error:
            metrics.final_deferred_count += 1
            metrics.deferred_packages.append(card.package)
            return card.model_copy(update={"research_status": "deferred",
                "truncation_reason": error.decision.safe_message})
        except Exception as error:
            logger.warning("verification-triggered research failed: %s", type(error).__name__)
            return card.model_copy(update={"research_status": "failed",
                "truncation_reason": f"verification-triggered research failed ({type(error).__name__})"})
        finally:
            metrics.batches.append({"packages": [card.package], "candidate_count": 1,
                "candidates_by_type": {"security": 0, "major": 0, "minor": 0, "patch": 1},
                "estimated_prompt_tokens": self.counter.count(prompt),
                "estimated_returned_structured_tokens": estimated_output,
                "provider_input_tokens": provider_input, "provider_output_tokens": provider_output,
                "duration_seconds": round(time.monotonic() - started, 4),
                "web_search_calls": 1, "trigger": "verification_failure"})

    async def _call_with_retry(self, prompt: str, batch_size: int, metrics: ResearchMetrics) -> str:
        total_wait = 0.0
        if self._permanent_rate_limit is not None:
            raise ResearchRateLimited(self._permanent_rate_limit, 0, 0.0)
        async with self.limiter:
            for attempt in range(1, self.config.max_attempts + 1):
                metrics.openai_attempted_calls += 1
                try:
                    value = await asyncio.wait_for(self._responder(prompt), timeout=self.config.timeout_seconds)
                    metrics.openai_successful_calls += 1
                    return value
                except RateLimitError as error:
                    decision = classify_rate_limit(error)
                    metrics.openai_rate_limited_calls += 1
                    metrics.rate_limit_categories[decision.category] = (
                        metrics.rate_limit_categories.get(decision.category, 0) + 1)
                    final = not decision.retryable or attempt >= self.config.max_attempts
                    delay = 0.0 if final else self._retry_delay(attempt, decision.reset_seconds)
                    metrics.rate_limit_events.append({"category": decision.category,
                        "http_status": decision.status, "request_id": decision.request_id,
                        "retry_attempt": attempt, "selected_model": self.provider_identifier,
                        "dependency_batch_size": batch_size,
                        "provider_reset_seconds": decision.reset_seconds,
                        "scheduled_wait_seconds": round(delay, 4), "will_retry": not final})
                    logger.warning("OpenAI research rate limit category=%s status=%s request_id=%s "
                                   "attempt=%d model=%s batch_size=%d wait=%.2fs",
                                   decision.category, decision.status, decision.request_id,
                                   attempt, self.provider_identifier, batch_size, delay)
                    if final:
                        if decision.category in {
                            "insufficient_quota", "usage_limit", "configuration_or_model"
                        }:
                            self._permanent_rate_limit = decision
                        raise ResearchRateLimited(decision, attempt, total_wait) from None
                    metrics.openai_retries += 1
                    metrics.retry_wait_seconds += delay
                    total_wait += delay
                    await self.sleep_fn(delay)
        raise RuntimeError("research retry loop ended unexpectedly")

    def _retry_delay(self, failed_attempt: int, reset_seconds: float | None) -> float:
        calculated = min(self.config.retry_max_seconds,
            self.config.retry_min_seconds * (self.config.retry_multiplier ** (failed_attempt - 1)))
        base = max(calculated, reset_seconds or 0.0)
        jitter = base * self.config.retry_jitter * min(1.0, max(0.0, float(self.random_fn())))
        return base + jitter

    async def _enrich_versions(self, profile: RepoProfile) -> set[str]:
        failures = set()
        fixed_by_advisory = {item.dependency.lower() for item in profile.vulnerabilities
                             if item.fix_available and item.fixed_versions}
        for dependency in profile.dependencies:
            if dependency.latest_version or dependency.name.lower() in fixed_by_advisory: continue
            provider = self.providers.get((dependency.ecosystem or profile.package_manager).lower())
            if provider is None: continue
            try: metadata = await provider.lookup(dependency.name)
            except Exception: metadata = None
            if metadata and metadata.latest_version:
                dependency.latest_version = metadata.latest_version
                dependency.metadata_signals = list(metadata.migration_signals)
                dependency.runtime_requirements = ([metadata.requires_python]
                    if metadata.requires_python else [])
                dependency.metadata_sources = ([metadata.release_url]
                    if metadata.release_url else [])
                dependency.metadata_provider = metadata.provider
            else:
                failures.add(dependency.name)
        return failures

    def _accept_batch(self, batch, parsed, changes):
        expected = {c.dependency.name: c for c in batch}
        for name, candidate in expected.items():
            detail = parsed.changes.get(name)
            if not detail or detail.current != candidate.dependency.version or detail.target != candidate.target:
                changes[name] = self._status_card(candidate, "failed", "package or version mismatch")
                continue
            metadata = self._metadata_card(candidate)
            evidence = detail.evidence or [ResearchEvidence(claim="Primary migration source", url=url,
                source_type="official") for url in detail.sources[:5]]
            evidence = list(dict.fromkeys((item.claim, item.url, item.source_type, item.source_title)
                for item in evidence + metadata.evidence))
            evidence = [ResearchEvidence(claim=item[0], url=item[1], source_type=item[2], source_title=item[3])
                        for item in evidence]
            payload = detail.model_dump()
            payload.update({"package": name, "ecosystem": self._ecosystem(candidate),
                "upgrade_type": candidate.upgrade_type, "research_required": True,
                "research_status": "researched", "evidence": evidence,
                "security_advisories": list(dict.fromkeys(
                    detail.security_advisories + metadata.security_advisories)),
                "runtime_requirements": list(dict.fromkeys(
                    detail.runtime_requirements + metadata.runtime_requirements)),
                "sources": list(dict.fromkeys(detail.sources +
                    ([detail.changelog_url] if detail.changelog_url else []) + metadata.sources +
                    [item.url for item in evidence]))})
            changes[name] = ChangeDetail.model_validate(payload)

    def _metadata_card(self, candidate):
        advisory = candidate.vulnerability
        sources = list(advisory.sources) if advisory else []
        sources.extend(candidate.dependency.metadata_sources)
        if advisory and advisory.advisory_url: sources.append(advisory.advisory_url)
        return ChangeDetail(package=candidate.dependency.name, ecosystem=self._ecosystem(candidate),
            current=candidate.dependency.version, target=candidate.target, upgrade_type=candidate.upgrade_type,
            research_required=candidate.research_required, research_status="metadata_only",
            migration_notes=candidate.reason, security_advisories=[advisory.identifier] if advisory and advisory.identifier else [],
            runtime_requirements=candidate.dependency.runtime_requirements,
            sources=sources, evidence=[ResearchEvidence(claim=advisory.summary or advisory.identifier or "Security advisory",
                url=advisory.advisory_url, source_type="security_advisory") for advisory in [advisory]
                if advisory and advisory.advisory_url])

    def _status_card(self, candidate, status, reason):
        return self._metadata_card(candidate).model_copy(update={"research_status": status,
            "truncated": status in {"deferred", "budget_exceeded"}, "truncation_reason": reason})

    async def _shrink(self, card, metrics):
        card.evidence = card.evidence[:self.config.max_sources]
        card.sources = card.sources[:self.config.max_sources]
        card.migration_notes = card.migration_notes[:min(2000, self.config.max_source_chars)]
        card.truncated = True; card.truncation_reason = "card token target"
        if self.counter.count(card.model_dump_json()) > self.config.card_target_tokens and self.config.summarization_enabled:
            metrics.summarizer_calls += 1
            try:
                card.migration_notes = await asyncio.wait_for(
                    self.summarizer.summarize(card.migration_notes, 1200),
                    timeout=min(self.config.timeout_seconds, 60))
            except Exception: card.migration_notes = card.migration_notes[:1200]
        card.estimated_tokens = self.counter.count(card.model_dump_json())
        return card

    @staticmethod
    def _ecosystem(candidate): return candidate.dependency.ecosystem or "unknown"

    @staticmethod
    def _prompt(batch: list[ResearchCandidate]) -> str:
        payload = [{"package": c.dependency.name, "ecosystem": c.dependency.ecosystem,
            "current": c.dependency.version, "target": c.target, "upgrade_type": c.upgrade_type,
            "security_ids": [c.vulnerability.identifier] if c.vulnerability and c.vulnerability.identifier else []}
            for c in batch]
        return ("Research only these dependency upgrades using authoritative primary project, registry, migration-guide, "
            "release, and advisory sources. Return strict JSON matching BreakingChanges with concise version-range-specific "
            "structured cards. Every material claim requires evidence {claim,url,source_type,source_title?}. Never return raw "
            "pages, long quotations, unrelated history, unknown packages, or different versions. Candidates: " + json.dumps(payload))

    @staticmethod
    def _json_object(value):
        value = value.strip()
        if value.startswith("```"): value = value.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return value

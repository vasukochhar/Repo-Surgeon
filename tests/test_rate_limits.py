import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from openai import RateLimitError

from repo_surgeon.contracts import Baseline, ChangeDetail, Dependency, RepoProfile
from repo_surgeon.research.cache import CacheRecord, InMemoryResearchCache, cache_key
from repo_surgeon.research.config import ResearchConfig
from repo_surgeon.research.limiter import AsyncResearchLimiter
from repo_surgeon.research.rate_limits import classify_rate_limit, parse_reset_seconds
from repo_surgeon.researcher import OpenAIResearcher


def profile(name="major", current="1.0.0", target="2.0.0"):
    return RepoProfile(language="Python", package_manager="pip", test_runner="pytest",
        baseline=Baseline(), dependencies=[Dependency(name=name, version=current,
            latest_version=target, ecosystem="PyPI", direct=True)])


def research_config(**updates):
    values = ResearchConfig().__dict__ | {"batch_size": 1, "max_attempts": 5,
        "retry_min_seconds": 5, "retry_max_seconds": 90,
        "retry_multiplier": 2, "retry_jitter": .25} | updates
    return ResearchConfig(**values)


def rate_error(message="rate limited", *, code="rate_limit_exceeded", headers=None):
    request = httpx.Request("POST", "https://api.openai.invalid/v1/responses",
                            headers={"Authorization": "Bearer never-log-this"})
    response = httpx.Response(429, request=request, headers=headers or {})
    return RateLimitError(message, response=response,
        body={"error": {"message": message, "type": "rate_limit_error", "code": code}})


def valid_response(prompt):
    candidate = json.loads(prompt.split("Candidates: ", 1)[1])[0]
    package = candidate["package"]
    url = f"https://primary.example/{package}"
    return json.dumps({"changes": {package: {"current": candidate["current"],
        "target": candidate["target"], "breaking_changes": ["API changed"],
        "sources": [url], "evidence": [{"claim": "API changed", "url": url,
            "source_type": "official_migration_guide"}]}}})


class SequenceResponder:
    def __init__(self, values):
        self.values, self.calls = list(values), 0
        self.last_usage = (None, None)

    async def __call__(self, prompt):
        self.calls += 1
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return valid_response(prompt) if value == "success" else value


def researcher(responder, *, config=None, sleep=None, random_fn=None, cache=None, limiter=None):
    return OpenAIResearcher(responder, {"pypi": object()}, cache=cache,
        config=config or research_config(), provider_identifier="test-model",
        sleep_fn=sleep, random_fn=random_fn or (lambda: 0),
        limiter=limiter or AsyncResearchLimiter(1))


@pytest.mark.asyncio
async def test_success_on_first_attempt_records_provider_call():
    responder = SequenceResponder(["success"])
    result = await researcher(responder).research(profile())
    assert result.changes["major"].research_status == "researched"
    assert result.metrics.openai_attempted_calls == result.metrics.openai_successful_calls == 1
    assert result.metrics.openai_retries == result.metrics.openai_rate_limited_calls == 0


@pytest.mark.parametrize("kind,message,headers,category", [
    ("rpm", "requests per minute exceeded", {"x-ratelimit-remaining-requests": "0"}, "requests_per_minute"),
    ("tpm", "tokens per minute exceeded", {"x-ratelimit-remaining-tokens": "0"}, "tokens_per_minute")])
@pytest.mark.asyncio
async def test_temporary_rate_limit_retries_then_succeeds(kind, message, headers, category):
    sleeps = []
    responder = SequenceResponder([rate_error(message, headers=headers), "success"])
    result = await researcher(responder, sleep=lambda delay: _record_sleep(sleeps, delay)).research(profile())
    assert result.changes["major"].research_status == "researched"
    assert sleeps == [5] and responder.calls == 2
    assert result.metrics.openai_retries == 1
    assert result.metrics.rate_limit_categories == {category: 1}


@pytest.mark.asyncio
async def test_reset_header_longer_than_backoff_and_jitter_are_respected():
    sleeps = []
    error = rate_error("requests per minute", headers={"x-ratelimit-reset-requests": "12s"})
    result = await researcher(SequenceResponder([error, "success"]),
        sleep=lambda delay: _record_sleep(sleeps, delay), random_fn=lambda: 1).research(profile())
    assert sleeps == [15]
    assert result.metrics.retry_wait_seconds == 15
    assert result.metrics.rate_limit_events[0]["provider_reset_seconds"] == 12


@pytest.mark.parametrize("header", [None, "not-a-duration"])
@pytest.mark.asyncio
async def test_missing_or_malformed_reset_header_uses_fallback(header):
    sleeps = []
    headers = {"x-ratelimit-remaining-requests": "0"}
    if header is not None:
        headers["x-ratelimit-reset-requests"] = header
    await researcher(SequenceResponder([rate_error("rpm", headers=headers), "success"]),
        sleep=lambda delay: _record_sleep(sleeps, delay)).research(profile())
    assert sleeps == [5]


@pytest.mark.asyncio
async def test_jitter_uses_configured_fraction():
    sleeps = []
    await researcher(SequenceResponder([rate_error("rpm", headers={
        "x-ratelimit-remaining-requests": "0"}), "success"]),
        sleep=lambda delay: _record_sleep(sleeps, delay), random_fn=lambda: .4).research(profile())
    assert sleeps == [5.5]


@pytest.mark.asyncio
async def test_five_total_attempts_not_six_and_exhaustion_is_deferred():
    sleeps = []
    errors = [rate_error("rpm", headers={"x-ratelimit-remaining-requests": "0"}) for _ in range(5)]
    result = await researcher(SequenceResponder(errors),
        sleep=lambda delay: _record_sleep(sleeps, delay)).research(profile())
    assert result.changes["major"].research_status == "deferred"
    assert result.metrics.openai_attempted_calls == 5
    assert result.metrics.openai_retries == 4
    assert sleeps == [5, 10, 20, 40]
    assert result.metrics.retry_wait_seconds == 75
    assert result.metrics.final_deferred_count == 1


@pytest.mark.parametrize("message,code,category", [
    ("You exceeded your current quota", "insufficient_quota", "insufficient_quota"),
    ("Monthly project usage limit exceeded", "rate_limit_exceeded", "usage_limit"),
    ("Billing credit balance exhausted", "rate_limit_exceeded", "insufficient_quota")])
@pytest.mark.asyncio
async def test_permanent_quota_and_billing_limits_are_not_retried(message, code, category):
    responder = SequenceResponder([rate_error(message, code=code)])
    result = await researcher(responder, sleep=lambda _: pytest.fail("must not sleep")).research(profile())
    assert responder.calls == 1 and result.changes["major"].research_status == "deferred"
    assert result.metrics.rate_limit_categories == {category: 1}
    assert result.metrics.openai_retries == 0


@pytest.mark.asyncio
async def test_permanent_quota_opens_instance_circuit_for_later_stage_calls():
    responder = SequenceResponder([rate_error("quota", code="insufficient_quota")])
    service = researcher(responder, sleep=lambda _: pytest.fail("must not sleep"))
    first = await service.research(profile())
    second = await service.research(profile())
    assert first.changes["major"].research_status == "deferred"
    assert second.changes["major"].research_status == "deferred"
    assert responder.calls == 1
    assert second.metrics.openai_attempted_calls == 0


@pytest.mark.asyncio
async def test_unknown_rate_limit_degrades_without_retry():
    responder = SequenceResponder([rate_error("provider capacity unavailable")])
    result = await researcher(responder, sleep=lambda _: pytest.fail("must not sleep")).research(profile())
    assert responder.calls == 1
    assert result.changes["major"].research_status == "deferred"
    assert result.metrics.rate_limit_categories == {"unknown_rate_limit": 1}


@pytest.mark.asyncio
async def test_oversized_tpm_request_is_not_retried():
    responder = SequenceResponder([rate_error(
        "Request too large for tokens per minute; requested tokens exceed limit")])
    result = await researcher(responder, sleep=lambda _: pytest.fail("must not sleep")).research(profile())
    assert responder.calls == 1 and result.metrics.openai_retries == 0
    assert result.metrics.rate_limit_categories == {"tokens_per_minute": 1}


@pytest.mark.asyncio
async def test_sdk_retries_are_disabled(monkeypatch):
    captured = {}
    class Responses:
        async def create(self, **kwargs):
            return type("Response", (), {"output_text": "{}", "usage": None})()
    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs); self.responses = Responses()
    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    instance = OpenAIResearcher.from_openai("gpt-5.6-luna")
    await instance._responder("safe")
    assert captured["max_retries"] == 0


@pytest.mark.asyncio
async def test_concurrency_one_serializes_calls():
    limiter = AsyncResearchLimiter(1)
    first_entered, release_first = asyncio.Event(), asyncio.Event()
    state = {"active": 0, "maximum": 0, "calls": 0}
    async def respond(prompt):
        state["calls"] += 1; state["active"] += 1
        state["maximum"] = max(state["maximum"], state["active"])
        if state["calls"] == 1:
            first_entered.set(); await release_first.wait()
        state["active"] -= 1
        return valid_response(prompt)
    one = researcher(respond, limiter=limiter)
    two = researcher(respond, limiter=limiter)
    task_one = asyncio.create_task(one.research(profile("one")))
    await first_entered.wait()
    task_two = asyncio.create_task(two.research(profile("two")))
    await asyncio.sleep(0)
    assert state["calls"] == 1
    release_first.set()
    await asyncio.gather(task_one, task_two)
    assert state["maximum"] == 1 and state["calls"] == 2


@pytest.mark.asyncio
async def test_cache_hit_and_registry_patch_make_zero_openai_calls():
    cache = InMemoryResearchCache()
    now = datetime.now(timezone.utc)
    card = ChangeDetail(package="major", ecosystem="PyPI", current="1.0.0", target="2.0.0")
    cache.set(cache_key("PyPI", "major", "1.0.0", "2.0.0"), CacheRecord(card=card,
        source_urls=[], created_at=now, expires_at=now + timedelta(hours=1)))
    responder = SequenceResponder([])
    cached = await researcher(responder, cache=cache).research(profile())
    patch = await researcher(responder).research(profile("patch", "1.0.0", "1.0.1"))
    assert cached.metrics.cache_hits == 1 and patch.metrics.registry_only == 1
    assert responder.calls == 0


@pytest.mark.asyncio
async def test_logs_exclude_api_key_prompt_and_raw_error(caplog):
    secret = "sk-secret-never-log"
    prompt_marker = "PROMPT_PRIVATE_CONTENT"
    responder = SequenceResponder([rate_error(f"rpm {secret} {prompt_marker}", headers={
        "x-ratelimit-remaining-requests": "0", "x-request-id": "req_safe"})])
    with caplog.at_level(logging.WARNING):
        await researcher(responder, config=research_config(max_attempts=1)).research(profile())
    output = caplog.text
    assert secret not in output and prompt_marker not in output
    assert "requests_per_minute" in output and "req_safe" in output


@pytest.mark.asyncio
async def test_other_batch_continues_when_one_package_is_deferred():
    async def respond(prompt):
        package = json.loads(prompt.split("Candidates: ", 1)[1])[0]["package"]
        if package == "a":
            raise rate_error("unclassified provider limit")
        return valid_response(prompt)
    candidate_profile = RepoProfile(language="Python", package_manager="pip", test_runner="pytest",
        baseline=Baseline(), dependencies=[Dependency(name=name, version="1", latest_version="2",
            ecosystem="PyPI", direct=True) for name in ("a", "b")])
    result = await researcher(respond).research(candidate_profile)
    assert result.changes["a"].research_status == "deferred"
    assert result.changes["b"].research_status == "researched"
    assert result.metrics.openai_attempted_calls == 2


def test_reset_parser_and_config_validation(monkeypatch):
    assert parse_reset_seconds("250ms") == .25
    assert parse_reset_seconds("1m2s") == 62
    assert parse_reset_seconds("broken") is None
    monkeypatch.setenv("REPO_SURGEON_RESEARCH_BATCH_SIZE", "99")
    monkeypatch.setenv("REPO_SURGEON_MAX_CONCURRENT_RESEARCH", "0")
    monkeypatch.setenv("REPO_SURGEON_RESEARCH_MAX_ATTEMPTS", "0")
    monkeypatch.setenv("REPO_SURGEON_RESEARCH_RETRY_MIN_SECONDS", "10")
    monkeypatch.setenv("REPO_SURGEON_RESEARCH_RETRY_MAX_SECONDS", "2")
    monkeypatch.setenv("REPO_SURGEON_RESEARCH_RETRY_JITTER", "2")
    config = ResearchConfig.from_env()
    assert config.batch_size == 5 and config.max_concurrent_research == 1
    assert config.max_attempts == 1 and config.retry_max_seconds == config.retry_min_seconds == 10
    assert config.retry_jitter == 1


async def _record_sleep(values, delay):
    values.append(delay)

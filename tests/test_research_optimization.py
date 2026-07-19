import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from repo_surgeon.contracts import (Baseline, BreakingChanges, ChangeDetail, Dependency,
    EditResult, RepoProfile, ResearchEvidence, UpgradeCategory, UpgradeItem,
    VerifyResult, Vulnerability)
from repo_surgeon.events import EventBus
from repo_surgeon.planner import Planner
from repo_surgeon.research.budget import ResearchContextBudgeter
from repo_surgeon.research.cache import CacheRecord, FileResearchCache, InMemoryResearchCache, cache_key
from repo_surgeon.research.config import ResearchConfig
from repo_surgeon.research.policy import ResearchPolicy
from repo_surgeon.research.providers import RegistryMetadata
from repo_surgeon.researcher import OpenAIResearcher
from repo_surgeon.surgeon import Surgeon


def repo_profile(dependencies, vulnerabilities=None):
    return RepoProfile(language="Python", package_manager="pip", test_runner="pytest",
        baseline=Baseline(), dependencies=dependencies, vulnerabilities=vulnerabilities or [])


def dependency(name, current="1.0.0", target="2.0.0", **updates):
    direct = updates.pop("direct", True)
    return Dependency(name=name, version=current, latest_version=target,
        ecosystem="PyPI", direct=direct, **updates)


class FakeRegistry:
    def __init__(self, metadata=None, error=None):
        self.metadata, self.error, self.calls = metadata, error, []

    async def lookup(self, package):
        self.calls.append(package)
        if self.error:
            raise self.error
        return self.metadata


def batch_responder(calls, usage=None):
    async def respond(prompt):
        payload = json.loads(prompt.split("Candidates: ", 1)[1])
        calls.append(payload)
        changes = {}
        for item in payload:
            url = f"https://primary.example/{item['package']}/{item['target']}"
            changes[item["package"]] = {"current": item["current"], "target": item["target"],
                "breaking_changes": [f"{item['package']} changed API"],
                "required_code_changes": ["Update exact_api_name()"], "sources": [url],
                "evidence": [{"claim": "API migration", "url": url,
                    "source_type": "official_migration_guide"}]}
        if usage:
            respond.last_usage = usage
        return json.dumps({"changes": changes})
    respond.last_usage = (None, None)
    return respond


def config(**updates):
    values = ResearchConfig().__dict__ | updates
    return ResearchConfig(**values)


def test_research_policy_prioritizes_all_candidates_without_ten_item_cap():
    dependencies = [dependency("security", target="1.0.1")]
    dependencies += [dependency(f"major-{index}") for index in range(4)]
    dependencies += [dependency(f"minor-{index}", target="1.1.0", requested_version="^1.0") for index in range(3)]
    dependencies += [dependency(f"patch-{index}", target="1.0.1") for index in range(4)]
    dependencies[-1].direct = False
    advisory = Vulnerability(dependency="security", identifier="CVE-2026-0001",
        fixed_versions=["1.0.1"], fix_available=True)
    candidates = ResearchPolicy().candidates(repo_profile(dependencies, [advisory]))
    assert len(candidates) == 12
    assert [candidate.upgrade_type for candidate in candidates] == (
        ["security"] + ["major"] * 4 + ["minor"] * 3 + ["patch"] * 4)
    assert candidates[-1].research_required is False
    direct_patch = next(candidate for candidate in candidates
                        if candidate.upgrade_type == "patch" and candidate.dependency.direct)
    assert ResearchPolicy.requires_web(direct_patch, verification_failed=True)


@pytest.mark.parametrize("batch_size,expected_sizes", [
    (3, [3, 3, 3, 2]), (4, [4, 4, 3]), (5, [5, 5, 1]), (99, [5, 5, 1])])
@pytest.mark.asyncio
async def test_research_batches_at_configured_size_and_marks_every_candidate(batch_size, expected_sizes):
    calls = []
    profile = repo_profile([dependency(f"package-{index}") for index in range(11)])
    researcher = OpenAIResearcher(batch_responder(calls), providers={"pypi": object()},
        config=config(batch_size=batch_size))
    result = await researcher.research(profile)
    assert len(result.changes) == 11
    assert list(map(len, calls)) == expected_sizes
    assert result.metrics.web_search_calls == len(expected_sizes)
    assert {card.research_status for card in result.changes.values()} == {"researched"}
    assert len(result.metrics.batches) == len(expected_sizes)


@pytest.mark.asyncio
async def test_cache_hit_miss_expiry_schema_and_security_ttl():
    calls, cache = [], InMemoryResearchCache()
    advisory = Vulnerability(dependency="secure", identifier="GHSA-abcd",
        fixed_versions=["1.0.1"], fix_available=True,
        advisory_url="https://advisories.example/GHSA-abcd")
    profile = repo_profile([dependency("secure", target="1.0.1")], [advisory])
    cfg = config(security_cache_ttl_seconds=30, normal_cache_ttl_seconds=3_000)
    first = await OpenAIResearcher(batch_responder(calls), {"pypi": object()}, cache, cfg).research(profile)
    assert first.metrics.cache_misses == 1 and len(calls) == 1
    assert first.changes["secure"].security_advisories == ["GHSA-abcd"]
    assert "https://advisories.example/GHSA-abcd" in first.changes["secure"].sources
    key = cache_key("PyPI", "secure", "1.0.0", "1.0.1")
    record = cache.records[key]
    assert 28 <= (record.expires_at - record.created_at).total_seconds() <= 31
    second = await OpenAIResearcher(batch_responder(calls), {"pypi": object()}, cache, cfg).research(profile)
    assert second.metrics.cache_hits == 1 and second.changes["secure"].research_status == "cached"
    assert len(calls) == 1
    cache.records[key] = record.model_copy(update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    refreshed = await OpenAIResearcher(batch_responder(calls), {"pypi": object()}, cache, cfg).research(profile)
    assert refreshed.metrics.cache_misses == 1 and len(calls) == 2
    cache.records[key] = record.model_copy(update={"schema_version": "1.0"})
    assert cache.get(key) is None


def test_file_cache_round_trip_and_normalized_key(tmp_path):
    path = tmp_path / "research.json"
    key = cache_key("PyPI", "Some_Package.Name", "1", "2")
    record = CacheRecord(card=ChangeDetail(package="Some_Package.Name", current="1", target="2"),
        source_urls=["https://primary.example/guide"], created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1), provider="fake")
    FileResearchCache(path).set(key, record)
    loaded = FileResearchCache(path).get(cache_key("pypi", "some-package-name", "1", "2"))
    assert loaded and loaded.provider == "fake" and loaded.source_urls == record.source_urls


@pytest.mark.asyncio
async def test_registry_first_patch_resolution_avoids_web_search():
    registry = FakeRegistry(RegistryMetadata("small", "PyPI", "1.0.1",
        "https://pypi.org/project/small/1.0.1", requires_python=">=3.9"))
    profile = repo_profile([Dependency(name="small", version="1.0.0", ecosystem="PyPI")])
    cache = InMemoryResearchCache()
    result = await OpenAIResearcher(providers={"pypi": registry}, cache=cache).research(profile)
    card = result.changes["small"]
    assert profile.dependencies[0].latest_version == "1.0.1"
    assert card.research_status == "metadata_only" and card.runtime_requirements == [">=3.9"]
    assert card.sources == ["https://pypi.org/project/small/1.0.1"]
    assert result.metrics.registry_only == 1 and result.metrics.web_search_calls == 0
    warm = await OpenAIResearcher(providers={"pypi": registry}, cache=cache).research(profile)
    assert warm.metrics.cache_hits == 1 and warm.changes["small"].research_status == "cached"


@pytest.mark.asyncio
async def test_major_security_and_signaled_minor_use_web_but_transitive_does_not():
    calls = []
    dependencies = [dependency("major"),
        dependency("minor", target="1.1.0", metadata_signals=["Migration notes published"]),
        dependency("transitive", direct=False)]
    advisory = Vulnerability(dependency="major", identifier="CVE-2026-7",
        fixed_versions=["2.0.0"], fix_available=True)
    result = await OpenAIResearcher(batch_responder(calls), {"pypi": object()}).research(
        repo_profile(dependencies, [advisory]))
    assert {item["package"] for batch in calls for item in batch} == {"major", "minor"}
    assert result.changes["transitive"].research_status == "metadata_only"
    assert result.changes["major"].security_advisories == ["CVE-2026-7"]


@pytest.mark.asyncio
async def test_unknown_package_and_version_mismatch_are_rejected():
    async def bad_response(prompt):
        return json.dumps({"changes": {
            "wanted": {"current": "1.0.0", "target": "9.9.9", "sources": ["https://primary.example/wanted"]},
            "unknown": {"current": "1", "target": "2", "sources": ["https://primary.example/unknown"]}}})
    result = await OpenAIResearcher(bad_response, {"pypi": object()}).research(
        repo_profile([dependency("wanted")]))
    assert set(result.changes) == {"wanted"}
    assert result.changes["wanted"].research_status == "failed"
    assert "mismatch" in result.changes["wanted"].truncation_reason


def test_structured_card_limits_deduplication_and_evidence_preservation():
    card = ChangeDetail(package="pkg", ecosystem="PyPI", current="1", target="2",
        migration_notes="x" * 5_000,
        breaking_changes=[" Same API ", "same   api"] + [f"change-{index}" for index in range(15)],
        required_code_changes=[f"code-{index}" for index in range(12)],
        configuration_changes=[f"config-{index}" for index in range(8)],
        runtime_requirements=[f"runtime-{index}" for index in range(8)],
        known_issues=[f"issue-{index}" for index in range(8)],
        security_advisories=[f"CVE-2026-{index:04d}" for index in range(8)],
        sources=["https://primary.example/guide", "https://primary.example/guide"],
        evidence=[ResearchEvidence(claim=f"claim-{index}", url=f"https://primary.example/{index}",
            source_type="official") for index in range(8)])
    assert len(card.breaking_changes) == 10 and len(card.required_code_changes) == 10
    assert len(card.configuration_changes) == len(card.runtime_requirements) == 5
    assert len(card.known_issues) == len(card.security_advisories) == len(card.evidence) == 5
    assert len(card.migration_notes) == 4_000 and card.truncated
    assert card.sources == ["https://primary.example/guide"]
    assert card.evidence[0].url == "https://primary.example/0"


def test_planner_budget_compacts_then_defers_low_priority_nonsecurity():
    changes = BreakingChanges(changes={
        "security": ChangeDetail(package="security", current="1", target="2", upgrade_type="security",
            security_advisories=["CVE-2026-9999"], sources=["https://advisories.example/9999"]),
        "major": ChangeDetail(package="major", current="1", target="2", upgrade_type="major",
            breaking_changes=["M" * 1000], sources=["https://primary.example/major"]),
        "patch": ChangeDetail(package="patch", current="1", target="1.0.1", upgrade_type="patch",
            known_issues=["P" * 1000], sources=["https://primary.example/patch"])})
    index, deferred, tokens = ResearchContextBudgeter(target=80, maximum=130).planner_index(changes)
    assert "security" in index and index["security"]["security_advisories"] == ["CVE-2026-9999"]
    assert deferred and "patch" in deferred
    assert changes.changes["patch"].research_status == "budget_exceeded"
    assert changes.changes["patch"].truncation_reason == "planner absolute context limit"
    assert tokens <= 130 or set(index) == {"security"}


@pytest.mark.asyncio
async def test_planner_receives_compact_index_not_full_research_cards():
    prompts = []
    async def respond(prompt):
        prompts.append(prompt)
        return '{"items":[]}'
    changes = BreakingChanges(changes={"one": ChangeDetail(package="one", current="1", target="2",
        migration_notes="PRIVATE_FULL_SOURCE_TEXT", sources=["https://primary.example/one"])})
    await Planner(respond).build_plan(repo_profile([]), changes)
    assert "PRIVATE_FULL_SOURCE_TEXT" not in prompts[0]
    assert "https://primary.example/one" in prompts[0]
    assert changes.metrics.planner_context_tokens > 0


@pytest.mark.asyncio
async def test_surgeon_receives_only_current_package_card(monkeypatch, tmp_path):
    monkeypatch.setenv("REPO_SURGEON_SURGEON_CONTEXT_TOKENS", "1500")
    class Runner:
        detail = None
        async def edit(self, workdir, item, breaking_change, failure_context=None):
            self.detail = breaking_change
            return EditResult()
    class Verifier:
        async def verify(self, item, workdir):
            return VerifyResult(item_id=item.id)
    runner = Runner()
    changes = BreakingChanges(changes={
        "one": ChangeDetail(package="one", current="1", target="2"),
        "two": ChangeDetail(package="two", current="1", target="2", migration_notes="other")})
    item = UpgradeItem(id="one", dependency="one", from_version="1", to_version="2",
        category=UpgradeCategory.MAJOR, risk=.5, rationale="test")
    await Surgeon(runner, Verifier(), EventBus()).operate("job", tmp_path, item, changes)
    assert runner.detail.package == "one" and "other" not in runner.detail.model_dump_json()
    assert changes.metrics.surgeon_context_tokens["one"] <= 1500


@pytest.mark.asyncio
async def test_failed_patch_iteration_triggers_one_web_research_escalation(tmp_path):
    calls = []
    researcher = OpenAIResearcher(batch_responder(calls), {"pypi": object()})
    class Runner:
        def __init__(self): self.cards = []
        async def edit(self, workdir, item, breaking_change, failure_context=None):
            self.cards.append(breaking_change)
            return EditResult()
    class Verifier:
        def __init__(self): self.calls = 0
        async def verify(self, item, workdir):
            self.calls += 1
            return (VerifyResult(item_id=item.id, tests_failed=1, logs="compatibility failure")
                    if self.calls == 1 else VerifyResult(item_id=item.id))
    runner = Runner()
    changes = BreakingChanges(changes={"patch": ChangeDetail(package="patch", ecosystem="PyPI",
        current="1.0.0", target="1.0.1", upgrade_type="patch", research_required=False,
        research_status="metadata_only")})
    item = UpgradeItem(id="patch", dependency="patch", from_version="1.0.0", to_version="1.0.1",
        category=UpgradeCategory.PATCH, risk=.1, rationale="test")
    result = await Surgeon(runner, Verifier(), EventBus(),
        research_escalator=researcher.escalate_after_verification).operate("job", tmp_path, item, changes)
    assert result.status.value == "green" and len(calls) == 1
    assert [card.research_status for card in runner.cards] == ["metadata_only", "researched"]


@pytest.mark.asyncio
async def test_summarizer_registry_and_web_failures_degrade_gracefully():
    class FailingSummarizer:
        async def summarize(self, text, max_chars):
            raise RuntimeError("offline")
    async def huge_response(prompt):
        item = json.loads(prompt.split("Candidates: ", 1)[1])[0]
        return json.dumps({"changes": {item["package"]: {"current": item["current"],
            "target": item["target"], "migration_notes": "Migration exact_api() " * 1000,
            "sources": ["https://primary.example/guide"]}}})
    summarized = await OpenAIResearcher(huge_response, {"pypi": object()},
        config=config(card_target_tokens=100, summarization_enabled=True),
        summarizer=FailingSummarizer()).research(repo_profile([dependency("huge")]))
    assert summarized.changes["huge"].truncated and summarized.metrics.summarizer_calls == 1

    failed_registry = FakeRegistry(error=RuntimeError("registry offline"))
    unresolved = await OpenAIResearcher(providers={"pypi": failed_registry}).research(
        repo_profile([Dependency(name="missing", version="1", ecosystem="PyPI")]))
    assert unresolved.changes["missing"].research_status == "failed"
    assert unresolved.metrics.registry_failures == ["missing"]

    async def slow_response(prompt):
        await asyncio.sleep(.05)
        return '{"changes":{}}'
    timed_out = await OpenAIResearcher(slow_response, {"pypi": object()},
        config=config(timeout_seconds=.001)).research(repo_profile([dependency("slow")]))
    assert timed_out.changes["slow"].research_status == "failed"
    assert "timed out" in timed_out.changes["slow"].truncation_reason

    async def broken_response(prompt):
        raise ConnectionError("offline")
    failed_web = await OpenAIResearcher(broken_response, {"pypi": object()}).research(
        repo_profile([dependency("offline")]))
    assert failed_web.changes["offline"].research_status == "failed"
    assert "ConnectionError" in failed_web.changes["offline"].truncation_reason


@pytest.mark.asyncio
async def test_required_web_without_provider_is_explicitly_deferred():
    result = await OpenAIResearcher(providers={"pypi": object()}).research(
        repo_profile([dependency("major")]))
    assert result.changes["major"].research_status == "deferred"
    assert result.metrics.deferred_packages == ["major"]


@pytest.mark.asyncio
async def test_metrics_distinguish_estimated_and_provider_reported_tokens():
    calls = []
    result = await OpenAIResearcher(batch_responder(calls, usage=(321, 45)),
        {"pypi": object()}).research(repo_profile([dependency("metrics")]))
    assert result.metrics.estimated_prompt_tokens > 0
    assert result.metrics.estimated_returned_output_tokens > 0
    assert result.metrics.provider_input_tokens == 321
    assert result.metrics.provider_output_tokens == 45

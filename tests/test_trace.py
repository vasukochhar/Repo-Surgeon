import json

import pytest

from repo_surgeon.contracts import Baseline, RepoProfile, UpgradeItem
from repo_surgeon.researcher import research_token_budget
from repo_surgeon.trace import JobTracer, NullTracer, _encode


@pytest.fixture
def tracer(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO_SURGEON_TRACE", "1")
    return JobTracer("job-1", root=tmp_path)


def test_writes_numbered_files_in_call_order(tracer):
    tracer.write("scouting", "input", {"a": 1})
    tracer.write("scouting", "output", {"b": 2})
    names = sorted(path.name for path in tracer.dir.iterdir())
    assert names == ["01_scouting_input.json", "02_scouting_output.json"]


def test_encodes_pydantic_models_losslessly(tracer):
    item = UpgradeItem(id="u1", dependency="requests", from_version="1.0", to_version="2.0",
                       category="security", risk=0.5, rationale="CVE")
    path = tracer.write("plan", "output", item)
    data = json.loads(path.read_text(encoding="utf-8"))["data"]
    assert data["dependency"] == "requests" and data["category"] == "security"


def test_truncates_huge_strings_but_keeps_both_ends():
    encoded = _encode("HEAD" + "x" * 100_000 + "TAIL")
    assert encoded.startswith("HEAD") and encoded.endswith("TAIL")
    assert "trace truncated" in encoded and len(encoded) < 50_000


def test_nested_profile_survives_encoding(tracer):
    profile = RepoProfile(language="python", package_manager="pip", test_runner="pytest",
                          baseline=Baseline(tests_passed=3))
    data = json.loads(tracer.write("scouting", "output", profile).read_text(encoding="utf-8"))["data"]
    assert data["baseline"]["tests_passed"] == 3


def test_disabled_tracer_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO_SURGEON_TRACE", "0")
    disabled = JobTracer("job-2", root=tmp_path)
    assert disabled.write("scouting", "input", {}) is None
    assert not disabled.dir.exists()


def test_unwritable_data_does_not_raise(tracer):
    """A trace failure must never take down the job it is tracing."""
    class Exploding:
        def model_dump(self, mode=None):
            raise RuntimeError("boom")
    assert tracer.write("scouting", "output", Exploding()) is not None


def test_null_tracer_is_a_silent_noop():
    assert NullTracer().write("any", "thing", object()) is None


def test_research_budget_scales_with_candidates(monkeypatch):
    monkeypatch.delenv("REPO_SURGEON_RESEARCH_MAX_OUTPUT_TOKENS", raising=False)
    assert research_token_budget(6) > research_token_budget(1)


def test_research_budget_override_wins(monkeypatch):
    monkeypatch.setenv("REPO_SURGEON_RESEARCH_MAX_OUTPUT_TOKENS", "500")
    assert research_token_budget(10) == 500

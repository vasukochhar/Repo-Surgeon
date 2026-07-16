import json
import sys
import pytest
from repo_surgeon.app import build_orchestrator
from repo_surgeon.contracts import Baseline, RepoProfile
from repo_surgeon.sandbox.command_runner import AsyncCommandRunner
from repo_surgeon.scout.baseline_runner import parse_test_output
from repo_surgeon.scout.command_detector import CommandDetector
from repo_surgeon.scout.coverage import parse_coverage
from repo_surgeon.scout.stack_detector import StackDetector
from repo_surgeon.security.normalizer import deduplicate
from repo_surgeon.security.npm_audit import parse_npm_audit
from repo_surgeon.security.osv import parse_osv
from repo_surgeon.security.pip_audit import parse_pip_audit
from repo_surgeon.verifier.affected_tests import AffectedTests
from repo_surgeon.verifier.baseline_diff import compare_failures
from repo_surgeon.verifier.mutmut_runner import parse_mutmut
from repo_surgeon.verifier.quality_score import grade, quality_score


@pytest.mark.asyncio
async def test_command_runner_outcomes_and_truncation(tmp_path):
    runner = AsyncCommandRunner(default_timeout=3, max_output_chars=80)
    ok = await runner.run([sys.executable, "-c", "print('x'*200)"], cwd=tmp_path)
    bad = await runner.run([sys.executable, "-c", "raise SystemExit(4)"])
    slow = await runner.run([sys.executable, "-c", "import time; time.sleep(1)"], timeout=.05)
    missing = await runner.run(["certainly-not-a-real-executable-7281"])
    assert ok.exit_code == 0 and "truncated" in ok.stdout
    assert bad.exit_code == 4 and slow.timed_out and missing.tool_unavailable


@pytest.mark.parametrize("kind,expected", [("pip", ("Python", "pip", "pytest")), ("poetry", ("Python", "poetry", "pytest")), ("uv", ("Python", "uv", "pytest"))])
def test_python_detection(tmp_path, kind, expected):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]')
    if kind != "pip": (tmp_path / f"{kind}.lock").write_text("")
    stack = StackDetector().detect(tmp_path)
    assert (stack.language, stack.package_manager, stack.test_runner) == expected
    assert CommandDetector().detect(tmp_path, stack).test == ["python", "-m", "pytest"]


def test_python_coverage_targets_package_not_persisted_dependencies(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]')
    (tmp_path / "app").mkdir(); (tmp_path / "app/__init__.py").write_text("")
    (tmp_path / ".repo-surgeon-deps").mkdir(); (tmp_path / ".repo-surgeon-deps/__init__.py").write_text("")
    commands = CommandDetector().detect(tmp_path, StackDetector().detect(tmp_path))
    assert "--cov=app" in commands.coverage


def test_node_detection_and_monorepo(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"packageManager":"pnpm@9", "workspaces":["packages/*"], "scripts":{"test":"vitest", "build":"tsc"}}))
    (tmp_path / "tsconfig.json").write_text("{}")
    stack = StackDetector().detect(tmp_path)
    assert (stack.language, stack.package_manager, stack.test_runner, stack.is_monorepo) == ("TypeScript", "pnpm", "vitest", True)
    assert CommandDetector().detect(tmp_path, stack).build == ["pnpm", "run", "build"]


def test_parsers_and_deduplication():
    assert parse_test_output("2 passed, 1 failed, 3 skipped")[0:3] == (2, 1, 3)
    pip = parse_pip_audit('{"dependencies":[{"name":"x","version":"1","vulns":[{"id":"CVE-1","fix_versions":["2"]}]}]}')
    npm = parse_npm_audit('{"vulnerabilities":{"x":{"severity":"high","via":[{"source":"CVE-1"}],"fixAvailable":true}}}')
    osv = parse_osv('{"results":[{"packages":[{"package":{"name":"x","ecosystem":"PyPI"},"vulnerabilities":[{"id":"CVE-1"}]}]}]}')
    assert pip[0].fix_available and npm[0].severity == "high" and osv[0].identifier == "CVE-1"
    pip[0].sources = ["a"]; duplicate = pip[0].model_copy(update={"sources":["b"]})
    assert deduplicate([pip[0], duplicate])[0].sources == ["a", "b"]


def test_coverage_affected_mapping_and_comparison(tmp_path):
    (tmp_path / "coverage.json").write_text('{"totals":{"percent_covered":80},"files":{"foo.py":{"summary":{"percent_covered":75}}}}')
    (tmp_path / "tests").mkdir(); (tmp_path / "tests/test_foo.py").write_text("")
    profile = RepoProfile(language="Python", package_manager="pip", test_runner="pytest", baseline=Baseline())
    selected, reason = AffectedTests(AsyncCommandRunner()).select(tmp_path, ["src/foo.py"], profile)
    assert parse_coverage(tmp_path).line_percent == 80 and selected == ["tests/test_foo.py"] and reason is None
    assert compare_failures(["old", "same"], ["same", "new"]) == (["new"], ["same"], ["old"])


def test_mutation_and_quality_score():
    report = parse_mutmut("killed 7 survived 2 timeout 1 untested 4")
    assert report.score == 70 and quality_score(80, None, 100) == 82.5 and grade(82.5) == "strong"


def test_real_factory_is_lazy():
    assert build_orchestrator("real") is not None

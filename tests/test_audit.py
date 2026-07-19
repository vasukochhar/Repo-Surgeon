import asyncio
import json
import sys
from pathlib import Path

import pytest

from repo_surgeon.contracts import (Baseline, CommandResult, ExecutionStatus, RepoProfile,
    UpgradeCategory, UpgradeItem, VerifyResult)
from repo_surgeon.sandbox import AsyncCommandRunner, RealSandbox
from repo_surgeon.sandbox.command_runner import redact_environment
from repo_surgeon.sandbox.errors import InvalidRepositoryError
from repo_surgeon.scout import CommandDetector, ProfileRegistry, StackDetector
from repo_surgeon.scout.profile_writer import ProfileWriter
from repo_surgeon.security.npm_audit import parse_npm_audit
from repo_surgeon.verifier.affected_tests import AffectedTests
from repo_surgeon.verifier.mutmut_runner import MutmutRunner, parse_mutmut
from repo_surgeon.verifier.mutation import MutationService
from repo_surgeon.verifier.quality_score import grade, quality_score
from repo_surgeon.verifier.service import RealVerifier
from repo_surgeon.verifier.stryker_runner import parse_stryker


def result(command, code=0, stdout="", stderr="", status=None, unavailable=False, timeout=False):
    return CommandResult(command=list(command), exit_code=code, stdout=stdout, stderr=stderr,
        status=status or (ExecutionStatus.PASSED if code == 0 else ExecutionStatus.FAILED),
        tool_unavailable=unavailable, timed_out=timeout)


class QueueRunner:
    def __init__(self, responses): self.responses, self.commands = list(responses), []
    async def run(self, command, **kwargs):
        self.commands.append(list(command)); return self.responses.pop(0)


def profile(failures=None, build=True):
    return RepoProfile(language="Python", package_manager="pip", test_runner="pytest",
        baseline=Baseline(test_command=["pytest"], build_command=["build"],
            failing_tests=failures or [], tests_failed=len(failures or []), build_ok=build))


def item():
    return UpgradeItem(id="x", dependency="d", from_version="1", to_version="2",
        category=UpgradeCategory.PATCH, risk=0, rationale="audit")


def test_contract_backwards_compatibility_and_pass_semantics():
    old = RepoProfile(language="Python", package_manager="pip", test_runner="pytest", baseline=Baseline())
    assert old.dependencies == [] and VerifyResult(item_id="x").passed
    assert not VerifyResult(item_id="x", regression_aware=True, test_execution_failed=True).passed
    assert not VerifyResult(item_id="x", regression_aware=True, affected_tests_failed=True).passed
    assert redact_environment({"API_TOKEN":"value", "NORMAL":"ok"}) == {"API_TOKEN":"[REDACTED]", "NORMAL":"ok"}


@pytest.mark.asyncio
async def test_runner_environment_unicode_stderr_and_cancel(tmp_path):
    runner = AsyncCommandRunner(default_timeout=2, max_output_chars=100)
    env = await runner.run([sys.executable, "-c", "import os; print(os.environ['AUDIT_X'])"], env={"AUDIT_X":"ok"})
    invalid = await runner.run([sys.executable, "-c", "import sys; sys.stderr.buffer.write(b'\\xff'*500)"])
    assert env.stdout.strip() == "ok" and "truncated" in invalid.stderr and "�" in invalid.stderr
    task = asyncio.create_task(runner.run([sys.executable, "-c", "import time; time.sleep(10)"], cwd=tmp_path))
    await asyncio.sleep(.1); task.cancel()
    with pytest.raises(asyncio.CancelledError): await task


def test_sandbox_validation_and_cleanup_boundary(tmp_path):
    sandbox = RealSandbox(root=tmp_path)
    for bad in ("file:///tmp/x", "ssh://host/x", "https://user:pass@host/x", "https://host/x\n--evil"):
        with pytest.raises(InvalidRepositoryError): sandbox.validate_url(bad)
    outside = tmp_path.parent / "outside-audit"
    with pytest.raises(InvalidRepositoryError):
        asyncio.run(sandbox.execute(outside, ["true"], "repo-surgeon-python"))


@pytest.mark.parametrize("files,expected", [
    ({"requirements.txt":"pytest", "pytest.ini":"[pytest]"}, ("pip","pytest")),
    ({"Pipfile":"[dev-packages]\npytest='*'"}, ("pipenv","pytest")),
    ({"pyproject.toml":"[project]\nname='x'"}, ("pip","unknown")),
])
def test_python_detection_realistic(tmp_path, files, expected):
    for name, text in files.items(): (tmp_path / name).write_text(text)
    stack = StackDetector().detect(tmp_path)
    assert (stack.package_manager, stack.test_runner) == expected
    commands = CommandDetector().detect(tmp_path, stack)
    if stack.test_runner == "unknown": assert commands.test is None


@pytest.mark.parametrize("manager_file,manager", [("package-lock.json","npm"),("pnpm-lock.yaml","pnpm"),("yarn.lock","yarn")])
def test_node_managers_and_no_browser_test_invention(tmp_path, manager_file, manager):
    (tmp_path / "package.json").write_text(json.dumps({"scripts":{"test":"cypress run"}, "devDependencies":{"cypress":"1"}}))
    (tmp_path / manager_file).write_text("{}")
    stack = StackDetector().detect(tmp_path); commands = CommandDetector().detect(tmp_path, stack)
    assert stack.package_manager == manager and stack.test_runner == "unknown" and commands.test is None


def test_malformed_package_json_is_safe(tmp_path):
    (tmp_path / "package.json").write_text("{")
    stack = StackDetector().detect(tmp_path)
    assert stack.package_manager == "unknown" and CommandDetector().detect(tmp_path, stack).test is None


def test_profile_round_trip_and_unique_paths(tmp_path):
    writer = ProfileWriter(tmp_path / "out"); one = tmp_path / "a" / "same"; two = tmp_path / "b" / "same"
    one.mkdir(parents=True); two.mkdir(parents=True)
    p1, p2 = profile(), profile(); path1 = writer.write(p1, one); path2 = writer.write(p2, two)
    assert path1 != path2 and RepoProfile.model_validate_json(path1.read_text()).schema_version == "1.0"


@pytest.mark.parametrize("before,current,expected_new,expected_fixed", [
    ([], "2 passed", [], []), ([], "FAILED test_new\n1 failed", ["test_new"], []),
    (["a","b"], "FAILED a\nFAILED b\n2 failed", [], []),
    (["a","b"], "FAILED a\nFAILED b\nFAILED c\n3 failed", ["c"], []),
    (["a","b"], "FAILED a\n1 failed", [], ["b"]),
])
@pytest.mark.asyncio
async def test_verifier_failure_regressions(tmp_path, before, current, expected_new, expected_fixed):
    registry = ProfileRegistry(); registry.put(tmp_path, profile(before))
    responses = [result(["git"], stdout=""), result(["git"], stdout=""),
        result(["pytest"], stdout=current, code=1 if "failed" in current else 0), result(["build"])]
    verified = await RealVerifier(registry, QueueRunner(responses)).verify(item(), tmp_path)
    assert verified.newly_failing_tests == expected_new and verified.fixed_tests == expected_fixed
    assert verified.passed is (not expected_new)


@pytest.mark.asyncio
async def test_verifier_unnamed_failure_affected_failure_and_build_regression(tmp_path):
    registry = ProfileRegistry(); registry.put(tmp_path, profile())
    runner = QueueRunner([result(["git"], stdout="src/x.py"), result(["git"], stdout=""),
        result(["pytest"], code=2, stderr="collection error"), result(["build"], code=1)])
    verified = await RealVerifier(registry, runner).verify(item(), tmp_path)
    assert verified.test_execution_failed and not verified.affected_tests_failed and verified.build_regression and not verified.passed


@pytest.mark.asyncio
async def test_verifier_stops_after_mapped_affected_test_failure(tmp_path):
    (tmp_path / "tests").mkdir(); (tmp_path / "tests/test_x.py").write_text("")
    registry = ProfileRegistry(); registry.put(tmp_path, profile())
    runner = QueueRunner([result(["git"], stdout="src/x.py"), result(["git"], stdout=""),
        result(["pytest"], code=1, stdout="FAILED tests/test_x.py::test_bad\n1 failed")])
    verified = await RealVerifier(registry, runner).verify(item(), tmp_path)
    assert verified.affected_tests_failed and not verified.passed and len(runner.commands) == 3


def test_affected_test_all_extensions_and_fallback(tmp_path):
    mapper = AffectedTests(QueueRunner([])); py = profile()
    for suffix in (".js", ".jsx", ".ts", ".tsx"):
        source = tmp_path / "src" / f"foo{suffix}"; target = tmp_path / "src" / f"foo.test{suffix}"
        source.parent.mkdir(exist_ok=True); target.write_text("")
        node = profile().model_copy(update={"language":"TypeScript"})
        assert mapper.select(tmp_path, [f"src/foo{suffix}"], node)[0] == [f"src/foo.test{suffix}"]
        target.unlink()
    assert mapper.select(tmp_path, ["src/nope.py"], py)[1] is not None


def test_scanner_partial_malformed_and_legacy_npm():
    assert parse_npm_audit("not json") == []
    legacy = parse_npm_audit('{"advisories":{"1":{"id":1,"module_name":"x","severity":"low","patched_versions":">=2"}}}')
    assert legacy[0].dependency == "x" and legacy[0].fix_available


@pytest.mark.asyncio
async def test_mutation_unavailable_timeout_zero_and_malformed(tmp_path):
    unavailable = result(["mutmut"], code=None, status=ExecutionStatus.UNAVAILABLE, unavailable=True)
    report = await MutmutRunner(QueueRunner([unavailable])).run(tmp_path, ["x.py"])
    assert report.status is ExecutionStatus.UNAVAILABLE
    assert parse_mutmut("nothing").score is None
    assert parse_mutmut("1/1 🎉 1 🫥 0 ⏰ 0 🤔 0 🙁 0").score == 100
    assert parse_stryker("bad").score is None
    assert parse_stryker('{"files":{}}').status is ExecutionStatus.NOT_APPLICABLE


def test_quality_reweighting_validation_and_boundaries():
    assert quality_score(80, 50, 100) == 76
    assert quality_score(80, None, None) == 80
    assert quality_score(None, 50, 100) == 66.7
    assert quality_score(None, None, None) is None
    with pytest.raises(ValueError): quality_score(101, None, None)
    assert [grade(x) for x in (39.9,40,60,75,90)] == ["poor","weak","moderate","strong","excellent"]


@pytest.mark.asyncio
async def test_changed_files_combines_tracked_staged_untracked_and_deduplicates(tmp_path):
    runner = QueueRunner([result(["git"], stdout="src/a.py\ntests/test_a.py\n"),
                          result(["git"], stdout="tests\\test_a.py\ntests/test_new.py\n")])
    detected = await RealVerifier(ProfileRegistry(), runner).detect_changed_files(tmp_path)
    assert detected.reliable
    assert detected.files == ["src/a.py", "tests/test_a.py", "tests/test_new.py"]
    assert runner.commands == [["git", "diff", "--name-only", "HEAD"],
                               ["git", "ls-files", "--others", "--exclude-standard"]]


@pytest.mark.asyncio
async def test_changed_files_real_git_unstaged_staged_and_untracked(tmp_path):
    runner = AsyncCommandRunner(default_timeout=3)
    for command in (["git", "init"], ["git", "config", "user.email", "audit@example.invalid"],
                    ["git", "config", "user.name", "Audit"]):
        assert (await runner.run(command, cwd=tmp_path)).exit_code == 0
    unstaged, staged = tmp_path / "unstaged.py", tmp_path / "staged.py"
    unstaged.write_text("before\n"); staged.write_text("before\n")
    assert (await runner.run(["git", "add", "."], cwd=tmp_path)).exit_code == 0
    assert (await runner.run(["git", "commit", "-m", "fixture"], cwd=tmp_path)).exit_code == 0
    unstaged.write_text("after\n"); staged.write_text("after\n")
    assert (await runner.run(["git", "add", "staged.py"], cwd=tmp_path)).exit_code == 0
    (tmp_path / "test_new.py").write_text("def test_new(): pass\n")
    detected = await RealVerifier(ProfileRegistry(), runner).detect_changed_files(tmp_path)
    assert detected.reliable
    assert set(detected.files) == {"unstaged.py", "staged.py", "test_new.py"}


@pytest.mark.asyncio
async def test_changed_files_failure_is_preserved_and_public_api_raises(tmp_path):
    failed = result(["git"], code=128, stderr="not a git repository")
    runner = QueueRunner([failed, failed, result(["git"], stdout="new.py")])
    verifier = RealVerifier(ProfileRegistry(), runner)
    detected = await verifier.detect_changed_files(tmp_path)
    assert not detected.reliable and "git diff" in detected.reason
    runner.responses = [failed, failed, result(["git"], stdout="")]
    with pytest.raises(RuntimeError, match="git diff"):
        await verifier.changed_files(tmp_path)


@pytest.mark.asyncio
async def test_changed_file_failure_forces_full_suite_and_skips_mutation(tmp_path):
    registry = ProfileRegistry(); registry.put(tmp_path, profile(build=False))
    failed = result(["git"], code=128, stderr="not a git repository")
    runner = QueueRunner([failed, failed, result(["git"], code=128, stderr="not a git repository"),
                          result(["pytest"], stdout="1 passed"), result(["build"], code=1)])
    verified = await RealVerifier(registry, runner).verify(item(), tmp_path)
    assert verified.passed
    assert verified.affected_test_result.selected_tests == []
    assert "git diff" in verified.affected_test_result.fallback_reason
    assert verified.mutation_report.status is ExecutionStatus.NOT_APPLICABLE


@pytest.mark.asyncio
async def test_full_suite_fallback_is_reused_and_command_metrics_are_exact(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO_SURGEON_COVERAGE_POLICY", "disabled")
    registry = ProfileRegistry(); registry.put(tmp_path, profile())
    runner = QueueRunner([result(["git"], stdout="src/unmapped.py"), result(["git"], stdout=""),
                          result(["pytest"], stdout="1 passed"), result(["build"])])
    verified = await RealVerifier(registry, runner).verify(item(), tmp_path)
    assert runner.commands == [["git", "diff", "--name-only", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"], ["pytest"], ["build"]]
    assert verified.full_suite_reused and verified.command_count == 4
    assert verified.verification_duration_seconds >= 0
    assert not verified.coverage_executed and not verified.mutation_executed


@pytest.mark.asyncio
async def test_mapped_affected_success_still_requires_final_full_suite_and_build(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO_SURGEON_COVERAGE_POLICY", "disabled")
    (tmp_path / "tests").mkdir(); (tmp_path / "tests/test_x.py").write_text("")
    registry = ProfileRegistry(); registry.put(tmp_path, profile())
    runner = QueueRunner([result(["git"], stdout="src/x.py"), result(["git"], stdout=""),
                          result(["pytest", "tests/test_x.py"], stdout="1 passed"),
                          result(["pytest"], stdout="1 passed"), result(["build"])])
    verified = await RealVerifier(registry, runner).verify(item(), tmp_path)
    assert runner.commands[-3:] == [["pytest", "tests/test_x.py"], ["pytest"], ["build"]]
    assert not verified.full_suite_reused and verified.full_test_result.command == ["pytest"]
    assert verified.command_count == 5 and verified.passed


@pytest.mark.asyncio
async def test_final_verification_cannot_be_green_without_a_test_command(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO_SURGEON_COVERAGE_POLICY", "disabled")
    candidate = profile()
    candidate.baseline.test_command = None
    registry = ProfileRegistry(); registry.put(tmp_path, candidate)
    runner = QueueRunner([result(["git"], stdout="src/x.py"), result(["git"], stdout=""),
                          result(["build"])])
    verified = await RealVerifier(registry, runner).verify(item(), tmp_path)
    assert verified.full_test_result is None and verified.test_execution_failed
    assert not verified.passed and runner.commands[-1] == ["build"]


@pytest.mark.asyncio
async def test_coverage_is_delayed_until_candidate_tests_are_green(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO_SURGEON_COVERAGE_POLICY", "final")
    (tmp_path / "tests").mkdir(); (tmp_path / "tests/test_x.py").write_text("")
    candidate = profile()
    candidate.baseline.coverage_command = ["pytest", "--cov"]
    registry = ProfileRegistry(); registry.put(tmp_path, candidate)
    runner = QueueRunner([result(["git"], stdout="src/x.py"), result(["git"], stdout=""),
        result(["pytest", "tests/test_x.py"], code=1,
            stdout="FAILED tests/test_x.py::test_bad\n1 failed")])
    verified = await RealVerifier(registry, runner).verify(item(), tmp_path)
    assert len(runner.commands) == 3
    assert not verified.coverage_executed and verified.affected_tests_failed


@pytest.mark.parametrize("manager,expected", [
    ("npm", ["npm", "test", "--", "src/foo.test.ts"]),
    ("pnpm", ["pnpm", "test", "--", "src/foo.test.ts"]),
    ("yarn", ["yarn", "test", "src/foo.test.ts"]),
])
@pytest.mark.asyncio
async def test_node_affected_test_argument_forwarding(tmp_path, manager, expected):
    (tmp_path / "src").mkdir(); (tmp_path / "src/foo.test.ts").write_text("")
    node = RepoProfile(language="TypeScript", package_manager=manager, test_runner="vitest",
        baseline=Baseline(test_command=[manager, "test"]))
    runner = QueueRunner([result(expected)])
    selected = await AffectedTests(runner).run(tmp_path, ["src/foo.ts"], node)
    assert selected.command == expected and runner.commands == [expected]


@pytest.mark.asyncio
async def test_untracked_test_and_changed_source_enable_mutation(tmp_path):
    runner = QueueRunner([result(["mutmut"], stdout="killed 1 survived 0"),
                          result(["mutmut", "results"], stdout="")])
    report = await MutationService(runner).run(tmp_path, ["src/widget.py", "tests/test_widget.py"], profile())
    assert report.status is ExecutionStatus.PASSED
    assert report.targeted_files == ["src/widget.py"]

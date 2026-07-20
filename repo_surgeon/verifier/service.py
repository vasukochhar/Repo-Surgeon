from __future__ import annotations
import logging
from pathlib import Path
from dataclasses import dataclass, field
from ..contracts import ExecutionStatus, RepoProfile, UpgradeItem, VerifyResult
from ..sandbox.command_runner import AsyncCommandRunner
from ..scout.baseline_runner import parse_test_output
from ..scout.coverage import parse_coverage
from ..scout.service import ProfileRegistry
from .affected_tests import AffectedTests
from .baseline_diff import compare_failures
from .mutation import MutationService
from .quality_score import quality_score

# Directories Repo Surgeon (or the tools it runs) creates inside the cloned
# repo — Scout's `pip install --target .repo-surgeon-deps`, and compiled
# bytecode/test caches left behind by running Python or pytest. These are
# never in the target repo's own .gitignore, so `git ls-files --others`
# reports them as "changed" — noise that isn't a migration edit at all. Left
# in, this pollutes changed-file detection and, through it, AffectedTests'
# filename heuristics (see affected_tests.py) — e.g. a `tests/__pycache__/*.pyc`
# file getting selected as if it were a test module to collect, which then
# fails outright since it isn't one.
SANDBOX_MANAGED_DIRS = {".repo-surgeon-deps", "__pycache__", ".pytest_cache", "node_modules",
                        ".turbo", ".next", "coverage", ".nyc_output"}

logger = logging.getLogger(__name__)


class RealVerifier:
    def __init__(self, registry: ProfileRegistry, runner: AsyncCommandRunner | None = None,
                 coverage_regression_threshold: float = 2.0) -> None:
        self.registry = registry; self.runner = runner or AsyncCommandRunner()
        self.coverage_regression_threshold = coverage_regression_threshold

    async def detect_changed_files(self, root: Path) -> "ChangedFilesResult":
        tracked = await self.runner.run(["git", "diff", "--name-only", "HEAD"], cwd=root)
        if tracked.status is not ExecutionStatus.PASSED:
            # An unborn repository has no HEAD; this fallback still captures staged/unstaged tracked paths.
            tracked = await self.runner.run(["git", "diff", "--name-only"], cwd=root)
        untracked = await self.runner.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=root)
        failures = [self._git_failure(name, value) for name, value in
                    (("git diff", tracked), ("git ls-files", untracked))
                    if value.status is not ExecutionStatus.PASSED]
        if failures:
            return ChangedFilesResult(reason="; ".join(failures))
        paths = [self._normalize_path(line) for value in (tracked, untracked)
                 for line in value.stdout.splitlines() if line.strip()]
        # Checks every path segment, not just the top-level one: __pycache__
        # (and, in principle, any of these) can appear nested under any
        # directory, not only at the repo root.
        paths = [path for path in paths if not set(Path(path).parts) & SANDBOX_MANAGED_DIRS]
        return ChangedFilesResult(files=list(dict.fromkeys(paths)))

    async def changed_files(self, root: Path) -> list[str]:
        detected = await self.detect_changed_files(root)
        if not detected.reliable:
            raise RuntimeError(detected.reason)
        return detected.files

    async def run_affected_tests(self, workdir: Path, changed_files: list[str], profile: RepoProfile,
                                 fallback_reason: str | None = None):
        return await AffectedTests(self.runner).run(workdir, changed_files, profile, fallback_reason)

    async def _reinstall(self, profile: RepoProfile, workdir: Path) -> str | None:
        """Re-run the install command before every verify() call.

        Codex's edit changes the dependency manifest, not what's actually on
        disk in `.repo-surgeon-deps` — without reinstalling, every test run
        below would import whatever was installed at baseline time, so an
        upgrade's edit would never actually get exercised no matter how
        correct it is. Returns a failure message (and skips testing entirely)
        if the install itself breaks, since a broken install means no
        installed code exists to test.
        """
        install_command = profile.baseline.install_command or profile.commands.install
        if not install_command:
            return None
        result = await self.runner.run(install_command, cwd=workdir)
        if result.exit_code not in (0, None):
            logger.warning("[%s] reinstall after edit failed (exit %s): %s", profile.repository.get("name"),
                           result.exit_code, (result.stderr or result.stdout or "").strip()[-1500:])
            return (f"Dependency install failed after this edit — nothing could be tested:\n"
                    f"{' '.join(install_command)}\n{(result.stderr or result.stdout or '').strip()[-2000:]}")
        return None

    async def verify(self, item: UpgradeItem, workdir: Path) -> VerifyResult:
        profile = self.registry.get(workdir)
        if profile is None: raise RuntimeError(f"no baseline profile registered for {workdir}")
        install_failure = await self._reinstall(profile, workdir)
        if install_failure is not None:
            return VerifyResult(item_id=item.id, regression_aware=True, test_execution_failed=True,
                logs=install_failure, concise_failure_context=install_failure)
        detected = await self.detect_changed_files(workdir)
        changed = detected.files
        affected = await self.run_affected_tests(workdir, changed, profile, detected.reason)
        affected_failed = bool(affected.selected_tests and affected.result and
                               affected.result.status is not ExecutionStatus.PASSED)
        if affected_failed:
            affected_text = affected.result.stdout + "\n" + affected.result.stderr
            _, affected_count, _, affected_names = parse_test_output(affected_text)
            # Only failures the baseline didn't already have count against this
            # item. A repo can arrive with tests that were failing before any
            # edit (e.g. a drifted transitive dependency breaking imports) —
            # blaming every item for that pre-existing breakage means no item
            # can ever pass, and none of them caused it. If everything named
            # here was already failing at baseline, fall through to the full
            # regression-aware run below instead of failing fast.
            affected_newly, _, _ = compare_failures(profile.baseline.failing_tests, affected_names)
            if affected_newly or not affected_names:
                context = self._context(affected_newly or affected.selected_tests, affected_text,
                                        affected.command, changed)
                return VerifyResult(item_id=item.id, tests_failed=max(affected_count, 1),
                    failing_tests=affected_names, newly_failing_tests=affected_newly,
                    regression_aware=True, affected_tests_failed=True,
                    affected_test_result=affected, logs=context or affected_text[-4000:],
                    concise_failure_context=context)
            logger.info("[%s] affected run failed only on pre-existing baseline failures %s — "
                        "not counting them against this item", item.id, affected_names)
            affected_failed = False
        full = (affected.result if not detected.reliable else
                await self.runner.run(profile.baseline.test_command, cwd=workdir)
                if profile.baseline.test_command else None)
        text = (full.stdout + "\n" + full.stderr) if full else ""
        passed, failed, _, failing = parse_test_output(text)
        newly, existing, fixed = compare_failures(profile.baseline.failing_tests, failing)
        full_failed = bool(full and full.exit_code not in (0, None))
        execution_unavailable = bool(full and full.status in {ExecutionStatus.TIMEOUT,
                                     ExecutionStatus.UNAVAILABLE, ExecutionStatus.UNSUPPORTED})
        # Neither an affected-tests run nor a full run happened at all — Scout
        # never found a test command for this stack. Absence of a failure is
        # not evidence of a pass: without this, VerifyResult.passed defaults to
        # True (no failing_tests, no build check) and the item ships as
        # "green" with zero tests actually executed.
        no_test_command = full is None and affected.result is None
        if no_test_command:
            logger.warning("[%s] no test command available for this stack — verification cannot run; "
                           "flagging for human review instead of a silent pass", item.id)
        unnamed_failure = execution_unavailable or (full_failed and not failing) or no_test_command
        build = await self.runner.run(profile.baseline.build_command, cwd=workdir) if profile.baseline.build_command else None
        build_ok = build.exit_code == 0 if build else True
        build_regression = profile.baseline.build_ok and not build_ok
        coverage_command = profile.baseline.coverage_command or profile.commands.coverage
        if coverage_command:
            await self.runner.run(coverage_command, cwd=workdir)
        coverage = parse_coverage(workdir); before = profile.baseline.coverage; after = coverage.line_percent
        delta = round(after - before, 2) if before is not None and after is not None else None
        coverage_regression = delta is not None and delta < -self.coverage_regression_threshold
        mutation = (await MutationService(self.runner).run(workdir, changed, profile)
                    if detected.reliable else MutationService.not_applicable(detected.reason or "changed-file detection failed"))
        score = quality_score(mutation.score, coverage.changed_code_percent, 100 if affected.result and affected.result.exit_code == 0 else None)
        context = self._context(newly, text, profile.baseline.test_command, changed)
        if no_test_command and not context:
            # newly_failing_tests is empty here (nothing ran to fail), so
            # _context() returns "" — without this override the failure_context
            # handed to the next Codex iteration is just "None", giving no clue
            # why an upgrade with no test failures still needs a human.
            context = ("No test command detected for this stack, so nothing could be run to verify "
                       "this change. Needs a human to confirm it's safe before merging.")
        return VerifyResult(item_id=item.id, tests_passed=passed, tests_failed=failed, failing_tests=failing,
            logs=context or text[-4000:], newly_failing_tests=newly, existing_failing_tests=existing, fixed_tests=fixed,
            build_ok=build_ok, baseline_build_ok=profile.baseline.build_ok, build_regression=build_regression,
            regression_aware=True, test_execution_failed=unnamed_failure,
            affected_tests_failed=affected_failed, coverage_regression=coverage_regression,
            coverage_before=before, coverage_after=after, coverage_delta=delta,
            mutation_report=mutation, test_quality_score=score, affected_test_result=affected,
            full_test_result=full, build_result=build, concise_failure_context=context)

    @staticmethod
    def _context(new: list[str], logs: str, command: list[str] | None, changed: list[str]) -> str:
        if not new: return ""
        meaningful = next((line for line in logs.splitlines() if "Error" in line or "Exception" in line), "")
        return f"New failures: {', '.join(new)}\nError: {meaningful}\nReproduce: {' '.join(command or [])}\nChanged: {', '.join(changed)}\n{logs[-1200:]}"

    @staticmethod
    def _normalize_path(value: str) -> str:
        return value.strip().replace("\\", "/").removeprefix("./")

    @staticmethod
    def _git_failure(label: str, result) -> str:
        detail = "timed out" if result.timed_out else "unavailable" if result.tool_unavailable else (
            result.stderr.strip().splitlines()[-1] if result.stderr.strip() else f"exit code {result.exit_code}")
        return f"{label} {detail}"


@dataclass
class ChangedFilesResult:
    files: list[str] = field(default_factory=list)
    reason: str | None = None

    @property
    def reliable(self) -> bool:
        return self.reason is None

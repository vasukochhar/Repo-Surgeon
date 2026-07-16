from __future__ import annotations
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
        return ChangedFilesResult(files=list(dict.fromkeys(paths)))

    async def changed_files(self, root: Path) -> list[str]:
        detected = await self.detect_changed_files(root)
        if not detected.reliable:
            raise RuntimeError(detected.reason)
        return detected.files

    async def run_affected_tests(self, workdir: Path, changed_files: list[str], profile: RepoProfile,
                                 fallback_reason: str | None = None):
        return await AffectedTests(self.runner).run(workdir, changed_files, profile, fallback_reason)

    async def verify(self, item: UpgradeItem, workdir: Path) -> VerifyResult:
        profile = self.registry.get(workdir)
        if profile is None: raise RuntimeError(f"no baseline profile registered for {workdir}")
        detected = await self.detect_changed_files(workdir)
        changed = detected.files
        affected = await self.run_affected_tests(workdir, changed, profile, detected.reason)
        affected_failed = bool(affected.selected_tests and affected.result and
                               affected.result.status is not ExecutionStatus.PASSED)
        if affected_failed:
            affected_text = affected.result.stdout + "\n" + affected.result.stderr
            _, affected_count, _, affected_names = parse_test_output(affected_text)
            context = self._context(affected_names or affected.selected_tests, affected_text,
                                    affected.command, changed)
            return VerifyResult(item_id=item.id, tests_failed=max(affected_count, 1),
                failing_tests=affected_names, newly_failing_tests=affected_names,
                regression_aware=True, affected_tests_failed=True,
                affected_test_result=affected, logs=context or affected_text[-4000:],
                concise_failure_context=context)
        full = (affected.result if not detected.reliable else
                await self.runner.run(profile.baseline.test_command, cwd=workdir)
                if profile.baseline.test_command else None)
        text = (full.stdout + "\n" + full.stderr) if full else ""
        passed, failed, _, failing = parse_test_output(text)
        newly, existing, fixed = compare_failures(profile.baseline.failing_tests, failing)
        full_failed = bool(full and full.exit_code not in (0, None))
        execution_unavailable = bool(full and full.status in {ExecutionStatus.TIMEOUT,
                                     ExecutionStatus.UNAVAILABLE, ExecutionStatus.UNSUPPORTED})
        unnamed_failure = execution_unavailable or (full_failed and not failing)
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

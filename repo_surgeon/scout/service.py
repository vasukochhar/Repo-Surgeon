from __future__ import annotations
import logging
import tempfile
from pathlib import Path
from ..contracts import DetectedCommands, ExecutionStatus, RepoProfile, StackInfo
from ..interfaces import CodexRunner
from ..trace import current_tracer
from ..sandbox.command_runner import AsyncCommandRunner
from ..security.service import SecurityService
from .baseline_runner import BaselineRunner
from .command_detector import CommandDetector
from .coverage import parse_coverage
from .dependency_collector import DependencyCollector
from .profile_writer import ProfileWriter
from .stack_detector import StackDetector

logger = logging.getLogger(__name__)


class ProfileRegistry:
    def __init__(self) -> None: self._profiles: dict[Path, RepoProfile] = {}
    def put(self, path: Path, profile: RepoProfile) -> None: self._profiles[path.resolve()] = profile
    def get(self, path: Path) -> RepoProfile | None: return self._profiles.get(path.resolve())
    def remove(self, path: Path) -> None: self._profiles.pop(path.resolve(), None)


class RealScout:
    def __init__(self, runner: AsyncCommandRunner | None = None, registry: ProfileRegistry | None = None,
                 output_root: Path | None = None, codex: CodexRunner | None = None) -> None:
        self.runner = runner or AsyncCommandRunner(); self.registry = registry or ProfileRegistry()
        self.detector = StackDetector(); self.commands = CommandDetector()
        self.output_root = output_root or Path(tempfile.gettempdir()) / "repo-surgeon-output"
        # Optional: lets profile() ask Codex to bootstrap a test suite when
        # none is detected, rather than leaving every upgrade unverifiable.
        self.codex = codex

    async def profile(self, workdir: Path) -> RepoProfile:
        tracer = current_tracer()
        stack = self.detector.detect(workdir); commands = self.commands.detect(workdir, stack)
        logger.info("stack detected: language=%s (%s) manager=%s runner=%s build=%s | manifests=%s lockfiles=%s",
                    stack.language, stack.language_version, stack.package_manager, stack.test_runner,
                    stack.build_tool, stack.dependency_files, stack.lockfiles)
        if stack.language == "unsupported":
            logger.warning("no recognised manifest at %s — contents: %s", workdir,
                           sorted(p.name for p in workdir.iterdir())[:40] if workdir.is_dir() else "<missing>")
        logger.info("commands detected: install=%s test=%s build=%s coverage=%s",
                    commands.install, commands.test, commands.build, commands.coverage)
        bootstrap_test_paths: list[str] = []
        if commands.test is None and stack.language in {"Python", "JavaScript", "TypeScript"} and self.codex is not None:
            stack, commands, bootstrap_test_paths = await self._bootstrap_tests(workdir, stack, commands, tracer)
        tracer.write("scout", "stack", {"stack": stack, "commands": commands, "workdir": workdir})

        baseline = await BaselineRunner(self.runner).run(workdir, commands)
        logger.info("baseline: %d passed, %d failed, %d skipped, build_ok=%s (test %.1fs, build %.1fs)",
                    baseline.tests_passed, baseline.tests_failed, baseline.tests_skipped,
                    baseline.build_ok, baseline.test_duration_seconds, baseline.build_duration_seconds)
        if baseline.failing_tests:
            logger.warning("baseline already has %d failing test(s) — these are excluded from "
                           "regression detection: %s", len(baseline.failing_tests), baseline.failing_tests[:20])
        tracer.write("scout", "baseline", baseline)
        if baseline.collection_failed:
            # A 0 passed / 0 failed baseline is not a clean slate — the test
            # runner exited non-zero without collecting anything. This used to
            # hard-stop the job here, but that's overly narrow: sometimes the
            # collection error *is* the bug this pipeline exists to fix (e.g.
            # an unpinned transitive dependency has drifted incompatible with
            # a pinned direct one — upgrading it is a normal planned item).
            # Baseline.failing_tests stays empty, so nothing here is treated as
            # a known pre-existing failure — every item's own verify() still
            # requires collection to actually succeed with no newly-failing
            # tests to go green (see VerifyResult.passed's test_execution_failed
            # check in verifier/service.py), so a persistently broken baseline
            # still can't slip through as a false pass. It just gets a real
            # chance to be fixed forward instead of blocking every item on a
            # problem none of them may even touch.
            tail = ((baseline.test_result.stdout if baseline.test_result else "") +
                    "\n" + (baseline.test_result.stderr if baseline.test_result else "")).strip()[-1500:]
            logger.warning("baseline test collection failed for %s — no tests were collected; "
                           "proceeding anyway since an upgrade may fix this. Each item still "
                           "requires collection to succeed with no new failures to go green: %s",
                           commands.test, tail)

        coverage = parse_coverage(workdir)
        if commands.coverage:
            coverage.command_result = await self.runner.run(commands.coverage, cwd=workdir)
            coverage = parse_coverage(workdir).model_copy(update={"command_result": coverage.command_result})
        logger.info("coverage: line=%s%% branch=%s%% (%s)", coverage.line_percent,
                    coverage.branch_percent, coverage.status.value)

        dependencies = await DependencyCollector(self.runner).collect(workdir, stack)
        upgradable = [d for d in dependencies if d.latest_version and d.latest_version != d.version]
        logger.info("dependencies: %d collected, %d with a newer version available",
                    len(dependencies), len(upgradable))
        if not dependencies:
            logger.warning("dependency collection returned nothing for a %s/%s project — "
                           "the manifest may be unreadable or the collector command failed above",
                           stack.language, stack.package_manager)
        tracer.write("scout", "dependencies", {"dependencies": dependencies,
                                               "upgradable": [d.name for d in upgradable]})

        security = await SecurityService(self.runner).scan(workdir, stack)
        logger.info("security: %d finding(s) across %d scanner(s), %d fixable, by severity %s",
                    security.total, len(security.scanners), security.fix_available_count,
                    security.counts_by_severity)
        for scanner in security.scanners:
            if scanner.status is not ExecutionStatus.PASSED:
                logger.warning("scanner %s did not run cleanly: %s — %s",
                               scanner.scanner, scanner.status.value, scanner.message)
        tracer.write("scout", "security", security)
        baseline.coverage = coverage.line_percent
        profile = RepoProfile(language=stack.language, package_manager=stack.package_manager,
            test_runner=stack.test_runner, baseline=baseline, dependencies=dependencies,
            vulnerabilities=security.findings, stack=stack, commands=commands, coverage_result=coverage,
            security_report=security, repository={"root": str(workdir), "name": workdir.name},
            bootstrap_test_paths=bootstrap_test_paths)
        ProfileWriter(self.output_root).write(profile, workdir)
        self.registry.put(workdir, profile)
        return profile

    async def cleanup_profile(self, workdir: Path) -> None:
        self.registry.remove(workdir)

    async def _bootstrap_tests(self, workdir: Path, stack: StackInfo, commands: DetectedCommands,
                               tracer) -> tuple[StackInfo, DetectedCommands, list[str]]:
        """No test command was found — ask Codex to write one before baseline runs.

        Without this, every upgrade on this repo is unverifiable: verify()
        finds no failures because nothing ran, and either silently reports a
        false pass, or (after that bug was fixed) correctly but uselessly
        flags every item needs_human with nothing a code edit can fix.

        Covers Python and JS/TS. Codex's own prompt (see CodexRunner.write_tests)
        differs by language — Python gets pytest against the sandbox image's
        preinstalled pytest with an add-files-only constraint; JS/TS gets
        Node's built-in test runner by default (nothing to install) and is
        allowed to touch package.json's "scripts.test" since there's no
        working test entrypoint to run without that wiring. Repos in any
        other language still fall through to the existing no-test-command
        safety net in verifier/service.py.
        """
        logger.info("no test command detected for this %s repo — asking Codex to write "
                    "a baseline test suite before any upgrades are attempted", stack.language)
        tracer.write("scout_bootstrap_tests", "input", {"workdir": workdir, "language": stack.language})
        try:
            edit = await self.codex.write_tests(workdir, stack.language)
        except RuntimeError as error:
            logger.warning("test bootstrap failed, proceeding without a test suite: %s", error)
            tracer.write("scout_bootstrap_tests", "error", {"error": str(error)})
            return stack, commands, []
        logger.info("test bootstrap wrote %d file(s): %s", len(edit.files_changed), edit.files_changed)
        tracer.write("scout_bootstrap_tests", "output", edit)
        if not edit.files_changed:
            logger.warning("test bootstrap produced no files — proceeding without a test suite")
            return stack, commands, []
        if stack.language in {"JavaScript", "TypeScript"}:
            # Codex was told to wire the runner into package.json's
            # "scripts.test" rather than dictating one, so `[manager, "test"]`
            # (npm/pnpm/yarn's own test entrypoint) is what actually reflects
            # whatever it chose — same convention CommandDetector already uses
            # for repos that had a working test script from the start.
            return (stack.model_copy(update={"test_runner": "node"}),
                    commands.model_copy(update={"test": [stack.package_manager, "test"]}),
                    edit.files_changed)
        # Trust pytest is present (it's baked into the sandbox image) rather
        # than re-running stack detection, which would need "pytest" written
        # into a manifest file to recognize it — see StackDetector.detect().
        return (stack.model_copy(update={"test_runner": "pytest"}),
                commands.model_copy(update={"test": ["python", "-m", "pytest"]}),
                edit.files_changed)

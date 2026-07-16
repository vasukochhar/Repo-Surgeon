from __future__ import annotations
import tempfile
from pathlib import Path
from ..contracts import RepoProfile
from ..sandbox.command_runner import AsyncCommandRunner
from ..security.service import SecurityService
from .baseline_runner import BaselineRunner
from .command_detector import CommandDetector
from .coverage import parse_coverage
from .dependency_collector import DependencyCollector
from .profile_writer import ProfileWriter
from .stack_detector import StackDetector


class ProfileRegistry:
    def __init__(self) -> None: self._profiles: dict[Path, RepoProfile] = {}
    def put(self, path: Path, profile: RepoProfile) -> None: self._profiles[path.resolve()] = profile
    def get(self, path: Path) -> RepoProfile | None: return self._profiles.get(path.resolve())
    def remove(self, path: Path) -> None: self._profiles.pop(path.resolve(), None)


class RealScout:
    def __init__(self, runner: AsyncCommandRunner | None = None, registry: ProfileRegistry | None = None,
                 output_root: Path | None = None) -> None:
        self.runner = runner or AsyncCommandRunner(); self.registry = registry or ProfileRegistry()
        self.detector = StackDetector(); self.commands = CommandDetector()
        self.output_root = output_root or Path(tempfile.gettempdir()) / "repo-surgeon-output"

    async def profile(self, workdir: Path) -> RepoProfile:
        stack = self.detector.detect(workdir); commands = self.commands.detect(workdir, stack)
        baseline = await BaselineRunner(self.runner).run(workdir, commands)
        coverage = parse_coverage(workdir)
        if commands.coverage:
            coverage.command_result = await self.runner.run(commands.coverage, cwd=workdir)
            coverage = parse_coverage(workdir).model_copy(update={"command_result": coverage.command_result})
        dependencies = await DependencyCollector(self.runner).collect(workdir, stack)
        security = await SecurityService(self.runner).scan(workdir, stack)
        baseline.coverage = coverage.line_percent
        profile = RepoProfile(language=stack.language, package_manager=stack.package_manager,
            test_runner=stack.test_runner, baseline=baseline, dependencies=dependencies,
            vulnerabilities=security.findings, stack=stack, commands=commands, coverage_result=coverage,
            security_report=security, repository={"root": str(workdir), "name": workdir.name})
        ProfileWriter(self.output_root).write(profile, workdir)
        self.registry.put(workdir, profile)
        return profile

    async def cleanup_profile(self, workdir: Path) -> None:
        self.registry.remove(workdir)

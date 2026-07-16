from __future__ import annotations
from pathlib import Path, PurePosixPath
from ..contracts import AffectedTestResult, RepoProfile
from ..sandbox.command_runner import AsyncCommandRunner


class AffectedTests:
    def __init__(self, runner: AsyncCommandRunner) -> None: self.runner = runner
    def select(self, root: Path, changed: list[str], profile: RepoProfile) -> tuple[list[str], str | None]:
        selected = []
        for raw in changed:
            path = PurePosixPath(raw.replace("\\", "/"))
            if "test" in path.name.lower() and (root / path).exists(): selected.append(str(path))
            stem = path.stem
            if profile.language == "Python" and path.suffix == ".py":
                candidates = [PurePosixPath("tests") / f"test_{stem}.py", path.with_name(f"test_{stem}.py")]
            elif profile.language in {"JavaScript", "TypeScript"} and path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
                candidates = [path.with_name(f"{stem}.test{path.suffix}"), path.with_name(f"{stem}.spec{path.suffix}"), PurePosixPath("tests") / f"{stem}.test{path.suffix}"]
            else: candidates = []
            selected.extend(str(x) for x in candidates if (root / x).exists())
        selected = list(dict.fromkeys(selected))
        return (selected, None) if selected else ([], "no affected test mapping; full-suite fallback")

    async def run(self, root: Path, changed: list[str], profile: RepoProfile,
                  forced_fallback_reason: str | None = None) -> AffectedTestResult:
        tests, reason = self.select(root, changed, profile)
        if forced_fallback_reason:
            tests, reason = [], forced_fallback_reason
        base = profile.baseline.test_command or profile.commands.test or []
        command = self._command(base, tests, profile)
        result = await self.runner.run(command, cwd=root) if command else None
        return AffectedTestResult(selected_tests=tests, command=command, result=result,
            fallback_reason=reason, duration_seconds=result.duration_seconds if result else 0)

    @staticmethod
    def _command(base: list[str], tests: list[str], profile: RepoProfile) -> list[str]:
        if not tests:
            return list(base)
        manager = profile.stack.package_manager if profile.stack else profile.package_manager
        if manager in {"npm", "pnpm"}:
            return [*base, "--", *tests]
        if manager == "yarn":
            return [*base, *tests]
        return [*base, *tests]

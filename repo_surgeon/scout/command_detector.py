from __future__ import annotations

import json
from pathlib import Path
from ..contracts import DetectedCommands, StackInfo


class CommandDetector:
    def detect(self, root: Path, stack: StackInfo) -> DetectedCommands:
        if stack.language == "Python":
            if stack.package_manager == "uv": install = ["uv", "sync"]
            elif stack.package_manager == "poetry": install = ["poetry", "install"]
            elif stack.package_manager == "pipenv": install = ["pipenv", "install", "--dev"]
            # --upgrade matters beyond baseline: verify() re-runs this same
            # install command after every Codex edit so an upgraded pin
            # actually gets installed (see verifier/service.py). Without it,
            # pip leaves an already-present package alone even when the
            # requirement now pins a different version, so the edit would
            # never take effect and every item would test against stale deps.
            elif (root / "requirements.txt").exists():
                install = ["python", "-m", "pip", "install", "--upgrade", "--target", ".repo-surgeon-deps", "-r", "requirements.txt"]
            else:
                install = ["python", "-m", "pip", "install", "--upgrade", "--target", ".repo-surgeon-deps", ".[dev]"]
            test = (["python", "-m", "pytest"] if stack.test_runner == "pytest" else
                    ["python", "-m", "unittest", "discover"] if stack.test_runner == "unittest" else None)
            build = ["python", "-m", "build"] if stack.build_tool else None
            coverage_target = self._python_coverage_target(root)
            coverage = ([*test, f"--cov={coverage_target}", "--cov-report=json"]
                        if test and stack.test_runner == "pytest" else None)
            return DetectedCommands(install=install, test=test, build=build, coverage=coverage)
        if stack.language in {"JavaScript", "TypeScript"}:
            try:
                data = json.loads((root / "package.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return DetectedCommands()
            manager = stack.package_manager
            # Deliberately not `npm ci` / `--frozen-lockfile`: those require
            # package.json and the lockfile to match exactly and hard-fail
            # otherwise. verify() re-runs this same install command after every
            # Codex edit (see verifier/service.py._reinstall) — the instant
            # Codex bumps a version pin in package.json without hand-editing
            # the lockfile to match byte-for-byte, a frozen/ci install would
            # error out instead of installing the edit, and the item would
            # never get a real chance to pass. Plain `install` updates the
            # lockfile itself, same tradeoff as pip's --upgrade above: less
            # deterministic than a frozen baseline, but the edit actually gets
            # tested instead of the reinstall silently failing.
            install = [manager, "install"]
            run = [manager, "test"] if manager == "npm" else [manager, "test"]
            build = [manager, "run", "build"] if "build" in data.get("scripts", {}) else None
            coverage = [manager, "run", "coverage"] if "coverage" in data.get("scripts", {}) else None
            supported_test = stack.test_runner in {"jest", "vitest", "mocha", "ava", "node"}
            return DetectedCommands(install=install, test=run if supported_test and "test" in data.get("scripts", {}) else None,
                build=build, coverage=coverage)
        return DetectedCommands()

    @staticmethod
    def _python_coverage_target(root: Path) -> str:
        candidates = sorted(path.relative_to(root).as_posix() for path in root.iterdir()
            if path.is_dir() and (path / "__init__.py").exists() and
            path.name not in {"tests", ".repo-surgeon-deps"})
        return candidates[0] if candidates else "."

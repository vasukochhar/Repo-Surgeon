from __future__ import annotations

import json
from pathlib import Path

from ..contracts import StackInfo


class StackDetector:
    def detect(self, root: Path) -> StackInfo:
        py_files = [name for name in ("pyproject.toml", "requirements.txt", "requirements-dev.txt",
            "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock",
            "tox.ini", "pytest.ini") if (root / name).exists()]
        node_files = [name for name in ("package.json", "package-lock.json", "yarn.lock",
            "pnpm-lock.yaml", "tsconfig.json") if (root / name).exists()]
        py_count = len(list(root.glob("**/pyproject.toml")))
        package_files = list(root.glob("**/package.json"))
        if node_files and (not py_files or "package.json" in node_files):
            data = self._json(root / "package.json")
            if not data:
                return StackInfo(language="TypeScript" if (root / "tsconfig.json").exists() else "JavaScript",
                    dependency_files=["package.json"], package_manager="unknown", test_runner="unknown")
            manager = self._node_manager(data, node_files)
            runner = self._node_runner(data)
            language = "TypeScript" if (root / "tsconfig.json").exists() else "JavaScript"
            workspaces = bool(data.get("workspaces")) or (root / "pnpm-workspace.yaml").exists()
            return StackInfo(language=language, package_manager=manager, test_runner=runner,
                build_tool=manager if "build" in data.get("scripts", {}) else None,
                dependency_files=["package.json"], lockfiles=[f for f in node_files if "lock" in f],
                is_monorepo=workspaces or len(package_files) > 1)
        if py_files or (root / "tests").exists():
            manager = ("uv" if "uv.lock" in py_files else "poetry" if "poetry.lock" in py_files else
                "pipenv" if any(x in py_files for x in ("Pipfile", "Pipfile.lock")) else "pip")
            text = "\n".join((root / f).read_text(encoding="utf-8", errors="ignore")
                for f in py_files if (root / f).is_file())
            has_unittest = any("unittest" in p.read_text(encoding="utf-8", errors="ignore")
                for p in root.glob("**/test*.py") if p.is_file())
            runner = "tox" if "tox.ini" in py_files and "[testenv]" in text else (
                "pytest" if "pytest" in text or "pytest.ini" in py_files else "unittest" if has_unittest else "unknown")
            return StackInfo(language="Python", package_manager=manager, test_runner=runner,
                build_tool="python-build" if "[build-system]" in text else None,
                dependency_files=[f for f in py_files if f.startswith("requirements") or f in {"pyproject.toml", "Pipfile"}],
                lockfiles=[f for f in py_files if f.endswith(".lock") or f == "uv.lock"],
                is_monorepo=py_count > 1)
        return StackInfo()

    @staticmethod
    def _json(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _node_manager(data: dict, files: list[str]) -> str:
        declared = data.get("packageManager", "").split("@")[0]
        if declared in {"npm", "pnpm", "yarn"}:
            return declared
        return "pnpm" if "pnpm-lock.yaml" in files else "yarn" if "yarn.lock" in files else "npm"

    @staticmethod
    def _node_runner(data: dict) -> str:
        script = data.get("scripts", {}).get("test", "")
        for candidate in ("vitest", "jest", "mocha", "ava"):
            if candidate in script or candidate in data.get("devDependencies", {}):
                return candidate
        return "node" if "node --test" in script else "unknown"

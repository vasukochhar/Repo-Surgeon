from __future__ import annotations
from pathlib import Path
from ..contracts import ExecutionStatus, MutationReport, RepoProfile
from ..sandbox.command_runner import AsyncCommandRunner
from .mutmut_runner import MutmutRunner
from .stryker_runner import StrykerRunner


class MutationService:
    def __init__(self, runner: AsyncCommandRunner, max_files: int = 10) -> None: self.runner, self.max_files = runner, max_files
    async def run(self, root: Path, changed: list[str], profile: RepoProfile) -> MutationReport:
        tests_changed = any(_is_test_file(x) for x in changed)
        sources = [x for x in changed if not _is_test_file(x) and Path(x).suffix in {".py", ".js", ".jsx", ".ts", ".tsx"}][:self.max_files]
        if not tests_changed or not sources: return MutationReport(tool="none", status=ExecutionStatus.NOT_APPLICABLE)
        return await (MutmutRunner(self.runner).run(root, sources) if profile.language == "Python" else StrykerRunner(self.runner).run(root, sources))

    @staticmethod
    def not_applicable(reason: str) -> MutationReport:
        return MutationReport(tool="none", status=ExecutionStatus.NOT_APPLICABLE,
                              command_result=None)


def _is_test_file(value: str) -> bool:
    path = Path(value.replace("\\", "/"))
    name = path.name.lower()
    return "tests" in {part.lower() for part in path.parts} or name.startswith("test_") or any(
        marker in name for marker in (".test.", ".spec."))

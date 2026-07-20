"""RealScout asking Codex to bootstrap a test suite when Scout finds no test
command — added after real-mode E2E testing showed a repo with no tests
(app.py + requirements.txt, nothing else) could never produce a verified
upgrade, only an honest but unhelpful needs_human every time."""
import pytest

from repo_surgeon.contracts import DetectedCommands, EditResult, StackInfo
from repo_surgeon.scout.service import RealScout
from repo_surgeon.trace import NullTracer


class _StubCodex:
    def __init__(self, files_changed: list[str] | None = ("tests/test_bootstrap.py",)) -> None:
        self.calls: list[tuple] = []
        self._files_changed = list(files_changed) if files_changed else []

    async def write_tests(self, workdir, language):
        self.calls.append((workdir, language))
        return EditResult(files_changed=self._files_changed, patch="+test file", logs="ok")


class _FailingCodex:
    async def write_tests(self, workdir, language):
        raise RuntimeError("codex exec failed")


@pytest.mark.asyncio
async def test_bootstrap_sets_pytest_as_the_test_command(tmp_path):
    codex = _StubCodex()
    scout = RealScout(codex=codex)
    stack = StackInfo(language="Python", package_manager="pip", test_runner="unknown")
    commands = DetectedCommands(install=["pip", "install"], test=None, build=None, coverage=None)

    new_stack, new_commands, bootstrap_paths = await scout._bootstrap_tests(tmp_path, stack, commands, NullTracer())

    assert codex.calls == [(tmp_path, "Python")]
    assert new_commands.test == ["python", "-m", "pytest"]
    assert new_stack.test_runner == "pytest"
    assert bootstrap_paths == ["tests/test_bootstrap.py"]


@pytest.mark.asyncio
async def test_bootstrap_failure_leaves_commands_unchanged(tmp_path):
    """A bootstrap failure must not crash the job — Scout falls back to the
    existing no-test-command path, which needs_human's honestly."""
    scout = RealScout(codex=_FailingCodex())
    stack = StackInfo(language="Python", package_manager="pip", test_runner="unknown")
    commands = DetectedCommands(install=None, test=None, build=None, coverage=None)

    new_stack, new_commands, bootstrap_paths = await scout._bootstrap_tests(tmp_path, stack, commands, NullTracer())

    assert new_commands.test is None
    assert new_stack.test_runner == "unknown"
    assert bootstrap_paths == []


@pytest.mark.asyncio
async def test_bootstrap_no_files_written_leaves_commands_unchanged(tmp_path):
    scout = RealScout(codex=_StubCodex(files_changed=[]))
    stack = StackInfo(language="Python", package_manager="pip", test_runner="unknown")
    commands = DetectedCommands(install=None, test=None, build=None, coverage=None)

    new_stack, new_commands, bootstrap_paths = await scout._bootstrap_tests(tmp_path, stack, commands, NullTracer())

    assert new_commands.test is None
    assert new_stack.test_runner == "unknown"
    assert bootstrap_paths == []


def test_real_scout_defaults_codex_to_none():
    # Ensures existing callers that don't pass codex= (mock mode, older tests)
    # keep working: profile() only bootstraps when self.codex is not None.
    assert RealScout().codex is None


@pytest.mark.asyncio
async def test_bootstrap_sets_npm_test_as_the_test_command(tmp_path):
    codex = _StubCodex(files_changed=["tests/app.test.js", "package.json"])
    scout = RealScout(codex=codex)
    stack = StackInfo(language="JavaScript", package_manager="npm", test_runner="unknown")
    commands = DetectedCommands(install=["npm", "install"], test=None, build=None, coverage=None)

    new_stack, new_commands, bootstrap_paths = await scout._bootstrap_tests(tmp_path, stack, commands, NullTracer())

    assert codex.calls == [(tmp_path, "JavaScript")]
    assert new_commands.test == ["npm", "test"]
    assert new_stack.test_runner == "node"
    assert bootstrap_paths == ["tests/app.test.js", "package.json"]


@pytest.mark.asyncio
async def test_bootstrap_respects_pnpm_as_the_package_manager(tmp_path):
    codex = _StubCodex(files_changed=["tests/app.test.ts"])
    scout = RealScout(codex=codex)
    stack = StackInfo(language="TypeScript", package_manager="pnpm", test_runner="unknown")
    commands = DetectedCommands(install=["pnpm", "install"], test=None, build=None, coverage=None)

    _, new_commands, _ = await scout._bootstrap_tests(tmp_path, stack, commands, NullTracer())

    assert new_commands.test == ["pnpm", "test"]


@pytest.mark.asyncio
async def test_bootstrap_failure_leaves_commands_unchanged_for_js(tmp_path):
    scout = RealScout(codex=_FailingCodex())
    stack = StackInfo(language="JavaScript", package_manager="npm", test_runner="unknown")
    commands = DetectedCommands(install=None, test=None, build=None, coverage=None)

    new_stack, new_commands, bootstrap_paths = await scout._bootstrap_tests(tmp_path, stack, commands, NullTracer())

    assert new_commands.test is None
    assert new_stack.test_runner == "unknown"
    assert bootstrap_paths == []

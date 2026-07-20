"""RealCodexRunner._diff must exclude Scout's bootstrapped test files from
every item's own patch — they're scratch fixtures used to verify every
upgrade attempt, not part of any single item's migration. Without this,
Codex's first dependency edit would ship the whole test suite bundled into
that item's PR (see orchestrator.py's bootstrap_test_paths threading)."""
import subprocess

import pytest

from repo_surgeon.codex_runner import RealCodexRunner


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "a@a.com")
    _git(tmp_path, "config", "user.name", "a")
    (tmp_path / "requirements.txt").write_text("flask==1.1.2\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


@pytest.mark.asyncio
async def test_diff_excludes_preserved_paths(repo):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (repo / "scratch.txt").write_text("real edit\n", encoding="utf-8")

    runner = RealCodexRunner()
    patch = await runner._diff(repo, preserve_paths=frozenset({"tests/test_app.py"}))

    assert "tests/test_app.py" not in patch
    assert "scratch.txt" in patch


@pytest.mark.asyncio
async def test_diff_includes_everything_without_preserve_paths(repo):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("def test_x():\n    pass\n", encoding="utf-8")

    runner = RealCodexRunner()
    patch = await runner._diff(repo)

    assert "tests/test_app.py" in patch


def test_is_generated_respects_preserve_paths():
    runner = RealCodexRunner()
    assert runner._is_generated("tests/test_app.py", frozenset({"tests/test_app.py"})) is True
    assert runner._is_generated("tests/test_app.py") is False
    assert runner._is_generated(".pytest_cache/CACHEDIR.TAG") is True


def test_is_generated_matches_nested_pycache():
    # __pycache__ can appear under any directory, not just the repo root
    # (tests/__pycache__, app/__pycache__, ...) — matching only the first path
    # segment missed all of those, letting compiled bytecode leak into item
    # patches and get selected by AffectedTests as if it were a test module.
    runner = RealCodexRunner()
    assert runner._is_generated("tests/__pycache__/test_app.cpython-312-pytest-9.1.1.pyc") is True
    assert runner._is_generated("app/nested/__pycache__/mod.pyc") is True

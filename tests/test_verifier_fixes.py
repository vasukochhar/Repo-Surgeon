"""Regression tests for bugs found during real-mode E2E testing (2026-07-20):
a repo with no detectable test runner made AffectedTests build a command out
of bare filenames (the sandbox tried to exec a .pyc directly), and separately
made RealVerifier.verify() silently report a pass despite running zero tests.
"""
import subprocess

import pytest

from repo_surgeon.contracts import Baseline, RepoProfile, UpgradeCategory, UpgradeItem
from repo_surgeon.sandbox.command_runner import AsyncCommandRunner
from repo_surgeon.scout.service import ProfileRegistry
from repo_surgeon.verifier.affected_tests import AffectedTests
from repo_surgeon.verifier.service import RealVerifier


@pytest.mark.asyncio
async def test_affected_tests_never_synthesizes_a_command_from_filenames(tmp_path):
    # A "test"-named file existing on disk is exactly what tripped the bug:
    # select() matches on filename alone, so without the fix in run(), this
    # would become the entire command with no real test runner in front of it.
    (tmp_path / "vendored_testing.py").write_text("", encoding="utf-8")
    profile = RepoProfile(language="Python", package_manager="pip", test_runner="unknown", baseline=Baseline())
    result = await AffectedTests(AsyncCommandRunner()).run(tmp_path, ["vendored_testing.py"], profile)
    assert result.command == []
    assert result.result is None
    assert result.fallback_reason == "no test command detected for this stack"


def _init_git_repo(root) -> None:
    for args in (["git", "init"], ["git", "config", "user.email", "a@b.c"], ["git", "config", "user.name", "t"]):
        subprocess.run(args, cwd=root, check=True, capture_output=True)
    (root / "README.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)


@pytest.mark.asyncio
async def test_detect_changed_files_excludes_sandbox_managed_deps(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "real_change.py").write_text("x", encoding="utf-8")
    deps_dir = tmp_path / ".repo-surgeon-deps" / "somepkg"
    deps_dir.mkdir(parents=True)
    (deps_dir / "testing.py").write_text("x", encoding="utf-8")

    verifier = RealVerifier(ProfileRegistry(), AsyncCommandRunner())
    result = await verifier.detect_changed_files(tmp_path)

    assert "real_change.py" in result.files
    assert not any(f.startswith(".repo-surgeon-deps") for f in result.files)


@pytest.mark.asyncio
async def test_verify_flags_needs_human_when_no_test_command_exists(tmp_path):
    """The dangerous silent case: no test command anywhere means nothing ran,
    but the old code's default (no failures found => pass) would still mark
    the upgrade green. It must fail verification instead, loudly."""
    _init_git_repo(tmp_path)
    registry = ProfileRegistry()
    profile = RepoProfile(language="Python", package_manager="pip", test_runner="unknown", baseline=Baseline())
    registry.put(tmp_path, profile)
    item = UpgradeItem(id="u1", dependency="idna", from_version="2.10", to_version="3.7",
                       category=UpgradeCategory.SECURITY, risk=0.5, rationale="CVE")

    verifier = RealVerifier(registry, AsyncCommandRunner())
    result = await verifier.verify(item, tmp_path)

    assert result.test_execution_failed is True
    assert result.passed is False
    assert "no test command" in result.logs.lower()

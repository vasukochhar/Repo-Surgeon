"""GitHub check-run polling and bounded Codex repair loop."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional, Protocol

from .contracts import PRResult
from .github_layer import GitHubClient


class CheckRunClient(Protocol):
    async def check_runs(self, repository: str, sha: str) -> list[dict]: ...


Repair = Callable[[PRResult, str, Path], Awaitable[Optional[str]]]


class GitHubCIWatcher:
    """Poll GitHub checks and re-run a bounded repair callback for failed PRs."""

    def __init__(self, client: CheckRunClient, repository: str | None = None, repair: Repair | None = None,
                 poll_seconds: float = 20, max_polls: int = 30, max_repairs: int = 2) -> None:
        self.client, self.repository, self.repair = client, repository, repair
        self.poll_seconds, self.max_polls, self.max_repairs = poll_seconds, max_polls, max_repairs

    async def watch(self, prs: list[PRResult], workdir: Path) -> list[PRResult]:
        return [await self._watch_pr(pr, workdir) for pr in prs]

    async def _watch_pr(self, pr: PRResult, workdir: Path) -> PRResult:
        if not pr.head_sha:
            return pr.model_copy(update={"ci_status": "unavailable", "ci_logs": "PR has no head SHA."})
        repository = pr.repository or self.repository
        if not repository:
            return pr.model_copy(update={"ci_status": "unavailable", "ci_logs": "PR has no GitHub repository."})
        current, repairs = pr, 0
        polls = 0
        while polls < self.max_polls:
            checks = await self.client.check_runs(repository, current.head_sha)
            polls += 1
            if not checks or any(check.get("status") != "completed" for check in checks):
                if polls < self.max_polls:
                    await asyncio.sleep(self.poll_seconds)
                continue
            failures = [check for check in checks if check.get("conclusion") not in {"success", "neutral", "skipped"}]
            if not failures:
                return current.model_copy(update={"ci_status": "passed", "ci_logs": None})
            logs = self._failure_logs(failures)
            if self.repair is None or repairs >= self.max_repairs:
                return current.model_copy(update={"ci_status": "failed", "ci_logs": logs})
            repaired_sha = await self.repair(current, logs, workdir)
            if not repaired_sha:
                return current.model_copy(update={"ci_status": "needs_human", "ci_logs": logs})
            current = current.model_copy(update={"head_sha": repaired_sha, "ci_status": "repairing", "ci_logs": logs})
            repairs += 1
            polls = 0
        return current.model_copy(update={"ci_status": "timed_out", "ci_logs": "Timed out waiting for GitHub checks."})

    @staticmethod
    def _failure_logs(checks: list[dict]) -> str:
        chunks = []
        for check in checks:
            output = check.get("output") or {}
            chunks.append("\n".join(filter(None, [
                f"{check.get('name', 'check')} ({check.get('conclusion', 'failed')})",
                output.get("title"), output.get("summary"), output.get("text"),
            ])))
        return "\n\n".join(chunks)[:20_000]


class CodexCIFixer:
    """Apply a focused CI repair on the PR branch and push a fix commit."""

    def __init__(self, command: str = "codex", timeout_seconds: int = 300) -> None:
        self.command, self.timeout_seconds = command, timeout_seconds

    async def __call__(self, pr: PRResult, logs: str, workdir: Path) -> str | None:
        if not pr.branch:
            return None
        temporary = Path(tempfile.mkdtemp(prefix="repo-surgeon-ci-"))
        try:
            await self._git(workdir, "fetch", "origin", pr.branch)
            await self._git(workdir, "worktree", "add", "--detach", str(temporary), f"origin/{pr.branch}")
            await self._git(temporary, "switch", "-C", pr.branch, f"origin/{pr.branch}")
            prompt = (
                "Fix this GitHub CI failure in the current repository. Make only the smallest correct edit, "
                "run the relevant tests if available, and leave the fix uncommitted. CI logs:\n" + logs
            )
            executable = shutil.which(self.command)
            if not executable:
                raise RuntimeError(f"Could not find {self.command!r} on PATH")
            await asyncio.to_thread(subprocess.run, [executable, "exec", "--sandbox", "workspace-write", prompt],
                                    cwd=temporary, text=True, capture_output=True, check=True, timeout=self.timeout_seconds)
            diff = await self._git(temporary, "diff", "--quiet", check=False)
            if diff.returncode == 0:
                return None
            await self._git(temporary, "add", "-A")
            await self._git(temporary, "commit", "-m", "fix: address CI failure")
            sha = (await self._git(temporary, "rev-parse", "HEAD")).stdout.strip()
            await self._git(temporary, "push", "origin", f"HEAD:{pr.branch}")
            return sha
        finally:
            await self._git(workdir, "worktree", "remove", "--force", str(temporary), check=False)
            shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    async def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        completed = await asyncio.to_thread(subprocess.run, ["git", *args], cwd=cwd, text=True,
                                            capture_output=True, check=False)
        if check and completed.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
        return completed


def live_ci_watcher(token: str | None) -> GitHubCIWatcher:
    return GitHubCIWatcher(GitHubClient(token), repair=CodexCIFixer())

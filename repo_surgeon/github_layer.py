"""GitHub-backed reviewer that turns verified changes into small pull requests."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .contracts import PRRequest, PRResult, SurgeonResult, UpgradeItem

logger = logging.getLogger(__name__)


class GitHubAPIError(RuntimeError):
    pass


GIT_NETWORK_TIMEOUT_SECONDS = 60


def _run_git(cwd: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Run git with a hard timeout and no interactive credential prompt.

    Without GIT_TERMINAL_PROMPT=0, a stale or invalid GITHUB_TOKEN makes fetch/
    push block forever on stdin instead of failing — the timeout is a backstop
    for any other network stall (DNS, connection drop) that the flag can't catch.
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True,
                              encoding="utf-8", errors="replace",
                              check=False, env=env, timeout=GIT_NETWORK_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(error.cmd, returncode=124, stdout=error.stdout or "",
                                           stderr=(error.stderr or "") + f"\ntimed out after {GIT_NETWORK_TIMEOUT_SECONDS}s")


class GitHubClient:
    def __init__(self, token: str | None, api_url: str = "https://api.github.com") -> None:
        self.token = token
        self.api_url = api_url.rstrip("/")

    async def create_pull_request(self, repository: str, *, title: str, head: str, base: str, body: str) -> dict[str, Any]:
        return await self._request("POST", f"/repos/{repository}/pulls", {"title": title, "head": head, "base": base, "body": body})

    async def check_runs(self, repository: str, sha: str) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/repos/{repository}/commits/{sha}/check-runs")
        return list(data.get("check_runs", []))

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("GitHub actions require GITHUB_TOKEN with repository contents and pull-request access")
        def send() -> dict[str, Any]:
            data = json.dumps(payload).encode() if payload is not None else None
            request = Request(
                f"{self.api_url}{path}", data=data, method=method,
                headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {self.token}",
                         "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"},
            )
            try:
                with urlopen(request, timeout=30) as response:
                    return json.loads(response.read().decode() or "{}")
            except HTTPError as error:
                detail = error.read().decode(errors="replace")
                raise GitHubAPIError(f"GitHub {method} {path} failed ({error.code}): {detail}") from error
        return await asyncio.to_thread(send)


class GitHubReviewer:
    """Create one branch and pull request per green upgrade item."""

    def __init__(self, client: GitHubClient) -> None:
        self.client = client

    async def open_prs(self, request: PRRequest) -> list[PRResult]:
        if not request.workdir or not request.repo_url:
            raise ValueError("GitHubReviewer requires PRRequest.workdir and repo_url")
        workdir = Path(request.workdir)
        repository = github_repository(request.repo_url)
        base = request.base_branch or await self._git_output(workdir, "branch", "--show-current")
        evidence = {result.item_id: result for result in request.evidence}
        results: list[PRResult] = []
        for item in request.items:
            result = evidence.get(item.id)
            if result is None or not result.patch.strip():
                logger.info("skipping PR for %s: no green patch to review", item.dependency)
                continue
            branch = self._branch_name(request.branch, item)
            sha = await self._commit_patch(workdir, base, branch, result.patch, self._commit_message(item))
            pull = await self.client.create_pull_request(
                repository, title=f"{item.category.value}: upgrade {item.dependency} to {item.to_version}",
                head=branch, base=base, body=self.pr_body(item, result),
            )
            logger.info("opened PR for %s: %s", item.dependency, pull["html_url"])
            results.append(PRResult(url=pull["html_url"], number=pull.get("number"), branch=branch, head_sha=sha,
                                    item_ids=[item.id], ci_status="pending", repository=repository))
        return results

    @staticmethod
    def pr_body(item: UpgradeItem, result: SurgeonResult) -> str:
        confidence = "A" if result.iterations == 1 and item.risk <= 0.35 else "B" if item.risk <= 0.65 else "C"
        source = f"\n\nEvidence: {item.breaking_change_ref}" if item.breaking_change_ref else ""
        files = ", ".join(result.files_changed) or "dependency manifest"
        verification = result.verification
        quality = "not available"
        if verification and verification.test_quality_score is not None:
            quality = f"{verification.test_quality_score:.0f}/100"
        mutation = "not run"
        if verification and verification.mutation_report and verification.mutation_report.score is not None:
            mutation = f"{verification.mutation_report.score:.0f}%"
        tests = "not recorded"
        if verification:
            tests = f"{verification.tests_passed} passed, {verification.tests_failed} failed"
        return (
            f"## Repo Surgeon: {item.dependency}\n\n"
            f"- **Change:** {item.from_version} → {item.to_version}\n"
            f"- **Why:** {item.rationale}\n"
            f"- **Risk:** {item.category.value} ({item.risk:.0%})\n"
            f"- **Verification:** green after {result.iterations} Surgeon iteration(s); {tests}; changed {files}.\n"
            f"- **Test quality / mutation score:** {quality} / {mutation}.\n"
            f"- **Confidence:** {confidence}\n"
            f"- **Rollback:** revert this PR; it contains one upgrade item.{source}\n"
        )

    async def _commit_patch(self, workdir: Path, base: str, branch: str, patch: str, message: str) -> str:
        if shutil.which("git") is None:
            raise RuntimeError("GitHubReviewer requires git on PATH")
        temporary = Path(tempfile.mkdtemp(prefix="repo-surgeon-pr-"))
        try:
            await self._git(workdir, "worktree", "add", "--detach", str(temporary), base)
            await self._git(temporary, "switch", "-c", branch)
            patch_file = temporary / ".repo-surgeon.patch"
            patch_file.write_text(patch, encoding="utf-8")
            await self._git(temporary, "apply", "--index", "--whitespace=nowarn", str(patch_file))
            patch_file.unlink()
            await self._git(temporary, "commit", "-m", message)
            sha = await self._git_output(temporary, "rev-parse", "HEAD")
            await self._git(temporary, "push", "--set-upstream", "origin", branch)
            return sha
        finally:
            await self._git(workdir, "worktree", "remove", "--force", str(temporary), check=False)
            shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def _branch_name(prefix: str, item: UpgradeItem) -> str:
        safe = re.sub(r"[^a-z0-9._/-]+", "-", f"{item.category.value}-{item.dependency}-{item.to_version}".lower()).strip("-.")
        return f"{prefix}/{safe}"[:240]

    @staticmethod
    def _commit_message(item: UpgradeItem) -> str:
        return f"chore(deps): upgrade {item.dependency} to {item.to_version}"

    async def _git(self, cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        completed = await asyncio.to_thread(_run_git, cwd, args)
        if check and completed.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
        return completed

    async def _git_output(self, cwd: Path, *args: str) -> str:
        return (await self._git(cwd, *args)).stdout.strip()


def github_repository(url: str) -> str:
    """Convert a GitHub clone URL to the owner/repository API identifier."""
    match = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not match:
        raise ValueError(f"Only GitHub repository URLs are supported, got {url!r}")
    return f"{match.group(1)}/{match.group(2)}"

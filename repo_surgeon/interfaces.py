from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .contracts import (BreakingChanges, ChangeDetail, EditResult, PRRequest, PRResult,
                        RepoProfile, UpgradeItem, VerifyResult)


class SandboxClient(Protocol):
    async def clone(self, repo_url: str) -> Path: ...

    async def cleanup(self, workdir: Path | None = None) -> None: ...


class ScoutService(Protocol):
    async def profile(self, workdir: Path) -> RepoProfile: ...


class ResearcherService(Protocol):
    async def research(self, profile: RepoProfile) -> BreakingChanges: ...


class VerifierService(Protocol):
    async def verify(self, item: UpgradeItem, workdir: Path) -> VerifyResult: ...


class ReviewerService(Protocol):
    async def open_prs(self, request: PRRequest) -> list[PRResult]: ...


class CIWatcherService(Protocol):
    async def watch(self, prs: list[PRResult], workdir: Path) -> list[PRResult]: ...


class CodexRunner(Protocol):
    async def edit(self, workdir: Path, item: UpgradeItem, breaking_change: ChangeDetail | None,
                   failure_context: str | None = None) -> EditResult: ...

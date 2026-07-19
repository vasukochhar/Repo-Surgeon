from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from .contracts import ChangeDetail, EditResult, UpgradeItem

logger = logging.getLogger(__name__)


class RealCodexRunner:
    def __init__(self, timeout_seconds: int = 300, command: str = "codex",
                 sandbox: str = "workspace-write") -> None:
        self.timeout_seconds, self.command, self.sandbox = timeout_seconds, command, sandbox

    async def edit(self, workdir: Path, item: UpgradeItem, breaking_change: ChangeDetail | None,
                   failure_context: str | None = None) -> EditResult:
        context = breaking_change.model_dump_json() if breaking_change else "No migration notes available."
        prompt = (f"Perform this exact change now: upgrade {item.dependency} from {item.from_version} to {item.to_version}.\n"
                  f"Migration context: {context}\nFailure context: {failure_context or 'None'}\n"
                  "Find the dependency manifest, make the required focused edit, and leave it as an uncommitted "
                  "working-tree change. Do not merely explain the change, do not commit it, and do not stop until "
                  "`git diff` would show the edit.")
        agents = workdir / "AGENTS.md"
        created_agents = not agents.exists()
        if created_agents:
            agents.write_text("# Repo Surgeon\nMake focused dependency migration edits. Preserve existing project conventions.\n", encoding="utf-8")
        try:
            before = await self._diff(workdir)
            started = time.monotonic()
            try:
                command = self._command_args(prompt)
                completed = await asyncio.to_thread(subprocess.run, command, cwd=workdir,
                    check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=self.timeout_seconds)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as error:
                logger.warning("codex exec failed for %s after %.1fs: %s", item.id, time.monotonic() - started, error)
                raise RuntimeError(f"codex exec failed for {item.id}: {error}") from error
            logger.info("codex exec for %s finished in %.1fs", item.id, time.monotonic() - started)
            patch = await self._diff(workdir)
            return EditResult(files_changed=self._files_from_diff(patch), patch=patch if patch != before else "",
                              logs=f"{completed.stdout}\n{completed.stderr}".strip())
        finally:
            if created_agents:
                agents.unlink(missing_ok=True)

    def _command_args(self, prompt: str) -> list[str]:
        """Resolve npm's Windows .cmd shim before invoking Codex headlessly."""
        # Prefer npm's shim on Windows: an app-installed codex.exe can be on
        # PATH first but inaccessible to a subprocess launched from Python.
        shim = shutil.which(f"{self.command}.cmd") if os.name == "nt" else None
        if shim:
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", shim,
                    "exec", "--sandbox", self.sandbox, prompt]
        executable = shutil.which(self.command)
        if executable is None:
            raise FileNotFoundError(f"Could not find {self.command!r} on PATH")
        if executable.lower().endswith((".cmd", ".bat")):
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", executable, "exec", prompt]
        return [executable, "exec", "--sandbox", self.sandbox, prompt]

    async def _diff(self, workdir: Path) -> str:
        # Intent-to-add makes untracked files visible in the patch without
        # staging their content, so a reviewer can reproduce a full migration.
        await asyncio.to_thread(subprocess.run, ["git", "add", "-N", "."], cwd=workdir,
                                check=True, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=30)
        result = await asyncio.to_thread(subprocess.run, ["git", "diff", "--binary"], cwd=workdir,
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return result.stdout

    @staticmethod
    def _files_from_diff(patch: str) -> list[str]:
        return [line[6:] for line in patch.splitlines() if line.startswith("+++ b/")]


class MockCodexRunner:
    def __init__(self, fail_edits: int = 0) -> None:
        self.fail_edits = fail_edits
        self.calls = 0

    async def edit(self, workdir: Path, item: UpgradeItem, breaking_change: ChangeDetail | None,
                   failure_context: str | None = None) -> EditResult:
        self.calls += 1
        return EditResult(files_changed=["mock_dependency.txt"],
                          patch=f"mock edit {self.calls} for {item.dependency}",
                          logs="Mock Codex edit completed")

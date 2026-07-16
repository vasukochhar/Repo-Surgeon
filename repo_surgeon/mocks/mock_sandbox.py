from __future__ import annotations

import tempfile
from pathlib import Path


class MockSandbox:
    """Local temporary workdir stand-in for Faiz's isolated sandbox."""
    async def clone(self, repo_url: str) -> Path:
        self.workdir = Path(tempfile.mkdtemp(prefix="repo-surgeon-"))
        return self.workdir

    async def cleanup(self, workdir: Path | None = None) -> None:
        import shutil
        target = workdir or getattr(self, "workdir", None)
        if target:
            shutil.rmtree(target, ignore_errors=True)

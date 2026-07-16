from __future__ import annotations

import tempfile
from pathlib import Path


class MockSandbox:
    """Local temporary workdir stand-in for Faiz's isolated sandbox."""
    async def clone(self, repo_url: str) -> Path:
        return Path(tempfile.mkdtemp(prefix="repo-surgeon-"))

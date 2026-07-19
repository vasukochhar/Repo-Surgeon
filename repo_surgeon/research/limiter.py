from __future__ import annotations

import asyncio
import threading
from typing import Protocol


class ResearchLimiter(Protocol):
    async def __aenter__(self): ...
    async def __aexit__(self, exc_type, exc, traceback): ...


class AsyncResearchLimiter:
    """Replaceable single-process limiter for all OpenAI research batches."""

    def __init__(self, maximum: int = 1) -> None:
        self.maximum = max(1, maximum)
        self._semaphore = asyncio.Semaphore(self.maximum)

    async def __aenter__(self):
        await self._semaphore.acquire()
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self._semaphore.release()


_shared_lock = threading.Lock()
_shared_limiter: AsyncResearchLimiter | None = None


def shared_research_limiter(maximum: int = 1) -> AsyncResearchLimiter:
    global _shared_limiter
    with _shared_lock:
        if _shared_limiter is None:
            _shared_limiter = AsyncResearchLimiter(maximum)
        return _shared_limiter

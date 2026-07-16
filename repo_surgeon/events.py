from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator

from .contracts import Event


class EventBus:
    def __init__(self) -> None:
        self._history: dict[str, list[Event]] = defaultdict(list)
        self._subscribers: dict[str, list[asyncio.Queue[Event]]] = defaultdict(list)

    async def publish(self, event: Event) -> None:
        self._history[event.job_id].append(event)
        for queue in list(self._subscribers[event.job_id]):
            await queue.put(event)

    def history(self, job_id: str) -> list[Event]:
        return list(self._history[job_id])

    async def subscribe(self, job_id: str) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers[job_id].append(queue)
        try:
            for event in self.history(job_id):
                yield event
            while True:
                yield await queue.get()
        finally:
            self._subscribers[job_id].remove(queue)

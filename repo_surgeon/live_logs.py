"""In-memory log tail, exposed via /debug/logs/stream for the dashboard's
live console panel.

A ring buffer, not a pub/sub queue: subprocess output is logged from a worker
thread (AsyncCommandRunner runs via asyncio.to_thread), so anything requiring
event-loop affinity would need cross-thread handoff. SSE clients instead
long-poll by sequence number, which only needs deque.append() — atomic under
the GIL — from any thread.
"""
from __future__ import annotations

import logging
from collections import deque
from itertools import count

_HISTORY_LIMIT = 5000
_seq = count(1)
_history: deque[dict] = deque(maxlen=_HISTORY_LIMIT)


class RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()
        _history.append({
            "seq": next(_seq),
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        })


def install(level: int = logging.INFO) -> None:
    handler = RingBufferHandler()
    handler.setLevel(level)
    logging.getLogger("repo_surgeon").addHandler(handler)


def since(seq: int) -> list[dict]:
    return [entry for entry in _history if entry["seq"] > seq]

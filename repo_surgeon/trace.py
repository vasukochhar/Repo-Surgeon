"""Per-job data tracing for end-to-end testing.

Every pipeline stage dumps its exact inputs and outputs to
``test_results/<job_id>/NN_<stage>_<direction>.json`` so a human can read the
data flow without re-running anything. Tracing is best-effort by construction:
a failure to write a trace file must never fail the job it is tracing.

Enable with ``REPO_SURGEON_TRACE=1`` (default on) and point it somewhere else
with ``REPO_SURGEON_TRACE_DIR``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TRACE_DIR = "test_results"
# Command stdout/stderr can be megabytes. Trace files are meant to be read by a
# person, so keep each string field skimmable while preserving both ends —
# failures show up at the tail, invocation details at the head.
MAX_STRING_CHARS = 20_000


def _enabled() -> bool:
    return os.getenv("REPO_SURGEON_TRACE", "1").lower() not in {"0", "false", "no", "off"}


def _encode(value: Any) -> Any:
    """Make any pipeline object JSON-safe without losing its shape."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= MAX_STRING_CHARS else (
            value[: MAX_STRING_CHARS // 2]
            + f"\n... [trace truncated {len(value) - MAX_STRING_CHARS} chars] ...\n"
            + value[-MAX_STRING_CHARS // 2 :]
        )
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_encode(item) for item in value]
    dump = getattr(value, "model_dump", None)          # pydantic v2
    if callable(dump):
        try:
            return _encode(dump(mode="json"))
        except Exception:
            pass
    if hasattr(value, "__dict__"):                      # dataclasses, plain objects
        return _encode(vars(value))
    return repr(value)


class JobTracer:
    """Writes ordered JSON snapshots for one job."""

    def __init__(self, job_id: str, root: Path | None = None) -> None:
        self.job_id = job_id
        self.enabled = _enabled()
        base = root or Path(os.getenv("REPO_SURGEON_TRACE_DIR", DEFAULT_TRACE_DIR))
        self.dir = base / job_id
        self._step = 0
        self._lock = threading.Lock()
        if self.enabled:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                logger.info("[%s] tracing data flow to %s", job_id, self.dir.resolve())
            except OSError as error:
                self.enabled = False
                logger.warning("[%s] tracing disabled, could not create %s: %s", job_id, self.dir, error)

    def write(self, stage: str, direction: str, data: Any, **metadata: Any) -> Path | None:
        """Dump one snapshot. `direction` is input/output/llm_call/error."""
        if not self.enabled:
            return None
        with self._lock:
            self._step += 1
            step = self._step
        name = f"{step:02d}_{stage}_{direction}.json"
        payload = {
            "job_id": self.job_id,
            "step": step,
            "stage": stage,
            "direction": direction,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            **{key: _encode(value) for key, value in metadata.items()},
            "data": _encode(data),
        }
        path = self.dir / name
        try:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("[%s] traced %s -> %s", self.job_id, f"{stage}/{direction}", name)
        except (OSError, TypeError, ValueError) as error:
            logger.warning("[%s] could not write trace %s: %s", self.job_id, name, error)
            return None
        return path

    def llm_call(self, stage: str, *, model: str, prompt: str, response: str,
                 duration_seconds: float, usage: Any = None, request: Any = None,
                 truncated: bool | None = None, search_queries: list[str] | None = None) -> None:
        """Record a model call verbatim: prompt in, raw text out, token usage."""
        self.write(stage, "llm_call", {
            "model": model,
            "request_params": request,
            "prompt": prompt,
            "prompt_chars": len(prompt),
            "response_text": response,
            "response_chars": len(response),
            "response_truncated": truncated,
            "search_queries": search_queries,
            "usage": usage,
            "duration_seconds": round(duration_seconds, 3),
        })


class NullTracer:
    """No-op stand-in so call sites never need a None check."""

    job_id = ""
    enabled = False
    dir = Path(".")

    def write(self, *args: Any, **kwargs: Any) -> None:
        return None

    def llm_call(self, *args: Any, **kwargs: Any) -> None:
        return None


# Ambient tracer so leaf services (researcher, planner) can record LLM payloads
# without threading a tracer through every constructor. The orchestrator sets it
# for the duration of a job; concurrent jobs each get their own via contextvars.
from contextvars import ContextVar  # noqa: E402

_current: ContextVar[JobTracer | NullTracer] = ContextVar("repo_surgeon_tracer", default=NullTracer())


def current_tracer() -> JobTracer | NullTracer:
    return _current.get()


def set_tracer(tracer: JobTracer | NullTracer):
    return _current.set(tracer)


def reset_tracer(token) -> None:
    _current.reset(token)

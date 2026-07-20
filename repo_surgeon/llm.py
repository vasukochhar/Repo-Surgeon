"""Shared OpenAI access: rate-limit pacing, observable retries, token accounting.

Both the Researcher and the Planner call the Responses API. Left to themselves
they open separate clients with the SDK's opaque built-in retries, so a 429
looks like an unexplained 30-second stall. This module gives the pipeline one
throttled client whose every call, retry and backoff is logged and traced.

We don't know this account's actual TPM/RPM tier, so the two knobs below
trade risk for speed rather than eliminate it: CONCURRENCY caps how many
calls are in flight at once, MIN_INTERVAL staggers when each one *starts*
(so even at CONCURRENCY=3 they don't fire simultaneously). If the real
limit turns out to be lower than these imply, a 429 is not a failure — the
backoff below retries automatically and every attempt is logged, so a job
just runs slower, visibly, instead of erroring out.

Tunables (all optional):
  REPO_SURGEON_LLM_CONCURRENCY   max simultaneous model calls   (default 3)
  REPO_SURGEON_LLM_MIN_INTERVAL  seconds enforced between calls (default 3.0)
  REPO_SURGEON_LLM_MAX_RETRIES   429/5xx retry attempts         (default 5)
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from typing import Any

from .trace import current_tracer

logger = logging.getLogger(__name__)

_client = None
_client_lock = asyncio.Lock()
_gate: asyncio.Semaphore | None = None
_last_call_at = 0.0
_pace_lock = asyncio.Lock()
# Params a given model may reject (e.g. reasoning controls on a non-reasoning
# model). Recorded on first rejection so we stop re-sending them.
_unsupported: dict[str, set[str]] = {}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


async def _get_client():
    global _client, _gate
    async with _client_lock:
        if _client is None:
            from openai import AsyncOpenAI
            # max_retries=0: this module owns retries so every backoff is visible
            # in the log instead of hiding inside the SDK as dead air.
            _client = AsyncOpenAI(max_retries=0)
            _gate = asyncio.Semaphore(_int_env("REPO_SURGEON_LLM_CONCURRENCY", 3))
            logger.info("openai client ready (concurrency=%d, min_interval=%.1fs, max_retries=%d)",
                        _int_env("REPO_SURGEON_LLM_CONCURRENCY", 3),
                        _float_env("REPO_SURGEON_LLM_MIN_INTERVAL", 3.0),
                        _int_env("REPO_SURGEON_LLM_MAX_RETRIES", 5))
    return _client


async def _pace() -> None:
    """Space calls apart so a burst never trips the per-minute request limit."""
    global _last_call_at
    minimum = _float_env("REPO_SURGEON_LLM_MIN_INTERVAL", 3.0)
    async with _pace_lock:
        wait = minimum - (time.monotonic() - _last_call_at)
        if wait > 0:
            logger.info("pacing: waiting %.1fs before next model call", wait)
            await asyncio.sleep(wait)
        _last_call_at = time.monotonic()


def _retry_after(error: Exception) -> float | None:
    headers = getattr(getattr(error, "response", None), "headers", None)
    if not headers:
        return None
    for key in ("retry-after-ms", "retry-after"):
        raw = headers.get(key)
        if raw:
            try:
                return float(raw) / (1000.0 if key.endswith("-ms") else 1.0)
            except ValueError:
                continue
    return None


def _usage(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    dump = getattr(usage, "model_dump", None)
    return dump() if callable(dump) else {"raw": repr(usage)}


def _is_truncated(response: Any) -> bool:
    """True when the model stopped because it hit max_output_tokens."""
    if getattr(response, "status", None) == "incomplete":
        return True
    details = getattr(response, "incomplete_details", None)
    return getattr(details, "reason", None) == "max_output_tokens"


def _search_queries(response: Any) -> list[str]:
    """Web search results are never returned by the API — only the queries are
    visible. This is the one window we get into what a call actually cost."""
    queries: list[str] = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) == "web_search_call":
            action = getattr(item, "action", None)
            queries.extend(getattr(action, "queries", None) or
                           ([getattr(action, "query", None)] if getattr(action, "query", None) else []))
    return queries


async def respond(*, model: str, prompt: str, stage: str, tools: list[dict] | None = None,
                  max_output_tokens: int | None = None, reasoning: dict | None = None,
                  timeout: float | None = None) -> str:
    """One paced, retried, fully-traced Responses API call. Returns output text."""
    from openai import APIStatusError, BadRequestError, RateLimitError

    client = await _get_client()
    blocked = _unsupported.setdefault(model, set())
    max_retries = _int_env("REPO_SURGEON_LLM_MAX_RETRIES", 5)
    attempt = 0

    while True:
        attempt += 1
        params: dict[str, Any] = {"model": model, "input": prompt}
        if tools:
            params["tools"] = tools
        if max_output_tokens and "max_output_tokens" not in blocked:
            params["max_output_tokens"] = max_output_tokens
        if reasoning and "reasoning" not in blocked:
            params["reasoning"] = reasoning
        if timeout:
            params["timeout"] = timeout

        await _pace()
        logged = {key: value for key, value in params.items() if key != "input"}
        logger.info("[%s] model call attempt %d/%d: %s (prompt %d chars)",
                    stage, attempt, max_retries, logged, len(prompt))
        started = time.monotonic()
        assert _gate is not None
        try:
            async with _gate:
                response = await client.responses.create(**params)
        except BadRequestError as error:
            message = str(error)
            dropped = next((name for name in ("max_output_tokens", "reasoning")
                            if name in params and name in message), None)
            if dropped:
                # The model rejected an optional tuning param — remember and retry
                # without it rather than failing the whole stage over it.
                blocked.add(dropped)
                logger.warning("[%s] model %s rejected %r; retrying without it", stage, model, dropped)
                attempt -= 1
                continue
            logger.error("[%s] model call rejected: %s", stage, message)
            raise
        except (RateLimitError, APIStatusError) as error:
            status = getattr(error, "status_code", None)
            retryable = isinstance(error, RateLimitError) or (status is not None and status >= 500)
            if not retryable or attempt >= max_retries:
                logger.error("[%s] model call failed (status=%s, attempt %d): %s",
                             stage, status, attempt, error)
                current_tracer().write(stage, "error", {
                    "model": model, "attempt": attempt, "status": status, "error": str(error)})
                raise
            delay = _retry_after(error) or min(60.0, 2.0 ** attempt) + random.uniform(0, 1.5)
            logger.warning("[%s] rate limited (status=%s) on attempt %d; backing off %.1fs",
                           stage, status, attempt, delay)
            await asyncio.sleep(delay)
            continue

        elapsed = time.monotonic() - started
        text = response.output_text or ""
        truncated = _is_truncated(response)
        usage = _usage(response)
        queries = _search_queries(response)
        logger.info("[%s] model call ok in %.1fs: %d chars out, usage=%s%s",
                    stage, elapsed, len(text), usage, " TRUNCATED" if truncated else "")
        if queries:
            # The fetched page content that drives the input-token cost is never
            # returned by the API — the query text is the only visibility we get.
            logger.info("[%s] web search queries (%d): %s", stage, len(queries), queries)
        if truncated:
            # Surfaced loudly: a truncated response parses as invalid JSON later,
            # which otherwise reads as "the model returned garbage".
            logger.warning("[%s] response hit max_output_tokens (%s) and was cut off — "
                           "raise it if downstream JSON parsing fails", stage, max_output_tokens)
        current_tracer().llm_call(stage, model=model, prompt=prompt, response=text,
                                  duration_seconds=elapsed, usage=usage,
                                  request=logged, truncated=truncated, search_queries=queries or None)
        return text

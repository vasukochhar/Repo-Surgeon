from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Mapping


@dataclass(frozen=True)
class RateLimitDecision:
    category: str
    retryable: bool
    status: int | None = None
    request_id: str | None = None
    reset_seconds: float | None = None
    safe_message: str = "OpenAI research was rate limited."


class ResearchRateLimited(RuntimeError):
    def __init__(self, decision: RateLimitDecision, attempts: int, total_wait: float) -> None:
        super().__init__(decision.safe_message)
        self.decision, self.attempts, self.total_wait = decision, attempts, total_wait


def classify_rate_limit(error: Exception) -> RateLimitDecision:
    response = getattr(error, "response", None)
    headers = _headers(getattr(response, "headers", None))
    status = getattr(error, "status_code", None) or getattr(response, "status_code", None)
    request_id = getattr(error, "request_id", None) or headers.get("x-request-id")
    code, error_type, message = _error_fields(getattr(error, "body", None))
    text = " ".join((code, error_type, message)).lower()

    if "insufficient_quota" in text or any(term in text for term in
            ("billing quota", "credit balance", "credits exhausted", "billing limit")):
        return RateLimitDecision("insufficient_quota", False, status, request_id, None,
            "OpenAI quota or billing credit is unavailable; check account/project billing and usage tier.")
    if any(term in text for term in ("daily limit", "monthly limit", "project usage limit",
                                      "usage limit exceeded", "spend limit", "hard limit")):
        return RateLimitDecision("usage_limit", False, status, request_id, None,
            "OpenAI project or account usage limit was reached; check project limits and billing.")
    if any(term in text for term in ("unsupported model", "model_not_found", "invalid organization",
                                      "invalid project", "organization configuration")):
        return RateLimitDecision("configuration_or_model", False, status, request_id, None,
            "OpenAI model, project, or organization configuration must be checked.")

    request_reset = _first_reset(headers, ("x-ratelimit-reset-requests",))
    token_reset = _first_reset(headers, ("x-ratelimit-reset-tokens",
                                          "x-ratelimit-reset-project-tokens"))
    retry_after = _first_reset(headers, ("retry-after",))
    request_signal = (headers.get("x-ratelimit-remaining-requests") == "0" or
                      request_reset is not None or any(term in text for term in
                      ("requests per minute", "request rate", "rpm")))
    token_signal = (headers.get("x-ratelimit-remaining-tokens") == "0" or
                    token_reset is not None or any(term in text for term in
                    ("tokens per minute", "token rate", "tpm")))
    if token_signal:
        reset = max(value for value in (token_reset, retry_after) if value is not None) \
            if token_reset is not None or retry_after is not None else None
        oversized = any(term in text for term in ("request too large", "requested tokens exceed",
                                                   "maximum tokens per request"))
        return RateLimitDecision("tokens_per_minute", not oversized, status, request_id, reset,
            "OpenAI token-rate capacity is temporarily unavailable." if not oversized else
            "The OpenAI request exceeds the available token-rate capacity; reduce context or check the usage tier.")
    if request_signal:
        reset = max(value for value in (request_reset, retry_after) if value is not None) \
            if request_reset is not None or retry_after is not None else None
        return RateLimitDecision("requests_per_minute", True, status, request_id, reset,
            "OpenAI request-rate capacity is temporarily unavailable.")
    return RateLimitDecision("unknown_rate_limit", False, status, request_id, retry_after,
        "OpenAI returned an unclassified rate limit; research was deferred without retrying.")


def _headers(value) -> dict[str, str]:
    if value is None:
        return {}
    try:
        items = value.items()
    except AttributeError:
        return {}
    return {str(key).lower(): str(item).strip() for key, item in items}


def _error_fields(body) -> tuple[str, str, str]:
    if not isinstance(body, Mapping):
        return "", "", ""
    value = body.get("error", body)
    if not isinstance(value, Mapping):
        return "", "", ""
    return tuple(str(value.get(name) or "") for name in ("code", "type", "message"))


def parse_reset_seconds(value: str | None) -> float | None:
    if not value:
        return None
    text = value.strip().lower()
    try:
        numeric = float(text)
        return max(0.0, numeric)
    except ValueError:
        pass
    units = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h)", text)
    if matches and "".join(f"{amount}{unit}" for amount, unit in matches).replace(" ", "") == text.replace(" ", ""):
        return sum(float(amount) * units[unit] for amount, unit in matches)
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _first_reset(headers: Mapping[str, str], names: tuple[str, ...]) -> float | None:
    values = [parse_reset_seconds(headers.get(name)) for name in names]
    valid = [value for value in values if value is not None]
    return max(valid) if valid else None

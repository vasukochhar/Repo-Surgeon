from __future__ import annotations

import os


LUNA_MODEL = "gpt-5.6-luna"


def luna_only_model(explicit: str | None = None, *, environment: str | None = None) -> str:
    """Resolve an OpenAI model while enforcing Repo Surgeon's Luna-only policy."""
    configured = explicit or (os.getenv(environment) if environment else None) or LUNA_MODEL
    if configured != LUNA_MODEL:
        source = environment if explicit is None and environment else "explicit model argument"
        raise ValueError(f"{source} must be {LUNA_MODEL!r}; received a disallowed model")
    return LUNA_MODEL

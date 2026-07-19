from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from ..model_policy import LUNA_MODEL, luna_only_model


@dataclass(frozen=True)
class ResearchConfig:
    batch_size: int = 1
    max_concurrent_research: int = 1
    max_attempts: int = 5
    retry_min_seconds: float = 5
    retry_max_seconds: float = 90
    retry_multiplier: float = 2
    retry_jitter: float = 0.25
    planner_target_tokens: int = 8_000
    planner_max_tokens: int = 20_000
    card_target_tokens: int = 600
    surgeon_max_tokens: int = 1_500
    timeout_seconds: float = 240
    cache_location: Path = Path(".repo-surgeon-cache/research.json")
    security_cache_ttl_seconds: int = 86_400
    normal_cache_ttl_seconds: int = 2_592_000
    max_source_chars: int = 8_000
    max_sources: int = 5
    summarization_enabled: bool = False
    summarizer_model: str = LUNA_MODEL

    @classmethod
    def from_env(cls) -> "ResearchConfig":
        def integer(name, default):
            try:
                return int(os.getenv(name, str(default)))
            except ValueError:
                return default
        def decimal(name, default):
            try:
                return float(os.getenv(name, str(default)))
            except ValueError:
                return default
        batch = min(5, max(1, integer("REPO_SURGEON_RESEARCH_BATCH_SIZE", 1)))
        retry_min = max(0, decimal("REPO_SURGEON_RESEARCH_RETRY_MIN_SECONDS", 5))
        retry_max = max(retry_min, decimal("REPO_SURGEON_RESEARCH_RETRY_MAX_SECONDS", 90))
        planner_max = max(1, integer("REPO_SURGEON_PLANNER_RESEARCH_MAX_TOKENS", 20000))
        planner_target = min(planner_max,
            max(1, integer("REPO_SURGEON_PLANNER_RESEARCH_TARGET_TOKENS", 8000)))
        summarizer_model = luna_only_model(
            os.getenv("REPO_SURGEON_SUMMARIZER_MODEL") or None,
            environment="REPO_SURGEON_SUMMARIZER_MODEL")
        return cls(batch_size=batch,
            max_concurrent_research=max(1, integer("REPO_SURGEON_MAX_CONCURRENT_RESEARCH", 1)),
            max_attempts=min(10, max(1, integer("REPO_SURGEON_RESEARCH_MAX_ATTEMPTS", 5))),
            retry_min_seconds=retry_min, retry_max_seconds=retry_max,
            retry_multiplier=2,
            retry_jitter=min(1, max(0, decimal("REPO_SURGEON_RESEARCH_RETRY_JITTER", 0.25))),
            planner_target_tokens=planner_target, planner_max_tokens=planner_max,
            card_target_tokens=max(1, integer("REPO_SURGEON_RESEARCH_CARD_TOKENS", 600)),
            surgeon_max_tokens=max(1, integer("REPO_SURGEON_SURGEON_CONTEXT_TOKENS", 1500)),
            timeout_seconds=max(0.01, decimal("REPO_SURGEON_RESEARCH_TIMEOUT", 240)),
            cache_location=Path(os.getenv("REPO_SURGEON_RESEARCH_CACHE") or ".repo-surgeon-cache/research.json"),
            security_cache_ttl_seconds=max(0, integer("REPO_SURGEON_SECURITY_CACHE_TTL", 86400)),
            normal_cache_ttl_seconds=max(0, integer("REPO_SURGEON_RESEARCH_CACHE_TTL", 2592000)),
            max_source_chars=max(1, integer("REPO_SURGEON_RESEARCH_SOURCE_CHARS", 8000)),
            max_sources=min(5, max(1, integer("REPO_SURGEON_RESEARCH_MAX_SOURCES", 5))),
            summarization_enabled=os.getenv("REPO_SURGEON_ENABLE_SUMMARIZATION", "false").lower() == "true",
            summarizer_model=summarizer_model)

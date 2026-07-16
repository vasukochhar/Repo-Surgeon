from __future__ import annotations


def quality_score(mutation: float | None, changed_coverage: float | None,
                  stability: float | None) -> float | None:
    parts = [(mutation, .7), (changed_coverage, .2), (stability, .1)]
    if any(value is not None and not 0 <= value <= 100 for value, _ in parts):
        raise ValueError("quality score inputs must be between 0 and 100")
    available = [(value, weight) for value, weight in parts if value is not None]
    if not available: return None
    total = sum(weight for _, weight in available)
    return round(sum(value * weight for value, weight in available) / total, 1)


def grade(score: float | None) -> str | None:
    if score is None: return None
    return "excellent" if score >= 90 else "strong" if score >= 75 else "moderate" if score >= 60 else "weak" if score >= 40 else "poor"

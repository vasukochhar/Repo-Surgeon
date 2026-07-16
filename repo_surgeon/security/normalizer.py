from __future__ import annotations
from ..contracts import SecurityReport, Vulnerability


def severity(value: str | None) -> str:
    value = (value or "unknown").lower()
    return value if value in {"critical", "high", "medium", "low"} else "unknown"


def deduplicate(items: list[Vulnerability]) -> list[Vulnerability]:
    merged: dict[tuple[str, str, str], Vulnerability] = {}
    for item in items:
        key = ((item.ecosystem or "").lower(), item.dependency.lower(), item.identifier or "unknown")
        if key in merged:
            old = merged[key]
            old.sources = list(dict.fromkeys(old.sources + item.sources))
            old.fixed_versions = list(dict.fromkeys(old.fixed_versions + item.fixed_versions))
            old.aliases = list(dict.fromkeys(old.aliases + item.aliases))
            old.fix_available = old.fix_available or item.fix_available
        else: merged[key] = item.model_copy(deep=True)
    return list(merged.values())


def summarize(items: list[Vulnerability], scanners=None) -> SecurityReport:
    findings = deduplicate(items); counts = {x: 0 for x in ("critical", "high", "medium", "low", "unknown")}
    for item in findings: item.severity = severity(item.severity); counts[item.severity] += 1
    return SecurityReport(findings=findings, total=len(findings), counts_by_severity=counts,
        fix_available_count=sum(x.fix_available for x in findings), scanners=scanners or [])

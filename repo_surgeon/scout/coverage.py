from __future__ import annotations
import json
from pathlib import Path
from ..contracts import CoverageResult, ExecutionStatus


def parse_coverage(root: Path) -> CoverageResult:
    py = root / "coverage.json"
    node = root / "coverage" / "coverage-summary.json"
    try:
        if py.exists():
            data = json.loads(py.read_text(encoding="utf-8")); total = data.get("totals", {})
            files = {name: value.get("summary", {}).get("percent_covered", 0.0) for name, value in data.get("files", {}).items()}
            return CoverageResult(line_percent=total.get("percent_covered"), branch_percent=_branch(total), files=files, status=ExecutionStatus.PASSED)
        if node.exists():
            data = json.loads(node.read_text(encoding="utf-8")); total = data.get("total", {})
            files = {name: value.get("lines", {}).get("pct", 0.0) for name, value in data.items() if name != "total"}
            return CoverageResult(line_percent=total.get("lines", {}).get("pct"), branch_percent=total.get("branches", {}).get("pct"), files=files, status=ExecutionStatus.PASSED)
    except (OSError, json.JSONDecodeError, TypeError):
        return CoverageResult(status=ExecutionStatus.FAILED)
    return CoverageResult()


def _branch(total: dict) -> float | None:
    covered, count = total.get("covered_branches"), total.get("num_branches")
    return round(covered / count * 100, 2) if covered is not None and count else None

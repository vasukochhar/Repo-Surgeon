from __future__ import annotations
import json
from pathlib import Path
from ..contracts import ExecutionStatus, MutationReport
from ..sandbox.command_runner import AsyncCommandRunner


def parse_stryker(text: str, files=None) -> MutationReport:
    try: data = json.loads(text)
    except json.JSONDecodeError: return MutationReport(tool="stryker", targeted_files=files or [], status=ExecutionStatus.FAILED)
    mutants = data.get("files", {}); statuses = []
    for file in mutants.values(): statuses += [m.get("status", "") for m in file.get("mutants", [])]
    counts = {name: sum(x.lower() == name for x in statuses) for name in ("killed", "survived", "timeout", "suspicious", "notcovered")}
    valid = counts["killed"] + counts["survived"] + counts["timeout"] + counts["suspicious"]
    return MutationReport(tool="stryker", killed=counts["killed"], survived=counts["survived"], timeout=counts["timeout"],
        suspicious=counts["suspicious"], untested=counts["notcovered"], total=len(statuses),
        score=round(counts["killed"] / valid * 100, 1) if valid else None, targeted_files=files or [],
        status=ExecutionStatus.PASSED if valid else ExecutionStatus.NOT_APPLICABLE)


class StrykerRunner:
    def __init__(self, runner: AsyncCommandRunner, timeout: float = 180) -> None: self.runner, self.timeout = runner, timeout
    async def run(self, root: Path, files: list[str]) -> MutationReport:
        report_path = root / ".repo-surgeon-stryker.json"
        config_path = root / ".repo-surgeon-stryker.conf.json"
        config_path.write_text(json.dumps({"mutate": files, "reporters": ["json"],
            "jsonReporter": {"fileName": report_path.name}, "concurrency": 1,
            "testRunner": "vitest"}), encoding="utf-8")
        command = ["stryker", "run", config_path.name]
        try:
            result = await self.runner.run(command, cwd=root, timeout=self.timeout)
            payload = report_path.read_text(encoding="utf-8") if report_path.exists() else result.stdout
            report = parse_stryker(payload, files); report.command_result = result
            if result.tool_unavailable: report.status = ExecutionStatus.UNAVAILABLE
            elif result.timed_out: report.status = ExecutionStatus.TIMEOUT
            return report
        finally:
            report_path.unlink(missing_ok=True)
            config_path.unlink(missing_ok=True)

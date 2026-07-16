from __future__ import annotations
from pathlib import Path
from ..contracts import ExecutionStatus, ScannerExecution, SecurityReport, StackInfo
from ..sandbox.command_runner import AsyncCommandRunner
from .normalizer import summarize
from .npm_audit import parse_npm_audit
from .osv import parse_osv
from .pip_audit import parse_pip_audit


class SecurityService:
    def __init__(self, runner: AsyncCommandRunner) -> None: self.runner = runner
    async def scan(self, root: Path, stack: StackInfo) -> SecurityReport:
        specs = [("osv", ["osv-scanner", "scan", "source", "--format", "json", "."], parse_osv)]
        if stack.language == "Python": specs.append(("pip-audit", ["python", "-m", "pip_audit", "--format", "json"], parse_pip_audit))
        elif stack.language in {"JavaScript", "TypeScript"}: specs.append(("npm-audit", ["npm", "audit", "--json"], parse_npm_audit))
        findings = []; executions = []
        for name, command, parser in specs:
            result = await self.runner.run(command, cwd=root)
            parsed = parser(result.stdout)
            missing_module = "No module named" in result.stderr
            status = (ExecutionStatus.UNAVAILABLE if result.tool_unavailable or missing_module else
                      ExecutionStatus.TIMEOUT if result.timed_out else
                      ExecutionStatus.PASSED if parsed or result.exit_code == 0 else ExecutionStatus.FAILED)
            findings.extend(parsed); executions.append(ScannerExecution(scanner=name, status=status, result=result, findings_count=len(parsed)))
        return summarize(findings, executions)

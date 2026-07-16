from __future__ import annotations
import re
from pathlib import Path
from ..contracts import Baseline, DetectedCommands, ExecutionStatus
from ..sandbox.command_runner import AsyncCommandRunner


def parse_test_output(text: str) -> tuple[int, int, int, list[str]]:
    def count(name: str) -> int:
        matches = re.findall(rf"(\d+)\s+{name}", text, re.I)
        return int(matches[-1]) if matches else 0
    failing = list(dict.fromkeys(re.findall(r"(?:FAILED|FAIL)\s+([^\s]+)", text)))
    return count("passed"), count("failed") or len(failing), count("skipped"), failing


class BaselineRunner:
    def __init__(self, runner: AsyncCommandRunner) -> None: self.runner = runner
    async def run(self, root: Path, commands: DetectedCommands) -> Baseline:
        install = await self.runner.run(commands.install, cwd=root) if commands.install else None
        if install and install.status is not ExecutionStatus.PASSED:
            return Baseline(build_ok=False, install_command=commands.install, install_result=install,
                test_command=commands.test, build_command=commands.build, coverage_command=commands.coverage)
        test = await self.runner.run(commands.test, cwd=root) if commands.test else None
        passed, failed, skipped, failing = parse_test_output((test.stdout + "\n" + test.stderr) if test else "")
        build = await self.runner.run(commands.build, cwd=root) if commands.build else None
        return Baseline(tests_passed=passed, tests_failed=failed, tests_skipped=skipped,
            build_ok=build.exit_code == 0 if build else True, test_command=commands.test,
            build_command=commands.build, install_command=commands.install, coverage_command=commands.coverage,
            test_duration_seconds=test.duration_seconds if test else 0, build_duration_seconds=build.duration_seconds if build else 0,
            failing_tests=failing, failure_fingerprints=failing, test_result=test, build_result=build, install_result=install)

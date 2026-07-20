from __future__ import annotations
import re
from pathlib import Path
from ..contracts import Baseline, DetectedCommands, ExecutionStatus
from ..sandbox.command_runner import AsyncCommandRunner


def parse_test_output(text: str) -> tuple[int, int, int, list[str]]:
    def count(name: str) -> int:
        matches = re.findall(rf"(\d+)\s+{name}", text, re.I)
        return int(matches[-1]) if matches else 0
    # Pytest's short summary reports collection/import errors as line-start
    # "ERROR tests/test_app.py" — no FAILED prefix, so without capturing these
    # a module that can't even import is reported as zero failures. Anchored
    # to line start so it skips "___ ERROR collecting ... ___" headers and
    # "ERROR: ..." tool messages (pip, pytest usage errors), which say nothing
    # about which test failed.
    named = re.findall(r"(?:FAILED|FAIL)\s+([^\s]+)", text) + re.findall(r"^ERROR\s+([^\s:]+)", text, re.M)
    failing = list(dict.fromkeys(named))
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
        if test is not None and test.exit_code not in (0, None) and not passed and not failed:
            # The runner exited non-zero but nothing was collected — a
            # collection/import error (e.g. permission denied reading the test
            # directory), not "zero tests failed". Left unflagged, this reads
            # as a clean 0/0 baseline and the pipeline plans/operates against
            # a test suite that never actually ran.
            return Baseline(build_ok=False, collection_failed=True, test_command=commands.test,
                build_command=commands.build, install_command=commands.install, coverage_command=commands.coverage,
                test_duration_seconds=test.duration_seconds, test_result=test, install_result=install)
        build = await self.runner.run(commands.build, cwd=root) if commands.build else None
        return Baseline(tests_passed=passed, tests_failed=failed, tests_skipped=skipped,
            build_ok=build.exit_code == 0 if build else True, test_command=commands.test,
            build_command=commands.build, install_command=commands.install, coverage_command=commands.coverage,
            test_duration_seconds=test.duration_seconds if test else 0, build_duration_seconds=build.duration_seconds if build else 0,
            failing_tests=failing, failure_fingerprints=failing, test_result=test, build_result=build, install_result=install)

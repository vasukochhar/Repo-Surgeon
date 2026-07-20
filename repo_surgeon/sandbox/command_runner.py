from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Mapping, Sequence

from ..contracts import CommandResult, ExecutionStatus

logger = logging.getLogger(__name__)


class AsyncCommandRunner:
    def __init__(self, default_timeout: float = 300, max_output_chars: int = 5_000_000) -> None:
        self.default_timeout = default_timeout
        self.max_output_chars = max_output_chars

    async def run(self, command: Sequence[str], cwd: Path | None = None,
                  env: Mapping[str, str] | None = None, timeout: float | None = None,
                  strict: bool = False) -> CommandResult:
        if not command or not all(isinstance(part, str) for part in command):
            raise ValueError("command must be a non-empty sequence of strings")
        started = time.monotonic()
        merged = os.environ.copy()
        if env:
            merged.update(env)
        try:
            process = await asyncio.create_subprocess_exec(
                *command, cwd=str(cwd) if cwd else None, env=merged,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            communicate = asyncio.create_task(process.communicate())
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    asyncio.shield(communicate), timeout=timeout or self.default_timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                stdout_b, stderr_b = await communicate
                return self._result(command, cwd, None, stdout_b, stderr_b, started,
                                    ExecutionStatus.TIMEOUT, timed_out=True)
        except asyncio.CancelledError:
            if "process" in locals() and process.returncode is None:
                process.kill()
                await process.wait()
            raise
        except (FileNotFoundError, PermissionError) as error:
            result = self._result(command, cwd, None, b"", str(error).encode(), started,
                                  ExecutionStatus.UNAVAILABLE, unavailable=True)
            if strict:
                raise RuntimeError(result.stderr) from error
            return result
        status = ExecutionStatus.PASSED if process.returncode == 0 else ExecutionStatus.FAILED
        result = self._result(command, cwd, process.returncode, stdout_b, stderr_b, started, status)
        if strict and process.returncode:
            raise RuntimeError(f"command failed ({process.returncode}): {result.stderr}")
        return result

    def _result(self, command: Sequence[str], cwd: Path | None, exit_code: int | None,
                stdout: bytes, stderr: bytes, started: float, status: ExecutionStatus,
                timed_out: bool = False, unavailable: bool = False) -> CommandResult:
        result = CommandResult(command=list(command), cwd=str(cwd) if cwd else None,
            exit_code=exit_code, stdout=self._truncate(stdout.decode(errors="replace")),
            stderr=self._truncate(stderr.decode(errors="replace")),
            duration_seconds=round(time.monotonic() - started, 4), timed_out=timed_out,
            status=status, tool_unavailable=unavailable)
        self._log(result)
        return result

    @staticmethod
    def _log(result: CommandResult) -> None:
        """Every scan, test run and git call in the pipeline lands here.

        Without this the whole subprocess layer is invisible: a missing scanner
        binary or a test command that exits 127 is indistinguishable from one
        that legitimately found nothing.
        """
        rendered = " ".join(result.command)
        if len(rendered) > 300:
            rendered = rendered[:300] + " ..."
        level = logging.INFO if result.status is ExecutionStatus.PASSED else logging.WARNING
        logger.log(level, "cmd %s -> %s (exit=%s, %.1fs) in %s", rendered, result.status.value,
                   result.exit_code, result.duration_seconds, result.cwd or ".")
        if result.status is not ExecutionStatus.PASSED:
            tail = (result.stderr or result.stdout).strip().splitlines()[-15:]
            if tail:
                logger.warning("cmd %s output tail:\n%s", result.command[0], "\n".join(tail))

    def _truncate(self, value: str) -> str:
        if len(value) <= self.max_output_chars:
            return value
        half = max(1, (self.max_output_chars - 42) // 2)
        return value[:half] + "\n... output truncated ...\n" + value[-half:]


def redact_environment(env: Mapping[str, str]) -> dict[str, str]:
    sensitive = ("KEY", "TOKEN", "SECRET", "PASSWORD")
    return {key: "[REDACTED]" if any(part in key.upper() for part in sensitive) else value
            for key, value in env.items()}

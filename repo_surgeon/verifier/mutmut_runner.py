from __future__ import annotations
import re
from pathlib import Path
from ..contracts import ExecutionStatus, MutationReport
from ..sandbox.command_runner import AsyncCommandRunner


def parse_mutmut(text: str, files=None) -> MutationReport:
    def value(name: str) -> int:
        match = re.search(rf"{name}\s*[:=]?\s*(\d+)", text, re.I); return int(match.group(1)) if match else 0
    killed, survived, timeout, suspicious, untested = (value(x) for x in ("killed", "survived", "timeout", "suspicious", "untested"))
    emoji_lines = re.findall(r"🎉\s*(\d+).*?🫥\s*(\d+).*?⏰\s*(\d+).*?🤔\s*(\d+).*?🙁\s*(\d+)", text)
    if emoji_lines:
        killed, survived, timeout, suspicious, untested = map(int, emoji_lines[-1])
    valid = killed + survived + timeout + suspicious
    return MutationReport(tool="mutmut", killed=killed, survived=survived, timeout=timeout, suspicious=suspicious,
        untested=untested, total=valid + untested, score=round(killed / valid * 100, 1) if valid else None,
        targeted_files=files or [], status=ExecutionStatus.PASSED if valid else ExecutionStatus.NOT_APPLICABLE)


class MutmutRunner:
    def __init__(self, runner: AsyncCommandRunner, timeout: float = 180) -> None: self.runner, self.timeout = runner, timeout
    async def run(self, root: Path, files: list[str]) -> MutationReport:
        config = root / "setup.cfg"
        original = config.read_bytes() if config.exists() else None
        if original is not None and b"[mutmut]" in original:
            temporary_config = False
        else:
            temporary_config = True
            source_paths = sorted({Path(name).parent.as_posix() or "." for name in files})
            only_mutate = "\n    ".join(files)
            content = (original.decode("utf-8") + "\n" if original else "") + (
                "[mutmut]\nsource_paths = " + "\n    ".join(source_paths) +
                "\nonly_mutate = " + only_mutate + "\n")
            config.write_text(content, encoding="utf-8")
        try:
            command = ["mutmut", "run", "--max-children", "1"]
            result = await self.runner.run(command, cwd=root, timeout=self.timeout)
            if result.tool_unavailable or result.timed_out:
                return MutationReport(tool="mutmut", targeted_files=files,
                    status=ExecutionStatus.UNAVAILABLE if result.tool_unavailable else ExecutionStatus.TIMEOUT,
                    command_result=result)
            details = await self.runner.run(["mutmut", "results"], cwd=root, timeout=30)
            report = parse_mutmut(result.stdout + result.stderr + details.stdout + details.stderr, files)
            report.command_result = result
            return report
        finally:
            if temporary_config:
                if original is None:
                    config.unlink(missing_ok=True)
                else:
                    config.write_bytes(original)

import logging
import os
from pathlib import Path

import pytest

from repo_surgeon.codex_runner import RealCodexRunner
from repo_surgeon.contracts import UpgradeCategory, UpgradeItem


def test_windows_prefers_npm_cmd_and_uses_cmd_with_fixed_safe_arguments(monkeypatch):
    monkeypatch.setattr("repo_surgeon.codex_runner.os.name", "nt")
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    candidates = {
        "codex.cmd": r"C:\Users\test\AppData\Roaming\npm\codex.cmd",
        "codex": r"C:\Program Files\WindowsApps\OpenAI.Codex\codex.exe",
    }
    monkeypatch.setattr("repo_surgeon.codex_runner.shutil.which", candidates.get)
    command = RealCodexRunner()._command_args()
    assert command == [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c",
        r"C:\Users\test\AppData\Roaming\npm\codex.cmd",
        "exec", "--model", "gpt-5.6-luna", "--sandbox", "workspace-write", "-"]
    assert "WindowsApps" not in " ".join(command)


def test_native_executable_is_invoked_directly(monkeypatch):
    monkeypatch.setattr("repo_surgeon.codex_runner.os.name", "posix")
    monkeypatch.setattr("repo_surgeon.codex_runner.shutil.which", lambda _: "/usr/bin/codex")
    assert RealCodexRunner(sandbox="read-only")._command_args() == [
        "/usr/bin/codex", "exec", "--model", "gpt-5.6-luna", "--sandbox", "read-only", "-"]


def test_missing_executable_has_clear_error(monkeypatch):
    monkeypatch.setattr("repo_surgeon.codex_runner.shutil.which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="Could not find 'codex' on PATH"):
        RealCodexRunner()._command_args()


@pytest.mark.asyncio
async def test_prompt_uses_stdin_and_is_absent_from_failure_logs(tmp_path, monkeypatch, caplog):
    secret = "OPENAI_API_KEY=never-log-this"
    prompt_fragment = "danger & whoami | echo"
    runner = RealCodexRunner()
    monkeypatch.setattr(runner, "_command_args", lambda: ["codex.exe", "exec", "--model",
        "gpt-5.6-luna", "--sandbox", "workspace-write", "-"])
    async def empty_diff(_): return ""
    monkeypatch.setattr(runner, "_diff", empty_diff)
    captured = {}
    def fail(command, **kwargs):
        captured.update(kwargs)
        raise PermissionError("denied")
    monkeypatch.setattr("repo_surgeon.codex_runner.subprocess.run", fail)
    item = UpgradeItem(id="upgrade-safe", dependency=prompt_fragment, from_version="1", to_version="2",
                       category=UpgradeCategory.MAJOR, risk=.5, rationale="test")
    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError) as raised:
        await runner.edit(Path(tmp_path), item, None, failure_context=secret)
    assert captured["input"]
    assert prompt_fragment in captured["input"]
    assert prompt_fragment not in " ".join(runner._command_args())
    combined = caplog.text + str(raised.value)
    assert prompt_fragment not in combined
    assert "never-log-this" not in combined
    assert "codex.exe" in combined
    assert not (tmp_path / "AGENTS.md").exists()

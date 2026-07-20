from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path

from .contracts import ChangeDetail, EditResult, UpgradeItem
from .trace import current_tracer

logger = logging.getLogger(__name__)

# Directories/files Repo Surgeon itself creates inside the cloned repo (Scout's
# `pip install --target .repo-surgeon-deps`, pytest's cache, bytecode, npm/pnpm/
# yarn's node_modules, and the temporary AGENTS.md this runner writes). None of
# these are part of the migration Codex made, so they must never end up in the
# collected patch.
GENERATED_PATHS = {".repo-surgeon-deps", ".pytest_cache", "__pycache__", "AGENTS.md", "node_modules"}


class RealCodexRunner:
    # "workspace-write" (Codex's default) spawns the shell commands it runs
    # under a separate, more-restricted Windows account (observed here as
    # `CodexSandboxUsers`). Anything that account creates — e.g. `.pytest_cache`
    # from Codex self-invoking pytest — ends up with no ACL entry at all for
    # the account actually running this pipeline, not even permission to reset
    # the ACL, which made "give the next step access" impossible after the
    # fact. "danger-full-access" runs those commands under our own process
    # identity instead, so there's only ever one identity touching the clone
    # and no ACL boundary to reconcile. The clone is a disposable temp
    # workspace per job (see sandbox/manager.py), and the actual dependency
    # install/test/verify commands still run inside Docker, unaffected by this
    # setting — this only changes the sandboxing of Codex's own ad hoc shell
    # commands (listing files, reading source, an occasional self-check).
    def __init__(self, timeout_seconds: int = 300, command: str = "codex",
                 sandbox: str = "danger-full-access") -> None:
        self.timeout_seconds, self.command, self.sandbox = timeout_seconds, command, sandbox

    async def edit(self, workdir: Path, item: UpgradeItem, breaking_change: ChangeDetail | None,
                   failure_context: str | None = None, preserve_paths: Iterable[str] = ()) -> EditResult:
        context = breaking_change.model_dump_json() if breaking_change else "No migration notes available."
        prompt = (f"Perform this exact change now: upgrade {item.dependency} from {item.from_version} to {item.to_version}.\n"
                  f"Migration context: {context}\nFailure context: {failure_context or 'None'}\n"
                  "Find the dependency manifest, make the required focused edit, and leave it as an uncommitted "
                  "working-tree change. Do not merely explain the change, do not commit it, and do not stop until "
                  "`git diff` would show the edit. Do not run the test suite, install dependencies, or run any "
                  "other command yourself — a separate verification step runs right after you finish.")
        return await self._run(workdir, prompt, label=item.id, preserve_paths=preserve_paths)

    async def write_tests(self, workdir: Path, language: str) -> EditResult:
        """Bootstrap a minimal test suite when Scout found no test command.

        Without something to run, upgrades on this repo can never be verified
        (see verifier/service.py's no_test_command guard) — they'd sit at
        needs_human forever. Codex writes the tests once, up front.

        Python and JS/TS need different instructions here, not just a
        different runner name: the sandbox image ships pytest regardless of
        what a Python repo declares (docker/python/Dockerfile), so Python
        tests need zero new dependencies and zero manifest changes — "add
        files only" is safe to enforce. The Node image has no test framework
        preinstalled (docker/node/Dockerfile only ships Stryker's mutation
        runners globally, not jest/vitest/mocha themselves), so a JS/TS repo
        with nothing configured has no framework to write tests *with* unless
        Codex adds one — except Node 22 ships a built-in test runner
        (`node --test`, via 'node:test'/'node:assert') that needs nothing
        installed, so that's what's asked for by default, with wiring
        `package.json`'s "scripts.test" (an existing-file edit, unlike
        Python's file-only constraint) as part of the same task.
        """
        if language in {"JavaScript", "TypeScript"}:
            prompt = (
                "This repository has no automated test suite wired into package.json's \"scripts.test\". Before "
                "any dependency upgrades are attempted, read the codebase and write a minimal but meaningful test "
                "suite that exercises its current behavior (import the main module(s); call/exercise the key "
                "functions, routes, or classes you can observe) — so a later dependency upgrade can be checked "
                "against it. Prefer Node's built-in test runner ('node:test' and 'node:assert', run via "
                "`node --test`) so nothing new needs installing; only add a devDependency (e.g. vitest) if the "
                "codebase genuinely can't be tested that way (e.g. it needs a browser-like DOM), and explain why "
                "in your final message if you do. Add test files under a tests/ (or __tests__/) directory if one "
                "doesn't exist, and set package.json's \"scripts\".\"test\" to the command that runs them (e.g. "
                "\"node --test\") — that field is the only existing file you should change; leave application "
                "code untouched. Do not commit. Leave everything as an uncommitted working-tree change. Do not "
                "merely explain the plan — write the files, and do not stop until `git status` would show them. "
                "Do not run the test suite, or install/build anything, yourself — a separate step runs these "
                "tests right after you finish; reading a file back to sanity-check it is fine."
            )
        else:
            prompt = (
                "This repository has no detected automated test suite. Before any dependency upgrades are "
                "attempted, read the codebase and write a minimal but meaningful pytest test suite that "
                "exercises its current behavior (import the main module(s); call/exercise the key functions, "
                "routes, or classes you can observe) — so a later dependency upgrade can be checked against it. "
                "Add test files only, under a tests/ directory if one doesn't exist. Do not modify existing "
                "application code, do not add new dependencies, and do not commit. Leave the new files as an "
                "uncommitted working-tree change. Do not merely explain the plan — write the files, and do not "
                "stop until `git status` would show them. Do not run pytest, or any other command that executes "
                "the test suite, yourself — a separate step runs these tests right after you finish; static "
                "checks like reading the file back or `python -m py_compile` are fine if you want to sanity-check "
                "syntax."
            )
        return await self._run(workdir, prompt, label="bootstrap-tests")

    async def _run(self, workdir: Path, prompt: str, label: str, preserve_paths: Iterable[str] = ()) -> EditResult:
        preserve = frozenset(preserve_paths)
        agents = workdir / "AGENTS.md"
        created_agents = not agents.exists()
        if created_agents:
            agents.write_text("# Repo Surgeon\nMake focused dependency migration edits. Preserve existing project conventions.\n", encoding="utf-8")
        try:
            before = await self._diff(workdir, preserve)
            started = time.monotonic()
            try:
                # Prompt goes over stdin, not argv: failure_context/migration
                # notes can run to tens of KB, and cmd.exe (which _command_args
                # routes through on Windows) truncates any command line over
                # 8191 chars — codex would silently receive a mangled prompt.
                # `codex exec` reads stdin whenever no PROMPT argument is given.
                command = self._command_args()
                completed = await asyncio.to_thread(subprocess.run, command, cwd=workdir,
                    input=prompt, check=True, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=self.timeout_seconds)
            except subprocess.CalledProcessError as error:
                # str(error) alone omits stdout/stderr, which is the only place
                # codex explains *why* it exited non-zero — without this a
                # failure here is undiagnosable from the log alone.
                logger.warning("codex exec failed for %s after %.1fs (exit %s):\nstdout: %s\nstderr: %s",
                               label, time.monotonic() - started, error.returncode,
                               (error.stdout or "").strip()[-3000:], (error.stderr or "").strip()[-3000:])
                raise RuntimeError(f"codex exec failed for {label} (exit {error.returncode}): "
                                   f"{(error.stderr or error.stdout or '').strip()[-1500:]}") from error
            except (subprocess.TimeoutExpired, FileNotFoundError) as error:
                logger.warning("codex exec failed for %s after %.1fs: %s", label, time.monotonic() - started, error)
                raise RuntimeError(f"codex exec failed for {label}: {error}") from error
            logger.info("codex exec for %s finished in %.1fs", label, time.monotonic() - started)
            current_tracer().write("codex", "stdout", {"stdout": completed.stdout, "stderr": completed.stderr},
                                   label=label)
            patch = await self._diff(workdir, preserve)
            return EditResult(files_changed=self._files_from_diff(patch), patch=patch if patch != before else "",
                              logs=f"{completed.stdout}\n{completed.stderr}".strip())
        finally:
            if created_agents:
                agents.unlink(missing_ok=True)

    def _command_args(self) -> list[str]:
        """Resolve npm's Windows .cmd shim before invoking Codex headlessly.

        No PROMPT argument is appended — the prompt is written to the
        subprocess's stdin by the caller instead, since `codex exec` reads
        stdin whenever no positional prompt is given.
        """
        # Prefer npm's shim on Windows: an app-installed codex.exe can be on
        # PATH first but inaccessible to a subprocess launched from Python.
        shim = shutil.which(f"{self.command}.cmd") if os.name == "nt" else None
        if shim:
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", shim,
                    "exec", "--sandbox", self.sandbox]
        executable = shutil.which(self.command)
        if executable is None:
            raise FileNotFoundError(f"Could not find {self.command!r} on PATH")
        if executable.lower().endswith((".cmd", ".bat")):
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", executable,
                    "exec", "--sandbox", self.sandbox]
        return [executable, "exec", "--sandbox", self.sandbox]

    async def _diff(self, workdir: Path, preserve_paths: frozenset[str] = frozenset()) -> str:
        # Deliberately does not use `git add -N .`: that stages every path in
        # the workspace, including generated files Scout/pytest leave behind
        # (see GENERATED_PATHS), which would otherwise show up in the patch as
        # part of the "migration". Tracked edits and untracked files are
        # collected and filtered separately instead.
        tracked = await self._run_git(workdir, ["git", "diff", "--binary", "HEAD"])
        listed = await self._run_git(workdir, ["git", "ls-files", "--others", "--exclude-standard"])
        parts = [tracked.stdout]
        for path in listed.stdout.splitlines():
            path = path.strip()
            if not path or self._is_generated(path, preserve_paths):
                continue
            result = await asyncio.to_thread(subprocess.run,
                ["git", "diff", "--no-index", "--binary", "/dev/null", path], cwd=workdir,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            # `git diff --no-index` exits 1 when it finds a difference (the
            # expected case here) — only >1 signals a real failure.
            if result.returncode not in (0, 1):
                raise RuntimeError(self._git_error(["git", "diff", "--no-index", path], result))
            parts.append(result.stdout)
        return "".join(parts)

    @staticmethod
    def _is_generated(path: str, preserve_paths: frozenset[str] = frozenset()) -> bool:
        # preserve_paths is Scout's bootstrapped test files (RepoProfile.
        # bootstrap_test_paths): they're scratch fixtures written once so every
        # upgrade item has something to verify against, never part of any
        # single item's own migration — excluding them here is what keeps them
        # out of every item's PR patch (orchestrator.py separately keeps them
        # off `git clean`'s scope so they physically survive between items).
        if path in preserve_paths:
            return True
        # Checks every path segment, not just the top-level one: __pycache__
        # shows up nested under any package/test directory (tests/__pycache__,
        # app/__pycache__, ...), not only at the repo root. Matching parts[0]
        # only missed all of those, letting compiled bytecode leak into item
        # patches and — worse — get selected as a "test file" by AffectedTests'
        # tests/-prefix heuristic, which then fails outright trying to collect
        # a .pyc as if it were a test module.
        parts = Path(path).parts
        return not parts or any(part in GENERATED_PATHS for part in parts)

    async def _run_git(self, workdir: Path, command: list[str]):
        result = await asyncio.to_thread(subprocess.run, command, cwd=workdir,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if result.returncode != 0:
            raise RuntimeError(self._git_error(command, result))
        return result

    @staticmethod
    def _git_error(command: list[str], result) -> str:
        # `check=True` alone loses the reason Git rejected the command — this
        # is the only place that reason is available, so surface it in full.
        return (f"{' '.join(command)} failed (exit {result.returncode}):\n"
                f"stdout: {(result.stdout or '').strip()[-2000:]}\n"
                f"stderr: {(result.stderr or '').strip()[-2000:]}")

    @staticmethod
    def _files_from_diff(patch: str) -> list[str]:
        return [line[6:] for line in patch.splitlines() if line.startswith("+++ b/")]


class MockCodexRunner:
    def __init__(self, fail_edits: int = 0) -> None:
        self.fail_edits = fail_edits
        self.calls = 0

    async def edit(self, workdir: Path, item: UpgradeItem, breaking_change: ChangeDetail | None,
                   failure_context: str | None = None, preserve_paths: Iterable[str] = ()) -> EditResult:
        self.calls += 1
        return EditResult(files_changed=["mock_dependency.txt"],
                          patch=f"mock edit {self.calls} for {item.dependency}",
                          logs="Mock Codex edit completed")

    async def write_tests(self, workdir: Path, language: str) -> EditResult:
        self.calls += 1
        return EditResult(files_changed=["tests/test_mock_bootstrap.py"],
                          patch="mock bootstrap test suite", logs="Mock Codex test bootstrap completed")

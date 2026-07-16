from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from ..contracts import CommandResult
from .command_runner import AsyncCommandRunner
from .errors import CloneError, DockerUnavailableError, InvalidRepositoryError
from .policy import NetworkPhase, SandboxPolicy


class RealSandbox:
    def __init__(self, runner: AsyncCommandRunner | None = None, root: Path | None = None,
                 policy: SandboxPolicy | None = None, allow_local_paths: bool = False,
                 allow_host_execution: bool = False, shallow: bool = True) -> None:
        self.runner = runner or AsyncCommandRunner()
        self.root = root or Path(tempfile.mkdtemp(prefix="repo-surgeon-workspaces-"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.policy = policy or SandboxPolicy()
        self.allow_local_paths = allow_local_paths
        self.allow_host_execution = allow_host_execution
        self.shallow = shallow
        self._owned: set[Path] = set()

    def validate_url(self, value: str) -> str:
        path = Path(value)
        if self.allow_local_paths and path.exists():
            return str(path.resolve())
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise InvalidRepositoryError("only credential-free HTTPS repository URLs are supported")
        if any(char in value for char in ("\n", "\r", "\0")):
            raise InvalidRepositoryError("repository URL contains control characters")
        return value

    async def clone(self, repo_url: str) -> Path:
        source = self.validate_url(repo_url)
        target = self.root / f"job-{uuid4().hex}"
        command = ["git", "clone"]
        if self.shallow:
            command += ["--depth", "1"]
        command += ["--", source, str(target)]
        result = await self.runner.run(command, timeout=self.policy.timeout_seconds)
        if result.exit_code != 0 or not (target / ".git").exists():
            shutil.rmtree(target, ignore_errors=True)
            raise CloneError(result.stderr or "git clone did not create a repository")
        self._owned.add(target.resolve())
        return target

    async def docker_available(self) -> bool:
        result = await self.runner.run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=10)
        return result.exit_code == 0

    async def execute(self, workdir: Path, command: list[str], image: str,
                      phase: NetworkPhase = NetworkPhase.EXECUTION,
                      timeout: float | None = None) -> CommandResult:
        resolved = workdir.resolve()
        if resolved not in self._owned or self.root.resolve() not in resolved.parents:
            raise InvalidRepositoryError("execution is restricted to sandbox-owned workspaces")
        if image not in {"repo-surgeon-python", "repo-surgeon-node",
                         "repo-surgeon-python:local", "repo-surgeon-node:local"}:
            raise InvalidRepositoryError("unapproved sandbox image")
        if await self.docker_available():
            args = ["docker", "run", "--rm", "--init", "--cap-drop=ALL",
                "--security-opt", "no-new-privileges", "--memory", self.policy.memory,
                "--cpus", str(self.policy.cpus), "--pids-limit", str(self.policy.pids_limit),
                "--network", self.policy.network.docker_mode(phase),
                "--env", "PYTHONPATH=/workspace/.repo-surgeon-deps",
                "--env", "GIT_CONFIG_COUNT=1",
                "--env", "GIT_CONFIG_KEY_0=safe.directory",
                "--env", "GIT_CONFIG_VALUE_0=/workspace",
                "--mount", f"type=bind,src={resolved},dst=/workspace",
                "--workdir", "/workspace", "--tmpfs", "/tmp:rw,noexec,nosuid,size=512m"]
            if self.policy.read_only:
                args.append("--read-only")
            args += [image, *command]
            return await self.runner.run(args, timeout=timeout or self.policy.timeout_seconds)
        if self.allow_host_execution:
            return await self.runner.run(command, cwd=workdir, timeout=timeout or self.policy.timeout_seconds)
        raise DockerUnavailableError("Docker unavailable and host execution is disabled")

    async def cleanup(self, workdir: Path | None = None) -> None:
        targets = list(self._owned) if workdir is None else [workdir.resolve()]
        for target in targets:
            if target in self._owned and self.root.resolve() in target.parents:
                shutil.rmtree(target, ignore_errors=True)
                self._owned.discard(target)


class SandboxedCommandRunner:
    """Runner-compatible adapter that prevents Scout/Verifier commands escaping Docker."""
    def __init__(self, sandbox: RealSandbox, python_image: str = "repo-surgeon-python:local",
                 node_image: str = "repo-surgeon-node:local") -> None:
        self.sandbox, self.python_image, self.node_image = sandbox, python_image, node_image

    async def run(self, command, cwd: Path | None = None, env=None, timeout=None, strict=False) -> CommandResult:
        if cwd is None:
            raise ValueError("sandboxed repository commands require cwd")
        image = self.node_image if (cwd / "package.json").exists() else self.python_image
        network_tools = {"npm", "pnpm", "yarn", "uv", "poetry", "pipenv", "osv-scanner"}
        phase = (NetworkPhase.DEPENDENCY_INSTALL if command and
                 (command[0] in network_tools or "pip" in command or "pip_audit" in command)
                 else NetworkPhase.EXECUTION)
        result = await self.sandbox.execute(cwd, list(command), image, phase, timeout)
        if strict and result.exit_code not in (0, None):
            raise RuntimeError(result.stderr)
        return result

from __future__ import annotations
import json
from pathlib import Path
from ..contracts import Dependency, StackInfo
from ..sandbox.command_runner import AsyncCommandRunner


class DependencyCollector:
    def __init__(self, runner: AsyncCommandRunner) -> None: self.runner = runner
    async def collect(self, root: Path, stack: StackInfo) -> list[Dependency]:
        command = (["python", "-m", "pip", "list", "--format=json"] if stack.language == "Python" else
            [stack.package_manager, "ls", "--all", "--json"] if stack.language in {"JavaScript", "TypeScript"} else None)
        if not command: return []
        result = await self.runner.run(command, cwd=root)
        try:
            data = json.loads(result.stdout)
            if isinstance(data, list): return [Dependency(name=x["name"], version=x.get("version", ""), ecosystem="PyPI") for x in data]
            return [Dependency(name=name, version=value.get("version", ""), ecosystem="npm") for name, value in data.get("dependencies", {}).items()]
        except (json.JSONDecodeError, KeyError, TypeError): return []

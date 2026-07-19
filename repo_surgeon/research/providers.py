from __future__ import annotations
import asyncio, json
from dataclasses import dataclass, field
from typing import Protocol
from urllib.request import Request, urlopen


@dataclass
class RegistryMetadata:
    package: str
    ecosystem: str
    latest_version: str | None = None
    release_url: str | None = None
    requires_python: str | None = None
    migration_signals: list[str] = field(default_factory=list)
    provider: str = "registry"


class RegistryMetadataProvider(Protocol):
    async def lookup(self, package: str) -> RegistryMetadata | None: ...


class _JsonRegistry:
    url: str
    ecosystem: str
    async def lookup(self, package: str) -> RegistryMetadata | None:
        def fetch():
            request = Request(self.url.format(package=package), headers={"User-Agent": "Repo-Surgeon/1"})
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read(1_000_000))
        try: return self.parse(package, await asyncio.to_thread(fetch))
        except (OSError, ValueError): return None


class PyPIRegistryProvider(_JsonRegistry):
    url, ecosystem = "https://pypi.org/pypi/{package}/json", "PyPI"
    def parse(self, package, data):
        info = data.get("info", {})
        return RegistryMetadata(package, self.ecosystem, info.get("version"), info.get("project_url"),
            info.get("requires_python"), provider="pypi")


class NpmRegistryProvider(_JsonRegistry):
    url, ecosystem = "https://registry.npmjs.org/{package}", "npm"
    def parse(self, package, data):
        latest = data.get("dist-tags", {}).get("latest")
        return RegistryMetadata(package, self.ecosystem, latest,
            f"https://www.npmjs.com/package/{package}/v/{latest}" if latest else None, provider="npm")

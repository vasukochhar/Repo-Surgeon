from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class NetworkPhase(str, Enum):
    DEPENDENCY_INSTALL = "dependency_install"
    EXECUTION = "execution"


class NetworkPolicy(BaseModel):
    install_network: bool = True
    execution_network: bool = False

    def docker_mode(self, phase: NetworkPhase) -> str:
        allowed = self.install_network if phase is NetworkPhase.DEPENDENCY_INSTALL else self.execution_network
        return "bridge" if allowed else "none"


class SandboxPolicy(BaseModel):
    memory: str = "2g"
    cpus: float = 2.0
    pids_limit: int = 256
    timeout_seconds: float = 600
    read_only: bool = False
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)

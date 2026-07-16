from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Baseline(BaseModel):
    tests_passed: int = 0
    tests_failed: int = 0
    build_ok: bool = True
    coverage: float | None = None


class Dependency(BaseModel):
    name: str
    version: str
    latest_version: str | None = None


class Vulnerability(BaseModel):
    dependency: str
    severity: str
    identifier: str | None = None


class RepoProfile(BaseModel):
    language: str
    package_manager: str
    test_runner: str
    baseline: Baseline
    dependencies: list[Dependency] = Field(default_factory=list)
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)


class ChangeDetail(BaseModel):
    current: str
    target: str
    changelog_url: str | None = None
    migration_notes: str = ""
    known_issues: list[str] = Field(default_factory=list)


class BreakingChanges(BaseModel):
    changes: dict[str, ChangeDetail] = Field(default_factory=dict)


class UpgradeCategory(str, Enum):
    SECURITY = "security"
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


class UpgradeItem(BaseModel):
    id: str
    dependency: str
    from_version: str
    to_version: str
    category: UpgradeCategory
    risk: float = Field(ge=0, le=1)
    rationale: str
    breaking_change_ref: str | None = None


class UpgradePlan(BaseModel):
    items: list[UpgradeItem] = Field(default_factory=list)


class VerifyResult(BaseModel):
    item_id: str
    tests_passed: int = 0
    tests_failed: int = 0
    failing_tests: list[str] = Field(default_factory=list)
    logs: str = ""
    build_ok: bool = True

    @property
    def passed(self) -> bool:
        return self.build_ok and self.tests_failed == 0


class EditResult(BaseModel):
    files_changed: list[str] = Field(default_factory=list)
    patch: str = ""
    logs: str = ""


class SurgeonStatus(str, Enum):
    GREEN = "green"
    NEEDS_HUMAN = "needs_human"
    FAILED = "failed"


class SurgeonResult(BaseModel):
    item_id: str
    status: SurgeonStatus
    iterations: int
    files_changed: list[str] = Field(default_factory=list)
    patch: str = ""


class PRRequest(BaseModel):
    items: list[UpgradeItem]
    branch: str
    evidence: list[SurgeonResult]


class PRResult(BaseModel):
    url: str
    item_ids: list[str] = Field(default_factory=list)


class Event(BaseModel):
    job_id: str
    stage: str
    type: str
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)

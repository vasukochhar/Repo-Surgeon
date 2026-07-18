from __future__ import annotations

from datetime import timezone, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExecutionStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class CommandResult(BaseModel):
    command: list[str] = Field(default_factory=list)
    cwd: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    status: ExecutionStatus = ExecutionStatus.SKIPPED
    tool_unavailable: bool = False


class CoverageResult(BaseModel):
    line_percent: float | None = None
    branch_percent: float | None = None
    files: dict[str, float] = Field(default_factory=dict)
    changed_code_percent: float | None = None
    status: ExecutionStatus = ExecutionStatus.NOT_APPLICABLE
    command_result: CommandResult | None = None


class StackInfo(BaseModel):
    language: str = "unsupported"
    language_version: str | None = None
    package_manager: str = "unknown"
    package_manager_version: str | None = None
    test_runner: str = "unknown"
    build_tool: str | None = None
    dependency_files: list[str] = Field(default_factory=list)
    lockfiles: list[str] = Field(default_factory=list)
    project_root: str = "."
    is_monorepo: bool = False


class DetectedCommands(BaseModel):
    install: list[str] | None = None
    test: list[str] | None = None
    build: list[str] | None = None
    coverage: list[str] | None = None


class Baseline(BaseModel):
    tests_passed: int = 0
    tests_failed: int = 0
    build_ok: bool = True
    coverage: float | None = None
    tests_skipped: int = 0
    test_command: list[str] | None = None
    build_command: list[str] | None = None
    install_command: list[str] | None = None
    coverage_command: list[str] | None = None
    test_duration_seconds: float = 0.0
    build_duration_seconds: float = 0.0
    failing_tests: list[str] = Field(default_factory=list)
    test_result: CommandResult | None = None
    build_result: CommandResult | None = None
    install_result: CommandResult | None = None
    failure_fingerprints: list[str] = Field(default_factory=list)


class Dependency(BaseModel):
    name: str
    version: str
    latest_version: str | None = None
    direct: bool | None = None
    ecosystem: str | None = None
    source_file: str | None = None
    requested_version: str | None = None


class Vulnerability(BaseModel):
    dependency: str
    severity: str = "unknown"
    identifier: str | None = None
    aliases: list[str] = Field(default_factory=list)
    package_version: str | None = None
    fixed_versions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    advisory_url: str | None = None
    ecosystem: str | None = None
    summary: str | None = None
    fix_available: bool = False
    breaking_fix: bool = False


class ScannerExecution(BaseModel):
    scanner: str
    status: ExecutionStatus
    result: CommandResult | None = None
    findings_count: int = 0
    message: str = ""


class SecurityReport(BaseModel):
    findings: list[Vulnerability] = Field(default_factory=list)
    total: int = 0
    counts_by_severity: dict[str, int] = Field(default_factory=dict)
    fix_available_count: int = 0
    scanners: list[ScannerExecution] = Field(default_factory=list)


class MutationReport(BaseModel):
    tool: str
    killed: int = 0
    survived: int = 0
    timeout: int = 0
    suspicious: int = 0
    untested: int = 0
    total: int = 0
    score: float | None = None
    targeted_files: list[str] = Field(default_factory=list)
    status: ExecutionStatus = ExecutionStatus.NOT_APPLICABLE
    command_result: CommandResult | None = None


class AffectedTestResult(BaseModel):
    selected_tests: list[str] = Field(default_factory=list)
    command: list[str] = Field(default_factory=list)
    result: CommandResult | None = None
    fallback_reason: str | None = None
    duration_seconds: float = 0.0


class RepoProfile(BaseModel):
    language: str
    package_manager: str
    test_runner: str
    baseline: Baseline
    dependencies: list[Dependency] = Field(default_factory=list)
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)
    schema_version: str = "1.0"
    repository: dict[str, Any] = Field(default_factory=dict)
    stack: StackInfo | None = None
    commands: DetectedCommands = Field(default_factory=DetectedCommands)
    coverage_result: CoverageResult | None = None
    security_report: SecurityReport = Field(default_factory=SecurityReport)
    raw_scanner_results: dict[str, Any] = Field(default_factory=dict)
    sandbox_metadata: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    profile_path: str | None = None


class ChangeDetail(BaseModel):
    current: str
    target: str
    changelog_url: str | None = None
    migration_notes: str = ""
    known_issues: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


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
    newly_failing_tests: list[str] = Field(default_factory=list)
    existing_failing_tests: list[str] = Field(default_factory=list)
    fixed_tests: list[str] = Field(default_factory=list)
    coverage_before: float | None = None
    coverage_after: float | None = None
    coverage_delta: float | None = None
    baseline_build_ok: bool = True
    build_regression: bool = False
    test_execution_failed: bool = False
    affected_tests_failed: bool = False
    coverage_regression: bool = False
    regression_aware: bool = False
    mutation_report: MutationReport | None = None
    test_quality_score: float | None = None
    affected_test_result: AffectedTestResult | None = None
    full_test_result: CommandResult | None = None
    build_result: CommandResult | None = None
    concise_failure_context: str = ""

    @property
    def passed(self) -> bool:
        if self.regression_aware:
            return not (self.newly_failing_tests or self.build_regression or
                        self.test_execution_failed or self.affected_tests_failed)
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
    verification: VerifyResult | None = None


class PRRequest(BaseModel):
    items: list[UpgradeItem]
    branch: str
    evidence: list[SurgeonResult]
    repo_url: str | None = None
    workdir: str | None = None
    base_branch: str | None = None


class PRResult(BaseModel):
    url: str
    item_ids: list[str] = Field(default_factory=list)
    number: int | None = None
    branch: str | None = None
    head_sha: str | None = None
    ci_status: str | None = None
    ci_logs: str | None = None
    repository: str | None = None


class Event(BaseModel):
    job_id: str
    stage: str
    type: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)

from __future__ import annotations

from pathlib import Path

from ..contracts import (Baseline, BreakingChanges, ChangeDetail, Dependency, PRRequest,
                         PRResult, RepoProfile, UpgradeItem, VerifyResult)


class MockScout:
    async def profile(self, workdir: Path) -> RepoProfile:
        return RepoProfile(language="Python", package_manager="pip", test_runner="pytest",
            baseline=Baseline(tests_passed=3, coverage=85.0),
            dependencies=[Dependency(name="example-lib", version="1.0.0", latest_version="2.0.0")])


class MockResearcher:
    async def research(self, profile: RepoProfile) -> BreakingChanges:
        return BreakingChanges(changes={"example-lib": ChangeDetail(current="1.0.0", target="2.0.0",
            migration_notes="Update the mock configuration API.")})


class MockVerifier:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times, self.calls = fail_times, 0

    async def verify(self, item: UpgradeItem, workdir: Path) -> VerifyResult:
        self.calls += 1
        failed = self.calls <= self.fail_times
        return VerifyResult(item_id=item.id, tests_passed=0 if failed else 3,
            tests_failed=1 if failed else 0, failing_tests=["test_mock"] if failed else [],
            logs="mock failure" if failed else "", build_ok=not failed)


class MockReviewer:
    async def open_prs(self, request: PRRequest) -> list[PRResult]:
        return [PRResult(url=f"https://example.invalid/pr/{request.branch}", item_ids=[i.id for i in request.items])]

import pytest

from repo_surgeon.contracts import BreakingChanges, Baseline, RepoProfile
from repo_surgeon.planner import Planner


@pytest.mark.asyncio
async def test_planner_deterministically_sorts_categories() -> None:
    async def response(_: str) -> str:
        return '{"items":[{"id":"major","dependency":"a","from_version":"1","to_version":"2","category":"major","risk":0.1,"rationale":"x"},{"id":"security","dependency":"b","from_version":"1","to_version":"2","category":"security","risk":0.9,"rationale":"x"}]}'
    profile = RepoProfile(language="Python", package_manager="pip", test_runner="pytest", baseline=Baseline())
    plan = await Planner(response).build_plan(profile, BreakingChanges())
    assert [item.id for item in plan.items] == ["security", "major"]

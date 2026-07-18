import pytest

from repo_surgeon.ci import GitHubCIWatcher
from repo_surgeon.contracts import (Baseline, ChangeDetail, Dependency, PRResult, RepoProfile,
                                    SurgeonResult, SurgeonStatus, UpgradeCategory, UpgradeItem)
from repo_surgeon.github_layer import GitHubReviewer, github_repository
from repo_surgeon.researcher import OpenAIResearcher


def _item() -> UpgradeItem:
    return UpgradeItem(id="upgrade-1", dependency="requests", from_version="2.31.0", to_version="2.32.3",
                       category=UpgradeCategory.SECURITY, risk=.2, rationale="Fix a published advisory",
                       breaking_change_ref="https://example.test/changelog")


@pytest.mark.asyncio
async def test_researcher_parses_evidence_and_rejects_unknown_packages() -> None:
    async def respond(_: str) -> str:
        return '''{"changes":{"requests":{"current":"2.31.0","target":"2.32.3","changelog_url":"https://example.test/release","migration_notes":"No code changes.","known_issues":[],"sources":["https://example.test/release"]},"other":{"current":"1","target":"2"}}}'''

    profile = RepoProfile(language="Python", package_manager="pip", test_runner="pytest", baseline=Baseline(),
                          dependencies=[Dependency(name="requests", version="2.31.0", latest_version="2.32.3")])
    result = await OpenAIResearcher(respond).research(profile)
    assert list(result.changes) == ["requests"]
    assert result.changes["requests"].sources == ["https://example.test/release"]


def test_pr_body_and_github_url_are_reviewable() -> None:
    body = GitHubReviewer.pr_body(_item(), SurgeonResult(item_id="upgrade-1", status=SurgeonStatus.GREEN,
                                  iterations=1, files_changed=["requirements.txt"], patch="diff"))
    assert "Confidence:** A" in body and "Rollback" in body and "Evidence:" in body
    assert github_repository("git@github.com:openai/repo-surgeon.git") == "openai/repo-surgeon"


class _Checks:
    async def check_runs(self, _: str, sha: str) -> list[dict]:
        if sha == "bad":
            return [{"name": "test", "status": "completed", "conclusion": "failure",
                     "output": {"title": "pytest", "summary": "test_x failed"}}]
        return [{"name": "test", "status": "completed", "conclusion": "success", "output": {}}]


@pytest.mark.asyncio
async def test_ci_watcher_repairs_and_rechecks(tmp_path) -> None:
    calls = []

    async def repair(pr: PRResult, logs: str, _):
        calls.append((pr.head_sha, logs))
        return "fixed"

    pr = PRResult(url="https://github.test/pr/1", number=1, branch="repo-surgeon/test", head_sha="bad",
                  repository="openai/repo-surgeon")
    watched = await GitHubCIWatcher(_Checks(), repair=repair, poll_seconds=0, max_polls=1).watch([pr], tmp_path)
    assert watched[0].ci_status == "passed" and watched[0].head_sha == "fixed"
    assert calls and "test_x failed" in calls[0][1]

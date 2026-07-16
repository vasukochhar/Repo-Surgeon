import pytest

from repo_surgeon.codex_runner import MockCodexRunner
from repo_surgeon.events import EventBus
from repo_surgeon.jobstore import InMemoryJobStore, JobState
from repo_surgeon.mocks import MockResearcher, MockReviewer, MockSandbox, MockScout, MockVerifier
from repo_surgeon.orchestrator import Orchestrator
from repo_surgeon.planner import Planner
from repo_surgeon.surgeon import Surgeon


@pytest.mark.asyncio
async def test_full_mock_pipeline_reaches_done() -> None:
    store, events = InMemoryJobStore(), EventBus()
    orchestrator = Orchestrator(store, events, MockSandbox(), MockScout(), MockResearcher(), Planner(),
        Surgeon(MockCodexRunner(), MockVerifier(fail_times=1), events), MockReviewer())
    job = store.create("https://example.invalid/demo.git")
    result = await orchestrator.run(job.id)
    stages = [event.stage for event in events.history(job.id)]
    assert result.state is JobState.DONE
    assert result.results[0].iterations == 2
    assert {"scouting", "researching", "planning", "operating", "reviewing", "watching_ci"} <= set(stages)

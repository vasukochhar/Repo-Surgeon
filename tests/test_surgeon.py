from pathlib import Path

import pytest

from repo_surgeon.codex_runner import MockCodexRunner
from repo_surgeon.contracts import BreakingChanges, UpgradeCategory, UpgradeItem
from repo_surgeon.events import EventBus
from repo_surgeon.mocks import MockVerifier
from repo_surgeon.surgeon import Surgeon


def item() -> UpgradeItem:
    return UpgradeItem(id="one", dependency="example-lib", from_version="1", to_version="2",
        category=UpgradeCategory.MAJOR, risk=.7, rationale="test")


@pytest.mark.asyncio
async def test_surgeon_corrects_until_green() -> None:
    runner, verifier, events = MockCodexRunner(), MockVerifier(fail_times=1), EventBus()
    result = await Surgeon(runner, verifier, events).operate("job", Path.cwd(), item(), BreakingChanges())
    assert result.status.value == "green"
    assert result.iterations == 2
    assert len(events.history("job")) == 2


@pytest.mark.asyncio
async def test_surgeon_stops_at_iteration_cap() -> None:
    result = await Surgeon(MockCodexRunner(), MockVerifier(fail_times=10), EventBus()).operate(
        "job", Path.cwd(), item(), BreakingChanges())
    assert result.status.value == "needs_human"
    assert result.iterations == 2


class _CrashingCodex:
    async def edit(self, workdir, item, breaking_change, failure_context=None, preserve_paths=()):
        raise RuntimeError("codex exec failed: quota exceeded")

    async def write_tests(self, workdir, language):
        raise RuntimeError("unused")


@pytest.mark.asyncio
async def test_codex_crash_flags_item_instead_of_killing_job() -> None:
    # A Codex crash (quota, apply_patch mismatch) is an item-level failure —
    # it must surface as needs_human for that item, not an exception that
    # aborts the whole job and discards every earlier item's result.
    result = await Surgeon(_CrashingCodex(), MockVerifier(), EventBus()).operate(
        "job", Path.cwd(), item(), BreakingChanges())
    assert result.status.value == "needs_human"
    assert result.iterations == 1

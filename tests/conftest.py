import os

import pytest


@pytest.fixture(autouse=True)
def _no_trace_files(monkeypatch, tmp_path):
    """Keep the unit suite from writing job traces into the repo.

    Tracing is on by default so an E2E run needs no setup, but the mock-mode
    unit tests drive the same orchestrator and would otherwise leave a
    test_results/<uuid>/ directory behind on every run.
    """
    monkeypatch.setenv("REPO_SURGEON_TRACE", "0")
    monkeypatch.setenv("REPO_SURGEON_TRACE_DIR", str(tmp_path / "trace"))
    yield

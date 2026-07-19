import pytest

from repo_surgeon.model_policy import LUNA_MODEL
from repo_surgeon.planner import Planner
from repo_surgeon.research.config import ResearchConfig
from repo_surgeon.research.summarizer import OpenAISummarizer
from repo_surgeon.researcher import OpenAIResearcher


def test_all_openai_components_select_luna(monkeypatch):
    monkeypatch.delenv("REPO_SURGEON_MODEL", raising=False)
    monkeypatch.delenv("REPO_SURGEON_RESEARCH_MODEL", raising=False)
    monkeypatch.delenv("REPO_SURGEON_SUMMARIZER_MODEL", raising=False)
    planner = Planner.from_openai()
    researcher = OpenAIResearcher.from_openai()
    summarizer = OpenAISummarizer()
    assert planner._responder.model == LUNA_MODEL
    assert researcher.provider_identifier == LUNA_MODEL
    assert summarizer.model == LUNA_MODEL
    assert ResearchConfig.from_env().summarizer_model == LUNA_MODEL


@pytest.mark.parametrize("name,factory", [
    ("REPO_SURGEON_MODEL", Planner.from_openai),
    ("REPO_SURGEON_RESEARCH_MODEL", OpenAIResearcher.from_openai),
])
def test_environment_cannot_activate_another_model(monkeypatch, name, factory):
    monkeypatch.setenv(name, "different-model")
    with pytest.raises(ValueError, match="disallowed model"):
        factory()


def test_summarizer_environment_cannot_activate_another_model(monkeypatch):
    monkeypatch.setenv("REPO_SURGEON_SUMMARIZER_MODEL", "different-model")
    with pytest.raises(ValueError, match="disallowed model"):
        ResearchConfig.from_env()


@pytest.mark.parametrize("factory", [
    lambda: Planner.from_openai("different-model"),
    lambda: OpenAIResearcher.from_openai("different-model"),
    lambda: OpenAISummarizer("different-model"),
])
def test_explicit_model_cannot_bypass_luna_policy(factory):
    with pytest.raises(ValueError, match="disallowed model"):
        factory()

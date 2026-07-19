from __future__ import annotations
import json
from ..contracts import BreakingChanges, ChangeDetail


class TokenCounter:
    def __init__(self):
        try:
            import tiktoken
            self._encoding = tiktoken.get_encoding("o200k_base")
        except (ImportError, Exception):
            self._encoding = None
    def count(self, value: str) -> int:
        return len(self._encoding.encode(value)) if self._encoding else max(1, (len(value) + 3) // 4)


class ResearchContextBudgeter:
    def __init__(self, counter: TokenCounter | None = None, target: int = 8000, maximum: int = 20000):
        self.counter, self.target, self.maximum = counter or TokenCounter(), target, maximum
    def compact_card(self, card: ChangeDetail) -> dict:
        return {"package": card.package, "current": card.current, "target": card.target,
            "upgrade_type": card.upgrade_type, "research_status": card.research_status,
            "security_advisories": card.security_advisories,
            "risk_signals": [value[:240] for value in card.breaking_changes[:3] + card.known_issues[:2]],
            "primary_sources": card.sources[:2]}

    @staticmethod
    def _minimal_card(card: ChangeDetail) -> dict:
        return {"package": card.package, "current": card.current, "target": card.target,
            "upgrade_type": card.upgrade_type, "research_status": card.research_status,
            "security_advisories": card.security_advisories,
            "risk_signal": (card.breaking_changes or card.known_issues or [""])[0][:180],
            "primary_source": card.sources[0] if card.sources else None}

    def planner_index(self, changes: BreakingChanges) -> tuple[dict, list[str], int]:
        deferred = [name for name, card in changes.changes.items()
                    if card.research_status in {"failed", "deferred", "budget_exceeded"}]
        ordered = [(name, card) for name, card in changes.changes.items() if name not in deferred]
        index = {name: self.compact_card(card) for name, card in ordered}
        if self.counter.count(json.dumps(index)) > self.target:
            index = {name: self._minimal_card(card) for name, card in ordered}
        priority = {"patch": 3, "minor": 2, "major": 1, "security": 0, "unknown": 3}
        while self.counter.count(json.dumps(index)) > self.maximum:
            removable = [(priority.get(changes.changes[name].upgrade_type, 3), name)
                         for name in index if changes.changes[name].upgrade_type != "security"]
            if not removable:
                break
            _, name = max(removable)
            deferred.append(name)
            card = changes.changes[name]
            changes.changes[name] = card.model_copy(update={"research_status": "budget_exceeded",
                "truncated": True, "truncation_reason": "planner absolute context limit"})
            del index[name]
        tokens = self.counter.count(json.dumps(index))
        return index, deferred, tokens

    def surgeon_card(self, card: ChangeDetail, maximum: int) -> tuple[ChangeDetail, int]:
        tokens = self.counter.count(card.model_dump_json())
        if tokens <= maximum:
            return card, tokens
        trimmed = card.model_copy(update={
            "migration_notes": card.migration_notes[:600],
            "breaking_changes": [value[:400] for value in card.breaking_changes[:4]],
            "required_code_changes": [value[:400] for value in card.required_code_changes[:4]],
            "configuration_changes": [value[:300] for value in card.configuration_changes[:2]],
            "runtime_requirements": [value[:300] for value in card.runtime_requirements[:2]],
            "known_issues": [value[:300] for value in card.known_issues[:2]],
            "evidence": card.evidence[:2], "sources": card.sources[:3],
            "truncated": True, "truncation_reason": "Surgeon context budget"})
        tokens = self.counter.count(trimmed.model_dump_json())
        if tokens > maximum:
            trimmed = trimmed.model_copy(update={"migration_notes": "",
                "breaking_changes": trimmed.breaking_changes[:1],
                "required_code_changes": trimmed.required_code_changes[:1],
                "configuration_changes": [], "runtime_requirements": [], "known_issues": [],
                "evidence": trimmed.evidence[:1], "sources": trimmed.sources[:1]})
            tokens = self.counter.count(trimmed.model_dump_json())
        return trimmed, tokens

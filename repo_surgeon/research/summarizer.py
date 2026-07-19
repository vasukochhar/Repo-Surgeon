from __future__ import annotations
import re
from typing import Protocol
from ..model_policy import luna_only_model


class Summarizer(Protocol):
    async def summarize(self, text: str, max_chars: int) -> str: ...


class OpenAISummarizer:
    """Optional overflow-only summarizer; it never performs web search."""
    def __init__(self, model: str | None = None):
        self.model, self._client = luna_only_model(model), None

    async def summarize(self, text: str, max_chars: int) -> str:
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(max_retries=0)
        response = await self._client.responses.create(model=self.model, input=(
            f"Compress these migration notes to at most {max_chars} characters. Preserve exact versions, "
            "security IDs, API/configuration identifiers, and claim/source associations. Return text only.\n\n"
            + text[:max_chars * 8]))
        return response.output_text[:max_chars]


class DeterministicSummarizer:
    HEADINGS = re.compile(r"breaking|migration|upgrade|deprecated|removed|security|compatibility|requirements", re.I)
    async def summarize(self, text: str, max_chars: int) -> str:
        lines, seen = [], set()
        for raw in text.splitlines():
            line = raw.strip()
            key = " ".join(line.lower().split())
            if not line or key in seen or line.lower().startswith(("home ", "menu ", "copyright")): continue
            seen.add(key)
            if self.HEADINGS.search(line) or any(ch in line for ch in ("`", "()", "=", "--")):
                lines.append(line)
        value = "\n".join(lines) or "\n".join(list(dict.fromkeys(x.strip() for x in text.splitlines() if x.strip())))
        return value[:max_chars]

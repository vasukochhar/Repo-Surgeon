from __future__ import annotations
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from pydantic import BaseModel
from ..contracts import ChangeDetail


class CacheRecord(BaseModel):
    card: ChangeDetail
    source_urls: list[str]
    created_at: datetime
    expires_at: datetime
    provider: str | None = None
    schema_version: str = "2.0"


class ResearchCache(Protocol):
    def get(self, key: str) -> CacheRecord | None: ...
    def set(self, key: str, record: CacheRecord) -> None: ...


def cache_key(ecosystem: str, package: str, current: str, target: str, schema: str = "2.0") -> str:
    normalized = re.sub(r"[-_.]+", "-", package.strip().lower())
    return "|".join((ecosystem.strip().lower(), normalized, current, target, schema))


class InMemoryResearchCache:
    def __init__(self): self.records: dict[str, CacheRecord] = {}
    def get(self, key: str) -> CacheRecord | None:
        record = self.records.get(key)
        return record if record and record.schema_version == "2.0" and record.expires_at > datetime.now(timezone.utc) else None
    def set(self, key: str, record: CacheRecord) -> None: self.records[key] = record


class FileResearchCache(InMemoryResearchCache):
    def __init__(self, path: Path):
        super().__init__(); self.path = path; self._lock = threading.Lock(); self._load()
    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.records = {key: CacheRecord.model_validate(value) for key, value in data.items()}
        except (OSError, ValueError, TypeError): self.records = {}
    def set(self, key: str, record: CacheRecord) -> None:
        with self._lock:
            super().set(key, record)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps({k: v.model_dump(mode="json") for k, v in self.records.items()}), encoding="utf-8")
            except OSError:
                pass

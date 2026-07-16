from __future__ import annotations
from pathlib import Path
from hashlib import sha256
from ..contracts import RepoProfile


class ProfileWriter:
    def __init__(self, output_root: Path) -> None: self.output_root = output_root
    def write(self, profile: RepoProfile, workspace: Path) -> Path:
        identity = sha256(str(workspace.resolve()).encode()).hexdigest()[:16]
        output = self.output_root / identity
        output.mkdir(parents=True, exist_ok=True)
        path = output / "repo_profile.json"
        profile.profile_path = str(path)
        path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        return path

from __future__ import annotations
from dataclasses import dataclass
from ..contracts import Dependency, RepoProfile, Vulnerability


@dataclass(frozen=True)
class ResearchCandidate:
    dependency: Dependency
    target: str
    upgrade_type: str
    security: bool = False
    research_required: bool = False
    reason: str = ""
    vulnerability: Vulnerability | None = None


class ResearchPolicy:
    ORDER = {"security": 0, "major": 1, "minor": 2, "patch": 3}

    def candidates(self, profile: RepoProfile) -> list[ResearchCandidate]:
        vulnerabilities = {v.dependency.lower(): v for v in profile.vulnerabilities}
        output = []
        for dependency in profile.dependencies:
            vulnerability = vulnerabilities.get(dependency.name.lower())
            target = (vulnerability.fixed_versions[0] if vulnerability and vulnerability.fix_available and
                      vulnerability.fixed_versions else dependency.latest_version)
            if not target or target == dependency.version:
                continue
            upgrade_type = "security" if vulnerability else self._semver_type(dependency.version, target)
            transitive = dependency.direct is False
            required = bool(vulnerability or upgrade_type == "major" or
                            (upgrade_type == "minor" and
                             (dependency.requested_version or dependency.metadata_signals)))
            if transitive and not vulnerability:
                required = dependency.explicit_override
            reason = "security advisory" if vulnerability else "major migration" if upgrade_type == "major" else (
                "compatibility metadata" if required else "registry metadata sufficient")
            output.append(ResearchCandidate(dependency, target, upgrade_type, bool(vulnerability), required, reason, vulnerability))
        return sorted(output, key=lambda c: (self.ORDER[c.upgrade_type], c.dependency.name.lower()))

    @staticmethod
    def requires_web(candidate: ResearchCandidate, verification_failed: bool = False) -> bool:
        if candidate.dependency.direct is False and not (candidate.security or candidate.dependency.explicit_override):
            return False
        return candidate.research_required or (verification_failed and candidate.upgrade_type == "patch")

    @staticmethod
    def _semver_type(current: str, target: str) -> str:
        def parts(value):
            values = value.lstrip("v").split(".")
            try: return tuple(int(x.split("-")[0]) for x in (values + ["0", "0"])[:3])
            except ValueError: return (0, 1, 0)
        old, new = parts(current), parts(target)
        return "major" if new[0] > old[0] else "minor" if new[1] > old[1] else "patch"

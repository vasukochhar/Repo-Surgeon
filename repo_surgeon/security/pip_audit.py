from __future__ import annotations
import json
from ..contracts import Vulnerability
from .normalizer import severity


def parse_pip_audit(text: str) -> list[Vulnerability]:
    try: data = json.loads(text)
    except json.JSONDecodeError: return []
    output = []
    for dep in data.get("dependencies", data if isinstance(data, list) else []):
        for vuln in dep.get("vulns", []):
            fixes = vuln.get("fix_versions", [])
            output.append(Vulnerability(dependency=dep.get("name", "unknown"), package_version=dep.get("version"),
                ecosystem="PyPI", identifier=vuln.get("id"), aliases=vuln.get("aliases", []), severity=severity(vuln.get("severity")),
                fixed_versions=fixes, fix_available=bool(fixes), summary=vuln.get("description"), sources=["pip-audit"]))
    return output

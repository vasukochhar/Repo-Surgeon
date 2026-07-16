from __future__ import annotations
import json
from ..contracts import Vulnerability
from .normalizer import severity


def parse_npm_audit(text: str) -> list[Vulnerability]:
    try: data = json.loads(text)
    except json.JSONDecodeError: return []
    output = []
    modern = data.get("vulnerabilities", {})
    if modern:
        for name, vuln in modern.items():
            via = vuln.get("via", []); advisory = next((x for x in via if isinstance(x, dict)), {})
            fix = vuln.get("fixAvailable", False)
            output.append(Vulnerability(dependency=name, ecosystem="npm", identifier=str(advisory.get("source", advisory.get("url", name))),
                severity=severity(vuln.get("severity")), advisory_url=advisory.get("url"), summary=advisory.get("title"),
                fix_available=bool(fix), breaking_fix=isinstance(fix, dict) and bool(fix.get("isSemVerMajor")), sources=["npm-audit"]))
    else:
        for item in data.get("advisories", {}).values():
            output.append(Vulnerability(dependency=item.get("module_name", "unknown"), ecosystem="npm",
                identifier=str(item.get("id")), severity=severity(item.get("severity")), advisory_url=item.get("url"),
                summary=item.get("title"), fix_available=bool(item.get("patched_versions")), sources=["npm-audit"]))
    return output

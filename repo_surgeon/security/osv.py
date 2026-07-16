from __future__ import annotations
import json
from ..contracts import Vulnerability
from .normalizer import severity


def parse_osv(text: str) -> list[Vulnerability]:
    try: data = json.loads(text)
    except json.JSONDecodeError: return []
    output = []
    for result in data.get("results", []):
        source = result.get("source", {})
        package = source.get("package", {})
        for package_vulns in result.get("packages", [result]):
            package = package_vulns.get("package", package)
            for vuln in package_vulns.get("vulnerabilities", package_vulns.get("vulns", [])):
                fixes = [e.get("fixed") for a in vuln.get("affected", []) for r in a.get("ranges", []) for e in r.get("events", []) if e.get("fixed")]
                sev = vuln.get("database_specific", {}).get("severity")
                output.append(Vulnerability(dependency=package.get("name", "unknown"), package_version=package.get("version"),
                    ecosystem=package.get("ecosystem"), identifier=vuln.get("id"), aliases=vuln.get("aliases", []), severity=severity(sev),
                    fixed_versions=fixes, fix_available=bool(fixes), summary=vuln.get("summary"), sources=["osv"]))
    return output

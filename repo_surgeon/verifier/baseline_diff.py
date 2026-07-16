from __future__ import annotations


def compare_failures(before: list[str], after: list[str]) -> tuple[list[str], list[str], list[str]]:
    old, new = set(before), set(after)
    return sorted(new - old), sorted(new & old), sorted(old - new)

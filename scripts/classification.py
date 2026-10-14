# SPDX-License-Identifier: GPL-3.0-only
"""Check domain-category boundaries, including ancestor/suffix intersections.

This is a build-time domain model, not a simulation of live client DNS/routing.
Only exact, inclusive suffix (+.) and subdomain-only (.) patterns are supported.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    entry: str
    base: str
    suffix: bool
    apex: bool

    @classmethod
    def parse(cls, entry):
        if not entry or "*" in entry or any(c.isspace() for c in entry):
            raise ValueError(f"Cannot audit domain pattern faithfully: {entry!r}")
        suffix = entry.startswith(("+.", "."))
        base = entry[2:] if entry.startswith("+.") else entry[1:] if suffix else entry
        if not base or any(c in base for c in ",/+?#\\") or base.startswith(".") or base.endswith(".") or ".." in base:
            raise ValueError(f"Invalid audit domain pattern: {entry!r}")
        return cls(entry, base.lower(), suffix, not entry.startswith("."))

    def matches(self, host):
        host = host.lower().rstrip(".")
        return (host == self.base and self.apex) or (self.suffix and host.endswith("." + self.base))


def overlap_witness(left, right):
    """Return one hostname in BOTH patterns, or None; never use string substrings."""
    if not left.suffix:
        return left.base if right.matches(left.base) else None
    if not right.suffix:
        return right.base if left.matches(right.base) else None
    if left.base == right.base:
        return left.base if left.apex and right.apex else "probe." + left.base
    if left.base.endswith("." + right.base):
        return left.base if left.apex else "probe." + left.base
    if right.base.endswith("." + left.base):
        return right.base if right.apex else "probe." + right.base
    return None


def covered_by(pattern, candidates):
    if not pattern.suffix:
        return any(candidate.matches(pattern.base) for candidate in candidates)
    # All descendants require a suffix at this base or an ancestor. An exact apex
    # plus a subdomain-only suffix together can cover an inclusive suffix.
    descendants = any(candidate.suffix and (pattern.base == candidate.base or
                      pattern.base.endswith("." + candidate.base)) for candidate in candidates)
    return descendants and (not pattern.apex or any(c.matches(pattern.base) for c in candidates))


def overlaps(left, right):
    hits = []
    for a in left:
        for b in right:
            witness = overlap_witness(a, b)
            if witness:
                hits.append({"left_entry": a.entry, "right_entry": b.entry, "witness": witness})
    return hits


def audit_classification(domain_sets, contract):
    if contract.get("schema_version") != 1:
        raise ValueError("Unsupported classification contract")
    if set(contract) - {"schema_version", "domain_priority", "disjoint", "subsets", "priority_overlaps", "samples", "forbidden"}:
        raise ValueError("Unknown classification contract field")
    priority = contract["domain_priority"]
    if not priority or len(priority) != len(set(priority)):
        raise ValueError("Empty/duplicate classification priority")
    referenced = set(priority)
    for key in ("disjoint", "subsets", "priority_overlaps"):
        for pair in contract.get(key, []):
            if len(pair) != 2 or pair[0] == pair[1]:
                raise ValueError(f"Invalid classification pair: {pair}")
            referenced.update(pair)
    for rule in contract.get("forbidden", {}):
        referenced.add(rule)
    missing = referenced - domain_sets.keys()
    if missing:
        raise ValueError(f"Unknown classification sets: {sorted(missing)}")
    patterns = {name: [Pattern.parse(e) for e in sorted(domain_sets[name])] for name in sorted(referenced)}
    report = {"schema_version": 1, "scope": "domain categories only, not live client routing",
              "domain_priority": priority, "disjoint": [], "subsets": [], "priority_overlaps": [],
              "samples": [], "forbidden": []}
    for left, right in contract.get("disjoint", []):
        hits = overlaps(patterns[left], patterns[right])
        if hits:
            raise ValueError(f"Forbidden category overlap {left} / {right}: {hits[:5]}; review, do not subtract shared CDN ranges automatically")
        report["disjoint"].append({"left": left, "right": right, "overlap_count": 0})
    for child, parent in contract.get("subsets", []):
        uncovered = [p.entry for p in patterns[child] if not covered_by(p, patterns[parent])]
        if uncovered:
            raise ValueError(f"Category subset broken {child} -> {parent}: {uncovered[:5]}")
        report["subsets"].append({"child": child, "parent": parent, "checked_entries": len(patterns[child])})
    for before, after in contract.get("priority_overlaps", []):
        if before not in priority or after not in priority or priority.index(before) >= priority.index(after):
            raise ValueError(f"Category priority reversed: {before} must precede {after}")
        hits = overlaps(patterns[before], patterns[after])
        report["priority_overlaps"].append({"before": before, "after": after, "overlap_count": len(hits), "examples": hits[:10]})
    for rule, hosts in contract.get("forbidden", {}).items():
        for host in hosts:
            matched = [p.entry for p in patterns[rule] if p.matches(host)]
            if matched:
                raise ValueError(f"Forbidden domain {host} matched {rule}: {matched}")
            report["forbidden"].append({"rule": rule, "domain": host, "matched": False})
    for case in contract.get("samples", []):
        host, expected = case["domain"], case["expected"]
        if expected is not None and expected not in priority:
            raise ValueError(f"Unknown sample expectation: {expected}")
        matched = [name for name in priority if any(p.matches(host) for p in patterns[name])]
        actual = matched[0] if matched else None
        if actual != expected:
            raise ValueError(f"Classification regression {host}: expected {expected}, got {actual}; matches={matched}")
        report["samples"].append({"domain": host, "winner": actual, "all_matching_categories": matched})
    return report

# SPDX-License-Identifier: GPL-3.0-only
"""Audit upstream domain categories separately from intentional broad overrides."""
if __package__:
    from .classification import Pattern, audit_classification
else:
    from classification import Pattern, audit_classification

CLAUDE_GUARDS = {
    "DOMAIN-SUFFIX,claude-api.com",
    "DOMAIN-SUFFIX,claudecontentmoderation.com",
    "DOMAIN-KEYWORD,anthropic",
    "DOMAIN-KEYWORD,claude",
}


def classical_matches(entries, host):
    host = host.lower().rstrip(".")
    for entry in entries:
        kind, value, *options = entry.split(",")
        if kind in ("IP-CIDR", "IP-CIDR6"):
            continue  # This helper models hostname matching only.
        if kind == "DOMAIN" and host == value:
            return True
        if kind == "DOMAIN-SUFFIX" and (host == value or host.endswith("." + value)):
            return True
        if kind == "DOMAIN-KEYWORD" and value in host:
            return True
        if kind not in ("DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"):
            raise ValueError(f"Unsupported classical domain audit: {kind}")
    return False


def audit_rule_outputs(manifest, artifacts, contract):
    domain_sets, baseline_names, extensions = {}, [], []
    for rule in manifest["rules"]:
        name = rule["name"]
        if rule["behavior"] == "domain" and rule.get("surge", True):
            domain_sets[name] = artifacts[f"Text/{rule.get('output', name)}.list"].decode().splitlines()
        elif rule.get("input_behavior") == "domain" and rule["behavior"] == "classical":
            baseline = artifacts[f"Sources/{name}.txt"].decode().splitlines()
            domain_sets[name] = baseline
            baseline_names.append(name)
            expected = set()
            for entry in baseline:
                p = Pattern.parse(entry)
                if p.suffix and not p.apex:
                    raise ValueError("Subdomain-only pattern needs explicit classical audit support")
                expected.add(("DOMAIN-SUFFIX," if p.suffix else "DOMAIN,") + p.base)
            actual = artifacts[f"Text/{rule.get('output', name)}.list"].decode().splitlines()
            if not expected <= set(actual):
                raise ValueError(f"Classical output lost upstream rules: {name}")
            if name == "claude_domain" and not CLAUDE_GUARDS <= set(actual):
                raise ValueError("Claude classical rules lost required guards")
            samples = []
            if name == "claude_domain":
                for host, wanted in (("claude-api.com", True), ("api.claude-api.com", True),
                                     ("claudecontentmoderation.com", True),
                                     ("thirdparty-claude.example", True), ("anthropic-proxy.example", True),
                                     ("clau.de", True), ("unrelated.example", False)):
                    matched = classical_matches(actual, host)
                    if matched != wanted:
                        raise ValueError(f"Claude classical regression: {host}")
                    samples.append({"domain": host, "matched": matched})
            extensions.append({"name": name, "upstream_domain_entries": len(baseline),
                               "complete_classical_entries": len(actual),
                               "extra_rules": sorted(set(actual) - expected), "samples": samples})
        elif rule["behavior"] == "classical":
            actual = artifacts[f"Text/{rule.get('output', name)}.list"].decode().splitlines()
            baseline = []
            for entry in actual:
                kind, value, *options = entry.split(",")
                if kind in ("DOMAIN", "DOMAIN-SUFFIX"):
                    baseline.append(("+." if kind == "DOMAIN-SUFFIX" else "") + value)
            domain_sets[name] = baseline
            samples = []
            if name == "apple_no_resolve":
                for host in ("www.apple.com", "api.push.apple.com", "probe-testflight.example"):
                    if not classical_matches(actual, host):
                        raise ValueError(f"Apple shared-rule regression: {host}")
                    samples.append({"domain": host, "matched": True})
            extensions.append({"name": name, "domain_baseline_entries": len(baseline),
                               "complete_shared_classical_entries": len(actual),
                               "keyword_entries": sum(e.startswith("DOMAIN-KEYWORD,") for e in actual),
                               "ip_entries": sum(e.startswith(("IP-CIDR,", "IP-CIDR6,")) for e in actual),
                               "samples": samples})
    claude = next(r for r in manifest["rules"] if r["name"] == "claude_domain")
    if claude["behavior"] != "classical" or claude.get("input_behavior") != "domain":
        raise ValueError("Claude must retain merged classical output with a domain upstream")
    report = audit_classification(domain_sets, contract)
    report["scope"] = "domain categories; classical overlap checks use exact/suffix baselines; keyword/IP extensions audited separately"
    report["upstream_only_domain_baselines"] = sorted(baseline_names)
    report["classical_extensions"] = extensions
    return report

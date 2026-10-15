# SPDX-License-Identifier: GPL-3.0-only
"""Public rule-only profiles. Never read a user's full/private client profile."""
import json
import re

CLAUDE_GUARDS = [
    "DOMAIN-SUFFIX,claude-api.com",
    "DOMAIN-SUFFIX,claudecontentmoderation.com",
    "DOMAIN-KEYWORD,anthropic",
    "DOMAIN-KEYWORD,claude",
]


def validate_routing(manifest, routing, contract):
    if set(routing) != {"schema_version", "claude_guards", "clash", "surge"} or routing["schema_version"] != 2:
        raise ValueError("Invalid client routing schema")
    # Explicit user-requested broad matching; never silently remove it during source sync.
    if routing["claude_guards"] != CLAUDE_GUARDS:
        raise ValueError("Claude guard changes require explicit review")
    expected = {r["name"] for r in manifest["rules"] if r.get("surge", True)}
    broad = {"geolocation-!cn", "cn_domain", "cn_ip"}
    for client in ("clash", "surge"):
        settings = routing[client]
        if set(settings) != {"routes", "fallback"}:
            raise ValueError("Rule-only profiles cannot contain nodes or other settings")
        routes = settings["routes"]
        if not all(isinstance(r, list) and len(r) == 2 and all(isinstance(x, str) for x in r)
                   for r in routes):
            raise ValueError("Invalid route")
        names = [r[0] for r in routes]
        if set(names) != expected or len(names) != len(expected):
            raise ValueError("Each client must route every shared set exactly once")
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", p) for _, p in routes):
            raise ValueError("Invalid public policy name")
        if dict(routes)["claude_domain"] != "Claude":
            raise ValueError("Claude guards must route to the Claude policy")
        for first, second in contract["priority_overlaps"] + [["apns", "apple_domain"]]:
            if names.index(first) >= names.index(second):
                raise ValueError(f"{client} routing priority reversed: {first} before {second}")
        for name in expected - broad:
            if any(names.index(name) > names.index(last) for last in broad):
                raise ValueError("Specific sets must precede geographical fallbacks")
        # Explicit fallbacks avoid silently publishing inline/private user rules.
        wanted = (["DST-PORT,80,Final", "DST-PORT,443,Final", "DST-PORT,22,Final", "MATCH,DIRECT"]
                  if client == "clash" else ["RULE-SET,LAN,DIRECT", "FINAL,Proxy,dns-failed"])
        if settings["fallback"] != wanted:
            raise ValueError("Client fallback change requires reviewing the generator")


def build_profiles(manifest, routing, contract):
    validate_routing(manifest, routing, contract)
    base = f"https://raw.githubusercontent.com/{manifest['publish_repository']}/main"
    by_name = {r["name"]: r for r in manifest["rules"]}
    providers = {}
    for name, rule in by_name.items():
        fmt = "yaml" if rule["behavior"] == "classical" else "mrs"
        output = rule.get("output", name)
        providers[name] = {
            "type": "http", "behavior": rule["behavior"], "format": fmt, "interval": 86400,
            "path": f"./providers/proxy-rules/{output}.{fmt}",
            "url": f"{base}/Clash/{output}.{fmt}",
        }
    clash_rules, surge_rules = [], []
    for name, policy in routing["clash"]["routes"]:
        if name == "claude_domain":
            clash_rules.extend(f"{guard},{policy}" for guard in routing["claude_guards"])
        option = ",no-resolve" if by_name[name]["behavior"] == "ipcidr" and name != "cn_ip" else ""
        clash_rules.append(f"RULE-SET,{name},{policy}{option}")
    for name, policy in routing["surge"]["routes"]:
        if name == "claude_domain":
            surge_rules.extend(f"{guard},{policy}" for guard in routing["claude_guards"])
        output = by_name[name].get("output", name)
        surge_rules.append(f"RULE-SET,{base}/Surge/{output}.list,{policy}")
    clash_rules.extend(routing["clash"]["fallback"])
    surge_rules.extend(routing["surge"]["fallback"])
    return {"rule-providers": providers, "rules": clash_rules}, surge_rules


def render_profiles(manifest, routing, contract):
    clash, surge = build_profiles(manifest, routing, contract)
    header = ["# Generated from sources.json and custom/client-routing.json; do not edit outputs.",
              "# RULE-ONLY MERGE FRAGMENT, not a standalone connection profile.",
              "# Keep existing nodes/policy groups, DNS, Wi-Fi exceptions and private local rules.",
              "# Policy names refer to existing groups; no nodes, credentials or SSIDs are published."]
    lines = header + ["rules:"] + ["  - " + json.dumps(rule) for rule in clash["rules"]]
    lines += ["", "# Fake-IP provider is for existing DNS references, not a routing rule.", "rule-providers:"]
    for name, settings in clash["rule-providers"].items():
        lines.append(f"  {json.dumps(name)}:")
        lines += [f"    {key}: {json.dumps(value)}" for key, value in settings.items()]
    return {
        "Profiles/Clash.rules.yaml": ("\n".join(lines) + "\n").encode(),
        "Profiles/Surge.rules.conf": ("\n".join(header + ["[Rule]"] + surge) + "\n").encode(),
    }

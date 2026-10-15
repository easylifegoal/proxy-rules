# SPDX-License-Identifier: GPL-3.0-only
"""Shared business routing with reviewed Wi-Fi and QUIC client differences."""
import json
import re

PRIVATE_TEMPLATES = {"tailscale-direct": "IP-CIDR,{{TAILSCALE_DIRECT_IPV4}}/32,DIRECT,no-resolve"}
TEST_TEMPLATE_VALUES = {"TAILSCALE_DIRECT_IPV4": "192.0.2.1", "HOME_WIFI_SSID": "EXAMPLE-HOME-WIFI",
                        "COMPANY_WIFI_SSID": "EXAMPLE-COMPANY-WIFI"}
SURGE_WIFI = [
    {"id": "home-wifi", "after": "claude_domain", "template": "SUBNET,SSID:{{HOME_WIFI_SSID}},DIRECT"},
    {"id": "company-wifi", "after": "usbank_domain", "template": 'SUBNET,"SSID:{{COMPANY_WIFI_SSID}}",DIRECT'},
]
QUIC_RULE = "AND,((NETWORK,UDP),(DST-PORT,443),(NOT,((OR,((RULE-SET,cn_domain),(RULE-SET,cn_ip)))))),REJECT"
FALLBACK = ["DST-PORT,80,Final", "DST-PORT,443,Final", "DST-PORT,22,Final", "MATCH,DIRECT"]


def published_url(base, rule, client, fmt):
    output = rule.get("output", rule["name"])
    version = "?v=" + rule["cache_tag"] if rule.get("cache_tag") else ""
    return f"{base}/{client}/{output}.{fmt}{version}"


def rule_policy(rule):
    parts = rule.split(",")
    while parts[-1] in ("no-resolve", "dns-failed", "extended-matching"):
        parts.pop()
    return parts[-1]


def validate_routing(manifest, routing, contract):
    if set(routing) != {"schema_version", "policy_groups", "common", "surge_wifi"} or routing["schema_version"] != 6:
        raise ValueError("One common routing source is required")
    if routing["surge_wifi"] != SURGE_WIFI:
        raise ValueError("Only the two reviewed Surge Wi-Fi exceptions are allowed")
    policies = routing["policy_groups"]
    if (not isinstance(policies, list) or len(policies) != len(set(policies))
            or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", p) for p in policies)):
        raise ValueError("Invalid policy group contract")
    allowed = set(policies) | {"DIRECT", "REJECT"}
    settings = routing["common"]
    if set(settings) != {"routes", "fallback", "insertions"}:
        raise ValueError("Rule-only source cannot contain nodes or other settings")
    expected = {r["name"] for r in manifest["rules"] if r.get("surge", True)}
    routes = settings["routes"]
    if not all(isinstance(r, list) and len(r) == 2 and all(isinstance(x, str) for x in r) for r in routes):
        raise ValueError("Invalid route")
    names = [r[0] for r in routes]
    if set(names) != expected or len(names) != len(expected):
        raise ValueError("Route every shared set exactly once")
    if any(p not in allowed for _, p in routes):
        raise ValueError("Rules may target declared policy groups, not individual nodes")
    if dict(routes)["claude_domain"] != "Claude":
        raise ValueError("Claude guards must route to the Claude policy")
    if dict(routes)["meta_domain"] != "Meta":
        raise ValueError("Meta must use its own policy group")
    if any(dict(routes)[name] != policy for name, policy in
           (("apns", "APNS"), ("apple_domain", "Apple"), ("apple_ip", "Apple"))):
        raise ValueError("APNS and Apple must use separate policy groups")
    for first, second in contract["priority_overlaps"] + [["apns", "apple_domain"]]:
        if names.index(first) >= names.index(second):
            raise ValueError(f"Routing priority reversed: {first} before {second}")
    broad = {"geolocation-!cn", "cn_domain", "cn_ip"}
    for name in expected - broad:
        if any(names.index(name) > names.index(last) for last in broad):
            raise ValueError("Specific sets must precede geographical fallbacks")
    if settings["fallback"] != FALLBACK:
        raise ValueError("Common fallback change requires explicit review")
    if "Final" not in allowed:
        raise ValueError("Missing Final policy group")
    if not isinstance(settings["insertions"], list):
        raise ValueError("Invalid insertions")
    anchors, ids, templates = set(), set(), {}
    for insertion in settings["insertions"]:
        if set(insertion) != {"before", "rules"} or insertion["before"] not in expected:
            raise ValueError("Unknown insertion anchor")
        if insertion["before"] in anchors:
            raise ValueError("Duplicate insertion anchor")
        anchors.add(insertion["before"])
        if not isinstance(insertion["rules"], list) or not insertion["rules"]:
            raise ValueError("Empty inline insertion")
        for entry in insertion["rules"]:
            states = set(entry) - {"id", "clients"}
            if len(states) != 1 or not states <= {"rule", "template"}:
                raise ValueError("Inline rule must have exactly one state")
            name = entry.get("id", "")
            if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or name in ids:
                raise ValueError("Duplicate/invalid inline rule id")
            ids.add(name)
            state = next(iter(states))
            value = entry[state]
            if name == "non-cn-quic":
                if state != "rule" or value != QUIC_RULE or entry.get("clients") != ["clash"]:
                    raise ValueError("The reviewed QUIC rule must be Clash-only")
            elif "clients" in entry or value == QUIC_RULE:
                raise ValueError("Only the reviewed QUIC rule may be client-specific")
            if not isinstance(value, str) or any(c in value for c in "\n\r\0"):
                raise ValueError("Invalid inline rule text")
            if rule_policy(value) not in allowed:
                raise ValueError("Inline rules must target declared groups, not nodes")
            if state == "template":
                templates[name] = value
                if PRIVATE_TEMPLATES.get(name) != value:
                    raise ValueError("Private rule must use a reviewed placeholder")
            elif "{{" in value or value.startswith(("IP-CIDR,", "SUBNET,")):
                raise ValueError("Unreviewed private IP/SSID rule")
            elif not (re.fullmatch(r"(?:DOMAIN|DOMAIN-SUFFIX|DOMAIN-KEYWORD),[a-z0-9.-]+,[A-Za-z][A-Za-z0-9_-]*", value)
                      or value == QUIC_RULE):
                raise ValueError("Unreviewed inline rule syntax")
    if templates != PRIVATE_TEMPLATES:
        raise ValueError("Private template rules must not be silently omitted")
    if "non-cn-quic" not in ids:
        raise ValueError("Clash QUIC guard must not be silently omitted")
    cn_ip = next(r for r in manifest["rules"] if r["name"] == "cn_ip")
    if cn_ip.get("surge_no_resolve", True):
        raise ValueError("CN IP DNS semantics must be identical in both clients")


def translate_rule(rule, manifest, client):
    if client == "clash":
        return rule
    if client != "surge":
        raise ValueError("Unknown client")
    by_name = {r["name"]: r for r in manifest["rules"]}
    base = f"https://raw.githubusercontent.com/{manifest['publish_repository']}/main"
    rule = re.sub(r"\bRULE-SET,([A-Za-z0-9_!.-]+)(?=[,)])",
                  lambda m: "RULE-SET," + published_url(base, by_name[m[1]], "Surge", "list"), rule)
    mapping = {"NETWORK": "PROTOCOL", "DST-PORT": "DEST-PORT", "MATCH": "FINAL"}
    return re.sub(r"(?<![A-Za-z0-9_-])(NETWORK|DST-PORT|MATCH),",
                  lambda m: mapping[m[1]] + ",", rule)


def normalize_surge_rule(rule, manifest):
    base = f"https://raw.githubusercontent.com/{manifest['publish_repository']}/main"
    for definition in manifest["rules"]:
        url = published_url(base, definition, "Surge", "list")
        rule = rule.replace("RULE-SET," + url, "RULE-SET," + definition["name"])
    mapping = {"PROTOCOL": "NETWORK", "DEST-PORT": "DST-PORT", "FINAL": "MATCH"}
    return re.sub(r"(?<![A-Za-z0-9_-])(PROTOCOL|DEST-PORT|FINAL),",
                  lambda m: mapping[m[1]] + ",", rule)


def profile_entries(manifest, routing, client):
    by_name = {r["name"]: r for r in manifest["rules"]}
    settings = routing["common"]
    insertions = {i["before"]: i["rules"] for i in settings["insertions"]}
    result = []
    for name, policy in settings["routes"]:
        result.extend(dict(e) for e in insertions.get(name, [])
                      if client in e.get("clients", ["clash", "surge"]))
        option = ",no-resolve" if by_name[name]["behavior"] == "ipcidr" and name != "cn_ip" else ""
        result.append({"id": "set-" + name, "rule": f"RULE-SET,{name},{policy}{option}"})
        if client == "surge":
            result.extend({"id": w["id"], "template": w["template"]} for w in routing["surge_wifi"] if w["after"] == name)
    result.extend({"id": f"fallback-{n}", "rule": r} for n, r in enumerate(settings["fallback"]))
    for entry in result:
        state = "rule" if "rule" in entry else "template"
        entry[state] = translate_rule(entry[state], manifest, client)
    return result


def active_rules(entries, template_values=None):
    result = []
    for entry in entries:
        if "rule" in entry:
            result.append(entry["rule"])
        elif template_values is not None:
            def replace(match):
                value = template_values[match[1]]
                if not isinstance(value, str) or any(c in value for c in '\n\r,{}"'):
                    raise ValueError("Invalid private template value")
                if match[1] == "TAILSCALE_DIRECT_IPV4":
                    import ipaddress
                    ipaddress.IPv4Address(value)
                return value
            result.append(re.sub(r"\{\{([A-Z0-9_]+)\}\}", replace, entry["template"]))
    return result


def required_policies(rules):
    return sorted({rule_policy(r) for r in rules} - {"DIRECT", "REJECT"})


def build_profiles(manifest, routing, contract, template_values=None):
    validate_routing(manifest, routing, contract)
    base = f"https://raw.githubusercontent.com/{manifest['publish_repository']}/main"
    providers = {}
    for rule in manifest["rules"]:
        name, output = rule["name"], rule.get("output", rule["name"])
        fmt = "yaml" if rule["behavior"] == "classical" else "mrs"
        providers[name] = {
            "type": "http", "behavior": rule["behavior"], "format": fmt, "interval": 86400,
            "path": f"./providers/proxy-rules/{output}.{fmt}",
            "url": published_url(base, rule, "Clash", fmt),
        }
    clash = active_rules(profile_entries(manifest, routing, "clash"), template_values)
    surge = active_rules(profile_entries(manifest, routing, "surge"), template_values)
    common_surge = [r for r in surge if not r.startswith("SUBNET,")]
    common_clash = [r for r in clash if r != QUIC_RULE]
    if common_clash != [normalize_surge_rule(r, manifest) for r in common_surge]:
        raise ValueError("Clash/Surge routing parity failed")
    return {"rule-providers": providers, "rules": clash}, surge


def render_profiles(manifest, routing, contract):
    clash, _ = build_profiles(manifest, routing, contract)
    header = [
        "# Generated from one common source: sources.json + custom/client-routing.json.",
        "# UNIFIED ROUTING TEMPLATE, not a standalone connection profile.",
        "# Same business rules/order/groups/fallbacks, with reviewed client differences:",
        "# Clash keeps its non-CN UDP/443 guard; Surge uses native QUIC handling and two Wi-Fi DIRECT rules.",
        "# Fill commented private IP / Wi-Fi placeholders locally, then uncomment those rules.",
        "# No node endpoints/credentials/real SSIDs; disabled ad rules are omitted.",
    ]
    def render_entries(client):
        lines = []
        for entry in profile_entries(manifest, routing, client):
            state = "rule" if "rule" in entry else "template"
            prefix = "  " if client == "clash" else ""
            if state == "template":
                lines.append(prefix + f"# TEMPLATE: {entry['id']}")
            body = "- " + json.dumps(entry[state]) if client == "clash" else entry[state]
            lines.append(prefix + ("# " if state == "template" else "") + body)
        return lines
    lines = header + ["rules:"] + render_entries("clash")
    lines += ["", "# Fake-IP provider is for existing DNS references, not a routing rule.", "rule-providers:"]
    for name, settings in clash["rule-providers"].items():
        lines.append(f"  {json.dumps(name)}:")
        lines += [f"    {key}: {json.dumps(value)}" for key, value in settings.items()]
    return {
        "Profiles/Clash.rules.yaml": ("\n".join(lines) + "\n").encode(),
        "Profiles/Surge.rules.conf": ("\n".join(header + ["[Rule]"] + render_entries("surge")) + "\n").encode(),
    }

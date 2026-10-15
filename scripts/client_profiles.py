# SPDX-License-Identifier: GPL-3.0-only
"""Public rule-only profiles. Never read a user's full/private client profile."""
import json
import re

PRIVATE_TEMPLATES = {
    "clash": {"tailscale-direct": "IP-CIDR,{{TAILSCALE_DIRECT_IPV4}}/32,DIRECT,no-resolve"},
    "surge": {"home-wifi": "SUBNET,SSID:{{HOME_WIFI_SSID}},DIRECT",
              "company-wifi": 'SUBNET,"SSID:{{COMPANY_WIFI_SSID}}",DIRECT'},
}
# Only documentation/test values, never a user's actual private values.
TEST_TEMPLATE_VALUES = {"TAILSCALE_DIRECT_IPV4": "192.0.2.1",
                        "HOME_WIFI_SSID": "EXAMPLE-HOME-WIFI",
                        "COMPANY_WIFI_SSID": "EXAMPLE-COMPANY-WIFI"}


def rule_policy(rule):
    parts = rule.split(",")
    while parts[-1] in ("no-resolve", "dns-failed", "extended-matching"):
        parts.pop()
    return parts[-1]


def validate_insertions(client, settings):
    anchors = {r[0] for r in settings["routes"]}
    used_anchors, ids, templates = set(), set(), {}
    if not isinstance(settings["insertions"], list):
        raise ValueError("Invalid inline rule insertions")
    for insertion in settings["insertions"]:
        if set(insertion) != {"before", "rules"} or insertion["before"] not in anchors:
            raise ValueError("Inline rule insertion has an unknown anchor")
        if insertion["before"] in used_anchors:
            raise ValueError("Duplicate inline insertion anchor")
        used_anchors.add(insertion["before"])
        if not isinstance(insertion["rules"], list) or not insertion["rules"]:
            raise ValueError("Empty inline rule insertion")
        for entry in insertion["rules"]:
            states = set(entry) - {"id"}
            if len(states) != 1 or not states <= {"rule", "template"}:
                raise ValueError("Inline rule must have exactly one state")
            name = entry.get("id", "")
            if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or name in ids:
                raise ValueError("Duplicate/invalid inline rule id")
            ids.add(name)
            state = next(iter(states))
            value = entry[state]
            if not isinstance(value, str) or any(c in value for c in "\n\r\0"):
                raise ValueError("Invalid inline rule text")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", rule_policy(value)):
                raise ValueError("Invalid inline rule policy")
            if state == "template":
                templates[name] = value
                if PRIVATE_TEMPLATES[client].get(name) != value:
                    raise ValueError("Private rule must use a reviewed placeholder")
            elif "{{" in value or value.startswith(("IP-CIDR,", "SUBNET,")):
                raise ValueError("Private IP/SSID rules must remain templated")
            elif not (re.fullmatch(r"(?:DOMAIN|DOMAIN-SUFFIX|DOMAIN-KEYWORD),[a-z0-9.-]+,[A-Za-z][A-Za-z0-9_-]*", value)
                      or value == "AND,((NETWORK,UDP),(DST-PORT,443),(NOT,((OR,((GEOSITE,cn),(GEOIP,CN)))))),REJECT"):
                raise ValueError("Unreviewed inline rule syntax")
    if templates != PRIVATE_TEMPLATES[client]:
        raise ValueError("Private template rules must not be silently omitted")

def published_url(base, rule, client, fmt):
    output = rule.get("output", rule["name"])
    version = "?v=" + rule["cache_tag"] if rule.get("cache_tag") else ""
    return f"{base}/{client}/{output}.{fmt}{version}"


def validate_routing(manifest, routing, contract):
    if set(routing) != {"schema_version", "clash", "surge"} or routing["schema_version"] != 4:
        raise ValueError("Invalid client routing schema")
    expected = {r["name"] for r in manifest["rules"] if r.get("surge", True)}
    broad = {"geolocation-!cn", "cn_domain", "cn_ip"}
    for client in ("clash", "surge"):
        settings = routing[client]
        if set(settings) != {"routes", "fallback", "insertions"}:
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
        validate_insertions(client, settings)
        if client == "surge":
            for insertion in settings["insertions"]:
                if any("template" in r for r in insertion["rules"]):
                    if names.index(insertion["before"]) <= names.index("claude_domain"):
                        raise ValueError("Claude must precede Wi-Fi direct exceptions")
        for first, second in contract["priority_overlaps"] + [["apns", "apple_domain"]]:
            if names.index(first) >= names.index(second):
                raise ValueError(f"{client} routing priority reversed: {first} before {second}")
        for name in expected - broad:
            if any(names.index(name) > names.index(last) for last in broad):
                raise ValueError("Specific sets must precede geographical fallbacks")
        # Fallback semantics remain explicit; private values are only placeholders.
        wanted = (["DST-PORT,80,Final", "DST-PORT,443,Final", "DST-PORT,22,Final", "MATCH,DIRECT"]
                  if client == "clash" else ["RULE-SET,LAN,DIRECT", "FINAL,Proxy,dns-failed"])
        if settings["fallback"] != wanted:
            raise ValueError("Client fallback change requires reviewing the generator")


def profile_entries(manifest, routing, client):
    """Full ordered inventory of enabled rules, including private placeholders."""
    by_name = {r["name"]: r for r in manifest["rules"]}
    base = f"https://raw.githubusercontent.com/{manifest['publish_repository']}/main"
    insertions = {i["before"]: i["rules"] for i in routing[client]["insertions"]}
    result = []
    for name, policy in routing[client]["routes"]:
        result.extend(insertions.get(name, []))
        if client == "clash":
            option = ",no-resolve" if by_name[name]["behavior"] == "ipcidr" and name != "cn_ip" else ""
            rule = f"RULE-SET,{name},{policy}{option}"
        else:
            rule = f"RULE-SET,{published_url(base, by_name[name], 'Surge', 'list')},{policy}"
        result.append({"id": "set-" + name, "rule": rule})
    result.extend({"id": f"fallback-{n}", "rule": r} for n, r in enumerate(routing[client]["fallback"]))
    return result


def active_rules(entries, template_values=None):
    result = []
    for entry in entries:
        if "rule" in entry:
            result.append(entry["rule"])
        elif "template" in entry and template_values is not None:
            def replace(match):
                value = template_values[match[1]]
                if not isinstance(value, str) or any(c in value for c in '\n\r,{}"'):
                    raise ValueError("Invalid private template value")
                return value
            result.append(re.sub(r"\{\{([A-Z0-9_]+)\}\}", replace, entry["template"]))
    return result


def required_policies(rules):
    return sorted({rule_policy(r) for r in rules} - {"DIRECT", "REJECT"})


def build_profiles(manifest, routing, contract, template_values=None):
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
            "url": published_url(base, rule, "Clash", fmt),
        }
    clash_rules = active_rules(profile_entries(manifest, routing, "clash"), template_values)
    surge_rules = active_rules(profile_entries(manifest, routing, "surge"), template_values)
    return {"rule-providers": providers, "rules": clash_rules}, surge_rules


def render_profiles(manifest, routing, contract):
    clash, surge = build_profiles(manifest, routing, contract)
    header = ["# Generated from sources.json and custom/client-routing.json; do not edit outputs.",
              "# COMPLETE ROUTING TEMPLATE, not a standalone connection profile.",
              "# All routing rules/order are retained; keep existing nodes, policy groups and DNS.",
              "# TEMPLATE comments preserve private rules in place: fill values locally and uncomment.",
              "# No endpoints, credentials, private IPs or SSIDs are published; disabled ad rules are omitted."]
    def render_entries(client):
        lines = []
        for entry in profile_entries(manifest, routing, client):
            state = next(key for key in ("rule", "template") if key in entry)
            rule = entry[state]
            prefix = "  " if client == "clash" else ""
            if state != "rule":
                lines.append(prefix + f"# {state.upper()}: {entry['id']}")
            body = "- " + json.dumps(rule) if client == "clash" else rule
            lines.append(prefix + ("# " if state != "rule" else "") + body)
        return lines
    lines = header + ["rules:"] + render_entries("clash")
    lines += ["", "# Fake-IP provider is for existing DNS references, not a routing rule.", "rule-providers:"]
    for name, settings in clash["rule-providers"].items():
        lines.append(f"  {json.dumps(name)}:")
        lines += [f"    {key}: {json.dumps(value)}" for key, value in settings.items()]
    surge_lines = render_entries("surge")
    return {
        "Profiles/Clash.rules.yaml": ("\n".join(lines) + "\n").encode(),
        "Profiles/Surge.rules.conf": ("\n".join(header + ["[Rule]"] + surge_lines) + "\n").encode(),
    }

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Fetch pinned snapshots and build rule files. Python standard library only."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

if __package__:
    from .classification import audit_classification
    from .client_profiles import render_profiles
else:
    from classification import audit_classification
    from client_profiles import render_profiles

ROOT = Path(__file__).resolve().parents[1]
MAX_DOWNLOAD = 20 * 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9_!.-]+\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def fetch(url: str) -> bytes:
    headers = {"User-Agent": "easylifegoal-proxy-rules-sync"}
    # Never send the repository token to raw.githubusercontent.com or upstream files.
    if urlparse(url).hostname == "api.github.com" and os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                data = response.read(MAX_DOWNLOAD + 1)
            if not data or len(data) > MAX_DOWNLOAD:
                raise ValueError(f"Empty or oversized response: {url}")
            return data
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in value:
        raise ValueError(f"Unsafe relative path: {value!r}")
    return value


def validate_manifest(manifest: dict) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported manifest schema")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", manifest["publish_repository"]):
        raise ValueError("Invalid publish repository")
    for upstream in manifest["upstreams"].values():
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", upstream["repository"]):
            raise ValueError("Invalid upstream repository")
    names, outputs = set(), set()
    for rule in manifest["rules"]:
        name = rule["name"]
        if not NAME.fullmatch(name) or name in names:
            raise ValueError(f"Duplicate/invalid rule: {name}")
        names.add(name)
        for output in [rule.get("output", name)] + rule.get("aliases", []):
            if not NAME.fullmatch(output) or output in outputs or output in (".", ".."):
                raise ValueError(f"Duplicate/invalid output: {output}")
            outputs.add(output)
        if rule["behavior"] not in ("domain", "ipcidr", "classical"):
            raise ValueError(f"Unsupported behavior: {name}")
        input_format = rule.get("input_format", "classical" if rule["behavior"] == "classical" else "mrs")
        if input_format not in ("mrs", "classical") or ((input_format == "classical") != (rule["behavior"] == "classical")):
            raise ValueError(f"Input format and behavior do not match: {name}")
        if sum(key in rule for key in ("local", "upstream", "inputs")) != 1:
            raise ValueError(f"Exactly one input required: {name}")
        if "local" in rule:
            safe_relative(rule["local"])
        elif "inputs" in rule:
            if rule["behavior"] != "domain" or not isinstance(rule["inputs"], list) or not rule["inputs"]:
                raise ValueError(f"Composition requires nonempty domain inputs: {name}")
            ids = set()
            for component in rule["inputs"]:
                key = component["id"]
                if not NAME.fullmatch(key) or key in ids or key in (".", ".."):
                    raise ValueError(f"Duplicate/invalid component: {key}")
                ids.add(key)
                if component["upstream"] not in manifest["upstreams"]:
                    raise ValueError(f"Unknown upstream: {key}")
                safe_relative(component["path"])
                if component.get("minimum_entries", 0) < 1:
                    raise ValueError(f"Positive minimum_entries required: {key}")
                if "select" in component:
                    selected = component["select"]
                    if not isinstance(selected, list) or not selected or not all(isinstance(e, str) and "\n" not in e for e in selected):
                        raise ValueError(f"Invalid component selection: {key}")
                    parse_entries("\n".join(selected), "domain")
        else:
            if rule["upstream"] not in manifest["upstreams"]:
                raise ValueError(f"Unknown upstream: {name}")
            safe_relative(rule["path"])
        if rule.get("minimum_entries", 0) < 1:
            raise ValueError(f"Positive minimum_entries required: {name}")


def resolve_upstreams(manifest: dict, pinned: dict | None = None) -> dict:
    result = {}
    for name, source in manifest["upstreams"].items():
        if pinned is None:
            url = (f"https://api.github.com/repos/{source['repository']}/git/ref/heads/"
                   + quote(source["branch"], safe=""))
            sha = json.loads(fetch(url))["object"]["sha"]
        else:
            recorded = pinned[name]
            if recorded["repository"] != source["repository"] or recorded["branch"] != source["branch"]:
                raise ValueError(f"Pinned upstream no longer matches manifest: {name}")
            sha = recorded["sha"]
        if not SHA.fullmatch(sha):
            raise ValueError(f"Invalid upstream commit: {name}")
        result[name] = {**source, "sha": sha}
        print(f"Snapshot {name}: {source['repository']}@{sha}", flush=True)
    return result


def source_url(rule: dict, snapshots: dict) -> str:
    source = snapshots[rule["upstream"]]
    return (f"https://raw.githubusercontent.com/{source['repository']}/{source['sha']}/"
            + quote(rule["path"], safe="/"))


def parse_entries(text: str, behavior: str) -> list[str]:
    if behavior == "classical":
        return parse_classical(text)
    if behavior not in ("domain", "ipcidr"):
        raise ValueError(f"Unsupported behavior: {behavior}")
    entries = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "//")):
            continue
        if behavior == "ipcidr":
            if "/" not in line:
                raise ValueError(f"Expected CIDR: {line!r}")
            line = str(ipaddress.ip_network(line, strict=True))
        else:
            line = line.lower()
            # Preserve existing DNS names such as ShellCrash's "Mijia Cloud";
            # Mihomo accepts embedded spaces, but not control characters.
            if any(ord(char) < 32 for char in line) or any(c in line for c in ",/#?[]()\\<>"):
                raise ValueError(f"Invalid domain pattern: {line!r}")
            labels = line.split(".")
            if line.endswith(".") or any(not label for label in labels[1:]):
                raise ValueError(f"Invalid domain labels: {line!r}")
            for index, label in enumerate(labels):
                if "+" in label and not (index == 0 and label == "+" and len(labels) > 1):
                    raise ValueError(f"Invalid suffix wildcard: {line!r}")
                if "*" in label and label != "*":
                    raise ValueError(f"Invalid label wildcard: {line!r}")
        entries.add(line)
    if not entries:
        raise ValueError("Empty rule set")
    return sorted(entries)


def parse_classical(text: str) -> list[str]:
    """A deliberately small shared subset; unknown types/options fail closed."""
    entries = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "//")):
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2 or not parts[1]:
            raise ValueError(f"Invalid classical rule: {line!r}")
        kind, value, *options = parts
        if kind in ("DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"):
            if options or any(c.isspace() for c in value):
                raise ValueError(f"Unexpected classical domain options: {line!r}")
            value = parse_entries(value, "domain")[0]
            if value.startswith((".", "+")) or "*" in value:
                raise ValueError(f"Unsupported classical domain pattern: {line!r}")
        elif kind in ("IP-CIDR", "IP-CIDR6"):
            if options not in ([], ["no-resolve"]):
                raise ValueError(f"Unexpected classical IP options: {line!r}")
            value = parse_entries(value, "ipcidr")[0]
            if ipaddress.ip_network(value).version != (4 if kind == "IP-CIDR" else 6):
                raise ValueError(f"Classical IP family mismatch: {line!r}")
        else:
            # Do not silently drop USER-AGENT, ASN, logical rules, actions, etc.
            raise ValueError(f"Unsupported classical rule type: {kind!r}")
        entries.add(",".join([kind, value, *options]))
    if not entries:
        raise ValueError("Empty rule set")
    return sorted(entries)


def convert(mihomo: Path, behavior: str, fmt: str, source: Path, target: Path) -> None:
    completed = subprocess.run(
        [str(mihomo), "convert-ruleset", behavior, fmt, str(source), str(target)],
        capture_output=True, text=True, timeout=90,
    )
    if completed.returncode or not target.exists() or not target.stat().st_size:
        raise ValueError(f"Mihomo conversion failed for {source.name}: "
                         f"{completed.stderr[-1200:]} {completed.stdout[-1200:]}")


def check_count(name: str, count: int, minimum: int, previous: int | None,
                allow_large_change: bool = False) -> None:
    if count < minimum:
        raise ValueError(f"{name}: {count} entries below minimum {minimum}")
    if previous and not allow_large_change and (count < previous * .8 or count > previous * 2):
        raise ValueError(f"{name}: suspicious count change {previous} -> {count}; "
                         "review upstream before allowing a large change")


def apply_overrides(entries: list[str], override: dict, behavior: str) -> list[str]:
    if set(override) - {"add", "remove"}:
        raise ValueError("Overrides only support add/remove")
    additions, removals = set(), set()
    for key, target in (("add", additions), ("remove", removals)):
        values = override.get(key, [])
        if not isinstance(values, list) or not all(isinstance(v, str) and "\n" not in v for v in values):
            raise ValueError(f"Invalid override {key}")
        if values:
            target.update(parse_entries("\n".join(values), behavior))
    if additions & removals:
        raise ValueError("The same entry cannot be both added and removed")
    missing = removals - set(entries)
    if missing:
        raise ValueError(f"Removal not in upstream (exact-entry removal only): {sorted(missing)[:5]}")
    result = sorted((set(entries) - removals) | additions)
    if not result:
        raise ValueError("Overrides emptied rule set")
    return result


def surge_rules(entries: list[str], behavior: str) -> list[str]:
    if behavior == "classical":
        return parse_classical("\n".join(entries))
    result = set()
    for entry in entries:
        if behavior == "ipcidr":
            network = ipaddress.ip_network(entry)
            kind = "IP-CIDR" if network.version == 4 else "IP-CIDR6"
            result.add(f"{kind},{network},no-resolve")
            continue
        if "*" in entry or any(char.isspace() for char in entry):
            # Mihomo '*' matches ONE label; Surge '*' crosses dots. Never widen silently.
            raise ValueError(f"Cannot faithfully export Mihomo single-label wildcard to Surge: {entry}")
        if entry.startswith("+."):
            result.add("DOMAIN-SUFFIX," + entry[2:])
        elif entry.startswith("."):
            # In Mihomo a leading dot excludes the apex; Surge DOMAIN-SUFFIX includes it.
            result.add("DOMAIN-WILDCARD,*" + entry)
        else:
            result.add("DOMAIN," + entry)
    return sorted(result)


def yaml_payload(entries: list[str], header: str) -> bytes:
    return (header + "payload:\n" + "".join("  - " + json.dumps(e, ensure_ascii=False) + "\n" for e in entries)).encode()


def provider_format(rule: dict, preferred: str) -> tuple[str, str]:
    # MRS cannot encode keywords. Never publish a partial APNS .mrs file.
    fmt = "yaml" if rule["behavior"] == "classical" else preferred
    behavior = "classical" if fmt == "yaml" and rule.get("classical_yaml") else rule["behavior"]
    return behavior, fmt


def render_examples(manifest: dict, contract: dict | None = None) -> dict[str, bytes]:
    base = f"https://raw.githubusercontent.com/{manifest['publish_repository']}/main"
    result = {}
    for fmt in ("mrs", "yaml"):
        lines = ["# Provider-only fragment. Keep your existing rules, policies and DNS settings.",
                 "# Classical sets (APNS) use YAML even in the MRS-preferred example.", "rule-providers:"]
        for rule in manifest["rules"]:
            out = rule.get("output", rule["name"])
            behavior, actual_format = provider_format(rule, fmt)
            lines.extend([
                f"  {json.dumps(rule['name'])}:", "    type: http", f"    behavior: {behavior}",
                f"    format: {actual_format}", "    interval: 86400",
                f"    path: ./ruleset/{out}.{actual_format}", f"    url: {base}/Clash/{out}.{actual_format}",
            ])
        result[f"examples/rule-providers-{fmt}.yaml"] = ("\n".join(lines) + "\n").encode()
    lines = ["# Reference only: replace POLICY with your actual policy; order is NOT prescribed.",
             "# Fake-IP is a Mihomo DNS exclusion set, not a Surge routing rule.", "[Rule]"]
    for rule in manifest["rules"]:
        if rule.get("surge", True):
            out = rule.get("output", rule["name"])
            lines.append(f"RULE-SET,{base}/Surge/{out}.list,POLICY")
    result["examples/surge-rules.conf"] = ("\n".join(lines) + "\n").encode()
    if contract:
        by_name = {r["name"]: r for r in manifest["rules"]}
        header = ["# Business-domain ordering fragment ONLY; not a complete profile.",
                  "# Replace POLICY_* with existing client policies. Do not overwrite your rules.",
                  "# Preserve Wi-Fi, local exceptions, APNS (before Apple), service IP rules and fallback."]
        clash, surge = header + ["rules:"], header + ["[Rule]"]
        for name in contract["domain_priority"]:
            output = by_name[name].get("output", name)
            clash.append("  - " + json.dumps(f"RULE-SET,{name},POLICY_{name}"))
            surge.append(f"RULE-SET,{base}/Surge/{output}.list,POLICY_{name}")
        result["examples/business-rules-clash.yaml"] = ("\n".join(clash) + "\n").encode()
        result["examples/business-rules-surge.conf"] = ("\n".join(surge) + "\n").encode()
    return result


def build_rule(rule: dict, data: bytes | dict[str, bytes] | None, snapshots: dict, overrides: dict,
               old: dict, mihomo: Path, root: Path, allow_large_change: bool) -> tuple[dict, dict]:
    name, behavior = rule["name"], rule["behavior"]
    artifacts, components = {}, {}
    with tempfile.TemporaryDirectory(prefix="proxy-rule-") as directory:
        work = Path(directory)
        if "inputs" in rule:
            if not isinstance(data, dict) or set(data) != {c["id"] for c in rule["inputs"]}:
                raise ValueError(f"Missing/extra composition inputs: {name}")
            merged = set()
            for component in rule["inputs"]:
                key = component["id"]
                incoming, decoded = work / f"{key}.mrs", work / f"{key}.txt"
                incoming.write_bytes(data[key])
                convert(mihomo, behavior, "mrs", incoming, decoded)
                original = parse_entries(decoded.read_text(), behavior)
                previous_component = old.get("components", {}).get(key, {})
                check_count(f"{name}/{key}", len(original), component["minimum_entries"],
                            previous_component.get("upstream_entries"), allow_large_change)
                selected = parse_entries("\n".join(component["select"]), behavior) if "select" in component else original
                missing = set(selected) - set(original)
                if missing:
                    raise ValueError(f"{name}/{key}: selected entries absent upstream: {sorted(missing)}")
                merged.update(selected)
                artifacts[f"Sources/{name}/{key}.mrs"] = data[key]
                artifacts[f"Sources/{name}/{key}.txt"] = ("\n".join(original) + "\n").encode()
                components[key] = {"source": source_url(component, snapshots),
                                   "upstream_sha256": digest(data[key]), "upstream_entries": len(original),
                                   "selected_entries": len(selected), "selection": component.get("select", "all")}
            entries = sorted(merged)
            origin = "sources.json:rules/" + name + "/inputs"
            # Stable digest of all component bytes; full provenance is recorded separately.
            input_hash = digest(json_bytes({k: digest(v) for k, v in sorted(data.items())}))
        elif data is not None:
            if behavior == "classical":
                entries = parse_classical(data.decode("utf-8-sig"))
                artifacts[f"Sources/{name}.list"] = data
            else:
                incoming, decoded = work / "upstream.mrs", work / "upstream.txt"
                incoming.write_bytes(data)
                convert(mihomo, behavior, "mrs", incoming, decoded)
                entries = parse_entries(decoded.read_text(), behavior)
                artifacts[f"Sources/{name}.mrs"] = data
            origin = source_url(rule, snapshots)
            input_hash = digest(data)
        else:
            source = root / rule["local"]
            entries = parse_entries(source.read_text(), behavior)
            origin = rule["local"]
            input_hash = digest(source.read_bytes())
        check_count(name, len(entries), rule["minimum_entries"], old.get("upstream_entries"), allow_large_change)
        upstream_entries = entries
        artifacts[f"Sources/{name}.txt"] = ("\n".join(entries) + "\n").encode()
        entries = apply_overrides(entries, overrides.get(name, {}), behavior)
        if behavior == "classical":
            check_count(name + " output", len(entries), rule["minimum_entries"], old.get("output_entries"), allow_large_change)
            heading = f"# Generated {name}; edit sources.json/custom, not this file.\n# Provenance and license: ../metadata/sync-state.json, ../NOTICE.md\n"
            plain = ("\n".join(entries) + "\n").encode()
            for output in [rule.get("output", name)] + rule.get("aliases", []):
                artifacts[f"Clash/{output}.yaml"] = yaml_payload(entries, heading)
                artifacts[f"Text/{output}.list"] = plain
                if rule.get("surge", True):
                    artifacts[f"Surge/{output}.list"] = heading.encode() + plain
            record = {
                "source": origin, "behavior": behavior,
                "upstream_entries": len(upstream_entries), "output_entries": len(entries),
                "upstream_sha256": input_hash,
                "mrs_sha256": None, "upstream_mrs_preserved": False,
                "surge_exported": rule.get("surge", True),
            }
            print(f"{name}: {len(upstream_entries)} source -> {len(entries)} classical entries; YAML/Surge only", flush=True)
            return artifacts, record
        initial = work / "canonical.txt"
        initial.write_text("\n".join(entries) + "\n")
        compiled, decoded = work / "final.mrs", work / "final.txt"
        convert(mihomo, behavior, "text", initial, compiled)
        convert(mihomo, behavior, "mrs", compiled, decoded)
        canonical = parse_entries(decoded.read_text(), behavior)
        # The converter may combine redundant suffix/IP entries; validate the resulting count too.
        check_count(name + " output", len(canonical), rule["minimum_entries"], old.get("output_entries"), allow_large_change)
        # A second compile/decode must be stable: detects malformed or lossy round trips.
        second, second_text = work / "second.mrs", work / "second.txt"
        convert(mihomo, behavior, "text", decoded, second)
        convert(mihomo, behavior, "mrs", second, second_text)
        if canonical != parse_entries(second_text.read_text(), behavior):
            raise ValueError(f"Unstable MRS round trip: {name}")
        unchanged = isinstance(data, bytes) and entries == upstream_entries
        mrs = data if unchanged else compiled.read_bytes()
        plain = ("\n".join(canonical) + "\n").encode()
        heading = f"# Generated {name}; edit sources.json/custom, not this file.\n# Provenance and license: ../metadata/sync-state.json, ../NOTICE.md\n"
        surge = surge_rules(canonical, behavior) if rule.get("surge", True) or rule.get("classical_yaml") else None
        yaml_entries = surge if rule.get("classical_yaml") else canonical
        yaml = yaml_payload(yaml_entries, heading)
        for output in [rule.get("output", name)] + rule.get("aliases", []):
            artifacts[f"Clash/{output}.mrs"] = mrs
            artifacts[f"Clash/{output}.yaml"] = yaml
            artifacts[f"Text/{output}.list"] = plain
            if rule.get("surge", True):
                artifacts[f"Surge/{output}.list"] = (heading + "\n".join(surge) + "\n").encode()
        record = {
            "source": origin, "behavior": behavior,
            "upstream_entries": len(upstream_entries), "output_entries": len(canonical),
            "upstream_sha256": input_hash,
            "mrs_sha256": digest(mrs), "upstream_mrs_preserved": unchanged,
            "surge_exported": rule.get("surge", True),
        }
        if components:
            record["components"] = components
        print(f"{name}: {len(upstream_entries)} source -> {len(canonical)} output entries; "
              f"MRS {'unchanged' if unchanged else 'compiled'}", flush=True)
        return artifacts, record


def publish(root: Path, artifacts: dict[str, bytes], state: dict, check: bool) -> bool:
    changed = [path for path, data in artifacts.items()
               if not (root / path).is_file() or (root / path).read_bytes() != data]
    # Prune only obsolete generated files recorded in our previous state, never arbitrary files.
    previous_path = root / "metadata/sync-state.json"
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    stale = []
    for path, expected_hash in previous.get("output_sha256", {}).items():
        if path in artifacts:
            continue
        target = root / safe_relative(path)
        if not target.exists():
            continue
        if (PurePosixPath(path).parts[0] not in {"Clash", "Surge", "Sources", "Text", "examples", "metadata", "Profiles"}
                or target.is_symlink() or not target.resolve().is_relative_to(root.resolve())
                or not target.is_file() or digest(target.read_bytes()) != expected_hash):
            raise ValueError(f"Refusing to remove modified/unsafe obsolete output: {path}")
        stale.append(path)
    # Record the last PUBLISHED source version. A daily upstream rebuild alone must not make a commit.
    if changed or stale or not (root / "metadata/sync-state.json").exists():
        artifacts = {**artifacts, "metadata/sync-state.json": json_bytes(state)}
    if check:
        if changed or stale:
            raise ValueError("Generated files differ: " + ", ".join(changed + stale))
        print("All generated files match the pinned inputs")
        return False
    # No tracked output is touched until every download/conversion/validation has succeeded.
    for relative, data in artifacts.items():
        target = root / safe_relative(relative)
        if target.is_file() and target.read_bytes() == data:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
            temporary.write(data)
            temp_path = Path(temporary.name)
        temp_path.chmod(0o644)
        temp_path.replace(target)
    for path in stale:
        (root / path).unlink()
        print(f"Removed obsolete generated file (recoverable in Git): {path}")
    print(f"Generated content changed in {len(changed)} files")
    return bool(changed or stale)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mihomo", type=Path, default=ROOT / ".tools/mihomo")
    parser.add_argument("--pinned", action="store_true", help="Reproduce the last published upstream commits")
    parser.add_argument("--check", action="store_true", help="Validate without writing generated files")
    parser.add_argument("--allow-large-change", action="store_true", help="Reviewed count changes only; minimums still enforced")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "sources.json").read_text())
    validate_manifest(manifest)
    overrides = json.loads((ROOT / "custom/overrides.json").read_text())
    unknown = set(overrides) - {r["name"] for r in manifest["rules"]}
    if unknown:
        raise ValueError(f"Overrides name unknown rules: {unknown}")
    state_path = ROOT / "metadata/sync-state.json"
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    if args.pinned and not previous:
        raise ValueError("No published state to pin")
    snapshots = resolve_upstreams(manifest, previous["upstreams"] if args.pinned else None)
    mihomo = args.mihomo.resolve(strict=True)
    version = subprocess.check_output([str(mihomo), "-v"], text=True, timeout=10).splitlines()[0]
    if "v1.19.32 " not in version:
        raise ValueError("Use the pinned Mihomo v1.19.32 for reproducible output")
    remote_rules = [source for r in manifest["rules"] for source in
                    ([r] if "upstream" in r else r.get("inputs", []))]
    urls = sorted({source_url(r, snapshots) for r in remote_rules})
    with ThreadPoolExecutor(max_workers=4) as pool:
        blobs = dict(zip(urls, pool.map(fetch, urls)))
    artifacts, records = {}, {}
    for rule in manifest["rules"]:
        data = ({c["id"]: blobs[source_url(c, snapshots)] for c in rule["inputs"]} if "inputs" in rule else
                blobs[source_url(rule, snapshots)] if "upstream" in rule else None)
        outputs, record = build_rule(rule, data, snapshots, overrides,
                                     previous.get("rules", {}).get(rule["name"], {}),
                                     mihomo, ROOT, args.allow_large_change)
        artifacts.update(outputs)
        records[rule["name"]] = record
    contract = json.loads((ROOT / "custom/classification.json").read_text())
    domain_sets = {r["name"]: artifacts[f"Text/{r.get('output', r['name'])}.list"].decode().splitlines()
                   for r in manifest["rules"] if r["behavior"] == "domain" and r.get("surge", True)}
    artifacts["metadata/classification-audit.json"] = json_bytes(audit_classification(domain_sets, contract))
    artifacts.update(render_examples(manifest, contract))
    routing = json.loads((ROOT / "custom/client-routing.json").read_text())
    artifacts.update(render_profiles(manifest, routing, contract))
    state = {"schema_version": 1, "converter": "mihomo v1.19.32", "upstreams": snapshots, "rules": records,
             "output_sha256": {path: digest(data) for path, data in sorted(artifacts.items())}}
    changed = publish(ROOT, artifacts, state, args.check)
    summary = ["## Rule synchronization", f"Validated {len(records)} rule sets. Changed: {changed}.",
               "", "| Rule | Source entries | Output entries |", "|---|---:|---:|"]
    summary += [f"| {name} | {r['upstream_entries']} | {r['output_entries']} |" for name, r in records.items()]
    for name, snapshot in snapshots.items():
        summary.append(f"\n{name}: `{snapshot['repository']}@{snapshot['sha']}`")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write("\n".join(summary) + "\n")


if __name__ == "__main__":
    main()

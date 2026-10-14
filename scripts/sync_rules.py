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
        if rule["behavior"] not in ("domain", "ipcidr"):
            raise ValueError(f"Unsupported behavior: {name}")
        if ("local" in rule) == ("upstream" in rule):
            raise ValueError(f"Exactly one input required: {name}")
        if "local" in rule:
            safe_relative(rule["local"])
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


def render_examples(manifest: dict) -> dict[str, bytes]:
    base = f"https://raw.githubusercontent.com/{manifest['publish_repository']}/main"
    result = {}
    for fmt in ("mrs", "yaml"):
        lines = ["# Provider-only fragment. Keep your existing rules, policies and DNS settings.", "rule-providers:"]
        for rule in manifest["rules"]:
            out = rule.get("output", rule["name"])
            behavior = "classical" if fmt == "yaml" and rule.get("classical_yaml") else rule["behavior"]
            lines.extend([
                f"  {json.dumps(rule['name'])}:", "    type: http", f"    behavior: {behavior}",
                f"    format: {fmt}", "    interval: 86400",
                f"    path: ./ruleset/{out}.{fmt}", f"    url: {base}/Clash/{out}.{fmt}",
            ])
        result[f"examples/rule-providers-{fmt}.yaml"] = ("\n".join(lines) + "\n").encode()
    lines = ["# Reference only: replace POLICY with your actual policy; order is NOT prescribed.",
             "# Fake-IP is a Mihomo DNS exclusion set, not a Surge routing rule.", "[Rule]"]
    for rule in manifest["rules"]:
        if rule.get("surge", True):
            out = rule.get("output", rule["name"])
            lines.append(f"RULE-SET,{base}/Surge/{out}.list,POLICY")
    result["examples/surge-rules.conf"] = ("\n".join(lines) + "\n").encode()
    return result


def build_rule(rule: dict, data: bytes | None, snapshots: dict, overrides: dict,
               old: dict, mihomo: Path, root: Path, allow_large_change: bool) -> tuple[dict, dict]:
    name, behavior = rule["name"], rule["behavior"]
    artifacts = {}
    with tempfile.TemporaryDirectory(prefix="proxy-rule-") as directory:
        work = Path(directory)
        if data is not None:
            incoming, decoded = work / "upstream.mrs", work / "upstream.txt"
            incoming.write_bytes(data)
            convert(mihomo, behavior, "mrs", incoming, decoded)
            entries = parse_entries(decoded.read_text(), behavior)
            origin = source_url(rule, snapshots)
            artifacts[f"Sources/{name}.mrs"] = data
        else:
            source = root / rule["local"]
            entries = parse_entries(source.read_text(), behavior)
            origin = rule["local"]
        check_count(name, len(entries), rule["minimum_entries"], old.get("upstream_entries"), allow_large_change)
        upstream_entries = entries
        artifacts[f"Sources/{name}.txt"] = ("\n".join(entries) + "\n").encode()
        entries = apply_overrides(entries, overrides.get(name, {}), behavior)
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
        unchanged = data is not None and entries == upstream_entries
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
            "upstream_sha256": digest(data) if data is not None else digest((root / rule['local']).read_bytes()),
            "mrs_sha256": digest(mrs), "upstream_mrs_preserved": unchanged,
            "surge_exported": rule.get("surge", True),
        }
        print(f"{name}: {len(upstream_entries)} source -> {len(canonical)} output entries; "
              f"MRS {'unchanged' if unchanged else 'compiled'}", flush=True)
        return artifacts, record


def publish(root: Path, artifacts: dict[str, bytes], state: dict, check: bool) -> bool:
    changed = [path for path, data in artifacts.items()
               if not (root / path).is_file() or (root / path).read_bytes() != data]
    # Record the last PUBLISHED source version. A daily upstream rebuild alone must not make a commit.
    if changed or not (root / "metadata/sync-state.json").exists():
        artifacts = {**artifacts, "metadata/sync-state.json": json_bytes(state)}
    if check:
        if changed:
            raise ValueError("Generated files differ: " + ", ".join(changed))
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
    print(f"Generated content changed in {len(changed)} files")
    return bool(changed)


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
    remote_rules = [r for r in manifest["rules"] if "upstream" in r]
    with ThreadPoolExecutor(max_workers=4) as pool:
        blobs = dict(zip((r["name"] for r in remote_rules), pool.map(lambda r: fetch(source_url(r, snapshots)), remote_rules)))
    artifacts, records = {}, {}
    for rule in manifest["rules"]:
        outputs, record = build_rule(rule, blobs.get(rule["name"]), snapshots, overrides,
                                     previous.get("rules", {}).get(rule["name"], {}),
                                     mihomo, ROOT, args.allow_large_change)
        artifacts.update(outputs)
        records[rule["name"]] = record
    artifacts.update(render_examples(manifest))
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

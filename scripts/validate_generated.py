#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Validate published hashes and load all YAML/MRS providers with the real core."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from sync_rules import audit_classification, parse_entries, provider_format, surge_rules

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surge-cli", type=Path, help="Optional local Surge offline profile checker")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "sources.json").read_text())
    state = json.loads((ROOT / "metadata/sync-state.json").read_text())
    for relative, expected in state["output_sha256"].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Published hash mismatch: {relative}")
    domain_sets = {r["name"]: (ROOT / "Text" / (r.get("output", r["name"]) + ".list")).read_text().splitlines()
                   for r in manifest["rules"] if r["behavior"] == "domain" and r.get("surge", True)}
    audit = audit_classification(domain_sets, json.loads((ROOT / "custom/classification.json").read_text()))
    if audit != json.loads((ROOT / "metadata/classification-audit.json").read_text()):
        raise ValueError("Recorded classification audit is stale")
    print(f"Validated category boundaries and {len(audit['samples'])} domain routing examples")
    # Independently compare Surge and classical YAML with the canonical Text sets.
    for rule in manifest["rules"]:
        output = rule.get("output", rule["name"])
        entries = parse_entries((ROOT / "Text" / f"{output}.list").read_text(), rule["behavior"])
        expected = surge_rules(entries, rule["behavior"]) if rule.get("surge", True) or rule.get("classical_yaml") else None
        if rule.get("surge", True):
            actual = sorted(line for line in (ROOT / "Surge" / f"{output}.list").read_text().splitlines()
                            if line and not line.startswith("#"))
            if actual != expected:
                raise ValueError(f"Surge and canonical matching entries differ: {output}")
        if rule["behavior"] == "classical" or rule.get("classical_yaml"):
            actual = sorted(json.loads(line[4:]) for line in (ROOT / "Clash" / f"{output}.yaml").read_text().splitlines()
                            if line.startswith("  - "))
            if actual != (expected if expected is not None else entries):
                raise ValueError(f"Classical YAML and canonical entries differ: {output}")
    binary = ROOT / ".tools/mihomo"
    with tempfile.TemporaryDirectory(prefix="validate-", dir=ROOT / ".tools") as directory:
        for fmt in ("mrs", "yaml"):
            providers, rules = {}, []
            for rule in manifest["rules"]:
                name = rule["name"]
                output = rule.get("output", name)
                behavior, actual_format = provider_format(rule, fmt)
                providers[name] = {
                    "type": "file", "behavior": behavior, "format": actual_format,
                    "path": str(ROOT / "Clash" / f"{output}.{actual_format}"),
                }
                rules.append(f"RULE-SET,{name},DIRECT")
            config = {
                "mode": "rule", "log-level": "info",
                "rule-providers": providers, "rules": rules + ["MATCH,DIRECT"],
            }
            path = Path(directory) / f"{fmt}.json"
            path.write_text(json.dumps(config))
            result = subprocess.run([str(binary), "-t", "-d", str(ROOT), "-f", str(path)],
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise ValueError(f"Mihomo {fmt} validation failed:\n{result.stdout}\n{result.stderr}")
            # Independently verify each non-classical YAML round trip, not just config syntax.
            for rule in manifest["rules"]:
                if fmt != "yaml" or rule.get("classical_yaml") or rule["behavior"] == "classical":
                    continue
                output = rule.get("output", rule["name"])
                compiled = Path(directory) / "check.mrs"
                decoded = Path(directory) / "check.txt"
                for form, source, target in (("yaml", ROOT / "Clash" / f"{output}.yaml", compiled),
                                              ("mrs", compiled, decoded)):
                    subprocess.run([str(binary), "convert-ruleset", rule["behavior"], form,
                                    str(source), str(target)], check=True, capture_output=True, timeout=90)
                actual = set(decoded.read_text().splitlines())
                expected = set((ROOT / "Text" / f"{output}.list").read_text().splitlines())
                if actual != expected:
                    raise ValueError(f"YAML and MRS matching entries differ: {output}")
            print(f"Validated {len(providers)} {fmt}-preferred providers (classical uses YAML) with Mihomo v1.19.32")
        if args.surge_cli:
            lines = ["[General]", "loglevel = warning", "[Rule]"]
            for rule in manifest["rules"]:
                if rule.get("surge", True):
                    output = rule.get("output", rule["name"])
                    lines.append(f"RULE-SET,{ROOT / 'Surge' / (output + '.list')},DIRECT")
            lines.append("FINAL,DIRECT")
            profile = Path(directory) / "surge-validation.conf"
            profile.write_text("\n".join(lines) + "\n")
            result = subprocess.run([str(args.surge_cli), "--check", str(profile)],
                                    capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise ValueError(f"Surge profile validation failed:\n{result.stdout}\n{result.stderr}")
            print("Surge offline profile check: " + (result.stdout + result.stderr).strip())
    print("All recorded output hashes and YAML/MRS/Surge entry sets agree")


if __name__ == "__main__":
    main()

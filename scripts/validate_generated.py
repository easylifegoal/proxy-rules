#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Validate published hashes and load all YAML/MRS providers with the real core."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "sources.json").read_text())
    state = json.loads((ROOT / "metadata/sync-state.json").read_text())
    for relative, expected in state["output_sha256"].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Published hash mismatch: {relative}")
    binary = ROOT / ".tools/mihomo"
    with tempfile.TemporaryDirectory(prefix="validate-", dir=ROOT / ".tools") as directory:
        for fmt in ("mrs", "yaml"):
            providers, rules = {}, []
            for rule in manifest["rules"]:
                name = rule["name"]
                output = rule.get("output", name)
                behavior = "classical" if fmt == "yaml" and rule.get("classical_yaml") else rule["behavior"]
                providers[name] = {
                    "type": "file", "behavior": behavior, "format": fmt,
                    "path": str(ROOT / "Clash" / f"{output}.{fmt}"),
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
                if fmt != "yaml" or rule.get("classical_yaml"):
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
            print(f"Validated {len(providers)} {fmt} providers with Mihomo v1.19.32")
    print("All recorded output hashes and YAML/MRS entry sets agree")


if __name__ == "__main__":
    main()

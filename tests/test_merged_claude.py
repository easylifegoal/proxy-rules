# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sync_rules as sync
from scripts.rule_audit import CLAUDE_GUARDS, audit_rule_outputs, classical_matches


class MergedClaudeTests(unittest.TestCase):
    def setUp(self):
        self.rule = {"name": "claude_domain", "behavior": "classical", "input_behavior": "domain",
                     "input_format": "mrs", "upstream": "test", "path": "anthropic.mrs", "minimum_entries": 1}
        self.snapshots = {"test": {"repository": "test/repo", "sha": "a" * 40}}
        self.domains = "+.anthropic.com\n+.clau.de\n+.claude.ai\n"
        self.overrides = {"claude_domain": {"add": sorted(CLAUDE_GUARDS)}}

    def build(self, domains=None, overrides=None):
        def decode(binary, behavior, fmt, source, target):
            self.assertEqual((behavior, fmt), ("domain", "mrs"))
            target.write_text(domains or self.domains)
        with patch.object(sync, "convert", side_effect=decode):
            return sync.build_rule(self.rule, b"original-mrs", self.snapshots,
                                   overrides if overrides is not None else self.overrides,
                                   {}, Path("/unused"), sync.ROOT, False)

    def test_merge_preserves_source_and_has_no_partial_mrs(self):
        outputs, record = self.build()
        self.assertEqual(outputs["Sources/claude_domain.mrs"], b"original-mrs")
        self.assertEqual(outputs["Sources/claude_domain.txt"].decode(), self.domains)
        self.assertNotIn("Clash/claude_domain.mrs", outputs)
        entries = set(outputs["Text/claude_domain.list"].decode().splitlines())
        self.assertTrue(CLAUDE_GUARDS <= entries)
        self.assertIn("DOMAIN-SUFFIX,clau.de", entries)
        self.assertEqual(len(entries), 7)
        self.assertEqual(record["upstream_entries"], 3)
        self.assertEqual(record["input_behavior"], "domain")
        yaml_entries = {json.loads(l[4:]) for l in outputs["Clash/claude_domain.yaml"].decode().splitlines() if l.startswith("  - ")}
        surge_entries = {l for l in outputs["Surge/claude_domain.list"].decode().splitlines() if l and not l.startswith("#")}
        self.assertEqual(entries, yaml_entries)
        self.assertEqual(entries, surge_entries)
        self.assertTrue(all(not l.endswith(",Claude") for l in entries))

    def test_future_upstream_update_keeps_all_guards(self):
        outputs, _ = self.build(self.domains + "+.new-service.example\n")
        entries = set(outputs["Text/claude_domain.list"].decode().splitlines())
        self.assertTrue(CLAUDE_GUARDS <= entries)
        self.assertIn("DOMAIN-SUFFIX,new-service.example", entries)

    def audit(self, outputs):
        manifest = {"rules": [self.rule, {"name": "ai", "behavior": "domain"}]}
        artifacts = {**outputs, "Text/ai.list": self.domains.encode()}
        contract = {"schema_version": 1, "domain_priority": ["claude_domain", "ai"],
                    "subsets": [["claude_domain", "ai"]]}
        return audit_rule_outputs(manifest, artifacts, contract)

    def test_baseline_subset_is_distinguished_from_complete_classical_set(self):
        report = self.audit(self.build()[0])
        self.assertEqual(report["upstream_only_domain_baselines"], ["claude_domain"])
        self.assertEqual(report["subsets"][0]["checked_entries"], 3)
        self.assertEqual(report["classical_extensions"][0]["complete_classical_entries"], 7)
        self.assertEqual(len(report["classical_extensions"][0]["samples"]), 7)

    def test_missing_any_guard_blocks_publication(self):
        for guard in CLAUDE_GUARDS:
            outputs, _ = self.build(overrides={"claude_domain": {"add": sorted(CLAUDE_GUARDS - {guard})}})
            with self.subTest(guard=guard), self.assertRaisesRegex(ValueError, "lost required guards"):
                self.audit(outputs)

    def test_upstream_loss_is_not_hidden_by_keyword_coverage(self):
        outputs, _ = self.build(overrides={"claude_domain": {"add": sorted(CLAUDE_GUARDS),
                                                               "remove": ["DOMAIN-SUFFIX,anthropic.com"]}})
        with self.assertRaisesRegex(ValueError, "lost upstream"):
            self.audit(outputs)

    def test_keyword_semantics_match_broad_user_policy(self):
        for host in ("claude-api.com", "api.claudecontentmoderation.com", "another-claude.example", "anthropic-proxy.example"):
            self.assertTrue(classical_matches(sorted(CLAUDE_GUARDS), host))
        self.assertFalse(classical_matches(sorted(CLAUDE_GUARDS), "unrelated.example"))

    def test_unknown_input_conversion_and_cache_injection_rejected(self):
        for changes in ({"input_behavior": "ipcidr"}, {"input_format": "classical"}, {"cache_tag": "v1,Proxy"}):
            manifest = json.loads((sync.ROOT / "sources.json").read_text())
            next(r for r in manifest["rules"] if r["name"] == "claude_domain").update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                sync.validate_manifest(manifest)

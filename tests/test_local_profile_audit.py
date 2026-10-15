# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts.client_profiles import QUIC_RULE, TEST_TEMPLATE_VALUES, build_profiles, required_policies, translate_rule

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('ruby'), 'Optional local audit requires Ruby')
class LocalProfileAuditTests(unittest.TestCase):
    def setUp(self):
        manifest = json.loads((ROOT / 'sources.json').read_text())
        self.manifest = manifest
        routing = json.loads((ROOT / 'custom/client-routing.json').read_text())
        contract = json.loads((ROOT / 'custom/classification.json').read_text())
        values = {**TEST_TEMPLATE_VALUES, 'TAILSCALE_DIRECT_IPV4': '100.64.0.1'}
        self.clash, self.surge = build_profiles(manifest, routing, contract, values)
        self.clash['proxy-groups'] = [{'name': p, 'type': 'select', 'proxies': ['DIRECT']}
                                      for p in required_policies(self.clash['rules'])]

    def run_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            clash = Path(directory) / 'clash.json'
            surge = Path(directory) / 'surge.conf'
            # JSON is a valid YAML document; never need real nodes or credentials.
            clash.write_text(json.dumps(self.clash))
            group_names = [g['name'] for g in self.clash['proxy-groups']]
            surge.write_text('[Proxy Group]\n' + '\n'.join(p + ' = select, DIRECT' for p in group_names)
                             + '\n[Rule]\n' + '\n'.join(self.surge) + '\n[Host]\n')
            before = [clash.read_bytes(), surge.read_bytes()]
            result = subprocess.run(['ruby', str(ROOT / 'scripts/audit_local_profiles.rb'),
                                     '--clash', str(clash), '--surge', str(surge)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(before, [clash.read_bytes(), surge.read_bytes()])
            self.assertNotIn('100.64.0.1', result.stdout + result.stderr)
            self.assertNotIn('EXAMPLE-HOME-WIFI', result.stdout + result.stderr)
            return result

    def test_all_rules_and_providers_match_without_modification(self):
        result = self.run_audit()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report['clash_enabled_rules'], report['surge_enabled_rules']), (38, 39))
        self.assertTrue(report['complete_ordered_match'])
        self.assertTrue(report['clash_only_quic_guard'])
        self.assertFalse(report['surge_rule_level_quic_reject'])

    def test_reintroduced_surge_quic_guard_is_detected(self):
        self.surge.insert(1, translate_rule(QUIC_RULE, self.manifest, 'surge'))
        result = self.run_audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Surge: rule order/content differs', result.stderr)

    def test_missing_clash_quic_guard_is_detected(self):
        self.clash['rules'].remove(QUIC_RULE)
        result = self.run_audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Clash: rule order/content differs', result.stderr)

    def test_missing_clash_nodeseek_is_detected(self):
        self.clash['rules'].remove('DOMAIN-SUFFIX,nodeseek.com,Nodeseek')
        result = self.run_audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Clash: rule order/content differs', result.stderr)

    def test_surge_policy_or_order_difference_is_detected(self):
        self.surge[self.surge.index('DOMAIN-KEYWORD,n26,N26')] = 'DOMAIN-KEYWORD,n26,Proxy'
        result = self.run_audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Surge: rule order/content differs', result.stderr)

    def test_provider_omission_is_detected(self):
        self.clash['rule-providers'].pop('claude_domain')
        result = self.run_audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('provider definitions differ', result.stderr)

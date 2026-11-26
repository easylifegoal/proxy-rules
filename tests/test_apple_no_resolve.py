# SPDX-License-Identifier: GPL-3.0-only
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sync_rules as sync
from scripts.client_profiles import build_profiles, validate_routing
from scripts.rule_audit import classical_matches

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (b'# upstream original\nDOMAIN-SUFFIX,apple.com\nDOMAIN-KEYWORD,testflight\n'
          b'IP-CIDR,17.0.0.0/8,no-resolve\nIP-CIDR6,2620:149::/32,no-resolve\n'
          b'PROCESS-NAME,apsd\nUSER-AGENT,AppleTV*\n')


class AppleNoResolveTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / 'sources.json').read_text())
        self.rule = copy.deepcopy(next(r for r in self.manifest['rules'] if r['name'] == 'apple_no_resolve'))
        self.rule['minimum_entries'] = 3

    def build(self, data=SOURCE):
        return sync.build_rule(self.rule, data,
                               {'blackmatrix7': {'repository': 'blackmatrix7/ios_rule_script', 'sha': 'a' * 40}},
                               {}, {}, Path('/unused'), ROOT, False)

    def test_projection_is_explicit_and_keeps_domain_keyword_ipv4_and_ipv6(self):
        entries, excluded = sync.project_classical(SOURCE.decode(), ['PROCESS-NAME', 'USER-AGENT'])
        self.assertEqual(len(entries), 4)
        self.assertEqual(excluded, {'PROCESS-NAME': ['PROCESS-NAME,apsd'], 'USER-AGENT': ['USER-AGENT,AppleTV*']})
        self.assertTrue(classical_matches(entries, 'www.apple.com'))
        self.assertTrue(classical_matches(entries, 'unrelated-testflight.example'))
        self.assertFalse(classical_matches(entries, 'unrelated.example'))

    def test_full_upstream_is_retained_and_shared_outputs_are_identical(self):
        with patch.object(sync, 'convert', side_effect=AssertionError('Keywords cannot be encoded as MRS')):
            artifacts, record = self.build()
        self.assertEqual(artifacts['Sources/apple_no_resolve.list'], SOURCE)
        self.assertEqual(record['classical_projection']['raw_entries'], 6)
        self.assertEqual(record['classical_projection']['excluded_entries'], 2)
        self.assertEqual(record['classical_projection']['excluded_counts'], {'PROCESS-NAME': 1, 'USER-AGENT': 1})
        self.assertNotIn('Clash/apple_no_resolve.mrs', artifacts)
        canonical = artifacts['Text/apple_no_resolve.list'].decode().splitlines()
        surge = [line for line in artifacts['Surge/apple_no_resolve.list'].decode().splitlines() if line and not line.startswith('#')]
        clash = [json.loads(line[4:]) for line in artifacts['Clash/apple_no_resolve.yaml'].decode().splitlines() if line.startswith('  - ')]
        self.assertEqual(canonical, surge)
        self.assertEqual(canonical, clash)
        self.assertEqual(artifacts['Sources/apple_no_resolve.excluded.list'].decode().splitlines(),
                         ['PROCESS-NAME,apsd', 'USER-AGENT,AppleTV*'])

    def test_unreviewed_and_malformed_rule_types_still_stop_publication(self):
        for extra in ('IP-ASN,714,no-resolve', 'PROCESS-NAME,apsd,DIRECT', 'USER-AGENT,', 'DOMAIN,apple.com,DIRECT'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                sync.project_classical(SOURCE.decode() + extra + '\n', ['PROCESS-NAME', 'USER-AGENT'])
        with self.assertRaises(ValueError):
            sync.project_classical(SOURCE.decode())

    def test_ip_no_resolve_cannot_disappear(self):
        for data in (SOURCE.replace(b'17.0.0.0/8,no-resolve', b'17.0.0.0/8'),
                     SOURCE.replace(b'2620:149::/32,no-resolve', b'2620:149::/32')):
            with self.assertRaisesRegex(ValueError, 'every IP entry'):
                self.build(data)

    def test_exclusions_are_not_a_generic_silent_rule_filter(self):
        for excluded in (['DOMAIN'], ['IP-CIDR'], ['USER-AGENT', 'USER-AGENT'], [], 'USER-AGENT'):
            manifest = copy.deepcopy(self.manifest)
            next(r for r in manifest['rules'] if r['name'] == 'apple_no_resolve')['exclude_classical_types'] = excluded
            with self.subTest(excluded=excluded), self.assertRaises(ValueError):
                sync.validate_manifest(manifest)

    def test_both_profiles_use_one_shared_set_and_no_resolve(self):
        routing = json.loads((ROOT / 'custom/client-routing.json').read_text())
        contract = json.loads((ROOT / 'custom/classification.json').read_text())
        clash, surge = build_profiles(self.manifest, routing, contract)
        self.assertIn('RULE-SET,apple_no_resolve,Apple,no-resolve', clash['rules'])
        self.assertTrue(any(r.endswith('/apple_no_resolve.list?v=shared-v1,Apple,no-resolve') for r in surge))
        provider = clash['rule-providers']['apple_no_resolve']
        self.assertEqual((provider['behavior'], provider['format']), ('classical', 'yaml'))
        self.assertTrue(provider['url'].endswith('/apple_no_resolve.yaml?v=shared-v1'))
        self.assertNotIn('apple_domain', clash['rule-providers'])
        self.assertNotIn('apple_ip', clash['rule-providers'])
        next(r for r in self.manifest['rules'] if r['name'] == 'apple_no_resolve')['no_resolve'] = False
        with self.assertRaisesRegex(ValueError, 'classical no-resolve'):
            validate_routing(self.manifest, routing, contract)


if __name__ == '__main__':
    unittest.main()

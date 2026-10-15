# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sync_rules as sync


class ValidationTests(unittest.TestCase):
    def test_current_manifest(self):
        manifest = json.loads((sync.ROOT / 'sources.json').read_text())
        sync.validate_manifest(manifest)
        self.assertEqual(len(manifest['rules']), 24)

    def test_invalid_composition_rejected(self):
        for inputs in ([], [{'id': '../bad', 'upstream': 'metacubex', 'path': 'a.mrs', 'minimum_entries': 1}],
                       [{'id': 'a', 'upstream': 'missing', 'path': 'a.mrs', 'minimum_entries': 1}]):
            manifest = json.loads((sync.ROOT / 'sources.json').read_text())
            media = next(r for r in manifest['rules'] if r['name'] == 'global_media_domain')
            media['inputs'] = inputs
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                sync.validate_manifest(manifest)

    def test_duplicate_composition_component_rejected(self):
        manifest = json.loads((sync.ROOT / 'sources.json').read_text())
        media = next(r for r in manifest['rules'] if r['name'] == 'global_media_domain')
        media['inputs'].append(media['inputs'][0])
        with self.assertRaisesRegex(ValueError, 'component'):
            sync.validate_manifest(manifest)

    def test_reject_format_behavior_mismatch(self):
        manifest = json.loads((sync.ROOT / 'sources.json').read_text())
        manifest['rules'][0]['input_format'] = 'classical'
        with self.assertRaisesRegex(ValueError, 'do not match'):
            sync.validate_manifest(manifest)

    def test_classical_shared_subset(self):
        source = '# comment\nDOMAIN,Identity.Apple.COM\nDOMAIN-SUFFIX,push.apple.com\nDOMAIN-KEYWORD,apple.com.edgekey.net\nIP-CIDR,17.57.144.0/22,no-resolve\nIP-CIDR6,2001:0db8::/32,no-resolve\n'
        expected = ['DOMAIN,identity.apple.com', 'DOMAIN-KEYWORD,apple.com.edgekey.net',
                    'DOMAIN-SUFFIX,push.apple.com', 'IP-CIDR,17.57.144.0/22,no-resolve',
                    'IP-CIDR6,2001:db8::/32,no-resolve']
        self.assertEqual(sync.parse_entries(source, 'classical'), expected)
        self.assertEqual(sync.surge_rules(expected, 'classical'), expected)

    def test_classical_rejects_unknown_and_malformed_rules(self):
        for source in ('', '<html>error</html>', 'USER-AGENT,Test*', 'IP-ASN,20473,no-resolve',
                       'DOMAIN,example.com,DIRECT', 'DOMAIN-SUFFIX,*.example.com',
                       'DOMAIN-KEYWORD,', 'IP-CIDR,2001:db8::/32', 'IP-CIDR6,192.0.2.0/24',
                       'IP-CIDR,192.0.2.0/24,REJECT', 'DOMAIN,with space.com',
                       'DOMAIN-WILDCARD,*.example.com', 'DOMAIN-KEYWORD,a*b',
                       'IP-CIDR,192.0.2.0/24,no-resolve,DIRECT'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                sync.parse_classical(source)

    def test_classical_overrides_preserve_keyword_and_no_resolve(self):
        entries = ['DOMAIN-KEYWORD,apple.com.edgekey.net']
        result = sync.apply_overrides(entries, {'add': ['IP-CIDR,192.0.2.0/24,no-resolve']}, 'classical')
        self.assertEqual(result, entries + ['IP-CIDR,192.0.2.0/24,no-resolve'])

    def test_mrs_example_falls_back_to_complete_classical_yaml(self):
        manifest = {'publish_repository': 'test/repo', 'rules': [
            {'name': 'apns', 'behavior': 'classical'}, {'name': 'google', 'behavior': 'domain'}]}
        example = sync.render_examples(manifest)['examples/rule-providers-mrs.yaml'].decode()
        self.assertIn('behavior: classical\n    format: yaml', example)
        self.assertIn('/Clash/apns.yaml', example)
        self.assertNotIn('apns.mrs', example)
        self.assertIn('/Clash/google.mrs', example)

    def test_business_examples_follow_same_contract_order(self):
        manifest = {'publish_repository': 'test/repo', 'rules': [
            {'name': 'ai', 'behavior': 'domain'}, {'name': 'claude', 'behavior': 'domain'}]}
        examples = sync.render_examples(manifest, {'domain_priority': ['claude', 'ai']})
        clash = examples['examples/business-rules-clash.yaml'].decode()
        surge = examples['examples/business-rules-surge.conf'].decode()
        self.assertLess(clash.index('RULE-SET,claude'), clash.index('RULE-SET,ai'))
        self.assertLess(surge.index('/Surge/claude.list'), surge.index('/Surge/ai.list'))
        self.assertIn('POLICY_claude', clash)
        self.assertNotIn('FINAL,', surge)

    def test_classical_build_preserves_raw_input_without_mrs(self):
        rule = {'name': 'apns', 'behavior': 'classical', 'input_format': 'classical',
                'upstream': 'test', 'path': 'apns.list', 'minimum_entries': 1}
        data = b'# original comment\nDOMAIN-KEYWORD,apple.com.edgekey.net\n'
        snapshots = {'test': {'repository': 'test/repo', 'sha': 'a' * 40}}
        with patch.object(sync, 'convert', side_effect=AssertionError('Classical must not use MRS')):
            artifacts, record = sync.build_rule(rule, data, snapshots, {}, {}, Path('/unused'), sync.ROOT, False)
        self.assertEqual(artifacts['Sources/apns.list'], data)
        self.assertNotIn('Clash/apns.mrs', artifacts)
        self.assertIsNone(record['mrs_sha256'])
        self.assertIn(b'DOMAIN-KEYWORD,apple.com.edgekey.net', artifacts['Clash/apns.yaml'])
        self.assertIn(b'DOMAIN-KEYWORD,apple.com.edgekey.net', artifacts['Surge/apns.list'])

    def test_reject_duplicate_output(self):
        manifest = json.loads((sync.ROOT / 'sources.json').read_text())
        manifest['rules'][1]['output'] = manifest['rules'][0]['name']
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            sync.validate_manifest(manifest)

    def test_reject_traversal(self):
        for value in ('../secret', '/etc/passwd', 'x/../../secret', r'..\secret'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                sync.safe_relative(value)

    def test_empty_and_html_rejected(self):
        for text in ('', '# comment', '<html>404 Not Found</html>'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                sync.parse_entries(text, 'domain')

    def test_domain_normalization_and_deduplication(self):
        self.assertEqual(sync.parse_entries('# hello\n+.Example.COM\n+.example.com\n', 'domain'), ['+.example.com'])

    def test_mihomo_dns_name_with_space_preserved(self):
        self.assertEqual(sync.parse_entries('Mijia Cloud', 'domain'), ['mijia cloud'])
        with self.assertRaises(ValueError):
            sync.surge_rules(['mijia cloud'], 'domain')

    def test_invalid_wildcards(self):
        for pattern in ('a*b.com', 'foo.+.com', 'example.com.', 'a..com', '+'):
            with self.subTest(pattern=pattern), self.assertRaises(ValueError):
                sync.parse_entries(pattern, 'domain')

    def test_invalid_cidr(self):
        for pattern in ('192.0.2.1/24', 'not-an-ip/24', '192.0.2.1'):
            with self.subTest(pattern=pattern), self.assertRaises(ValueError):
                sync.parse_entries(pattern, 'ipcidr')

    def test_ipv6_normalized(self):
        self.assertEqual(sync.parse_entries('2001:0db8::/32', 'ipcidr'), ['2001:db8::/32'])

    def test_drop_and_growth_guard(self):
        for count in (79, 201):
            with self.subTest(count=count), self.assertRaises(ValueError):
                sync.check_count('test', count, 10, 100)
        sync.check_count('test', 80, 10, 100)
        sync.check_count('test', 79, 10, 100, True)

    def test_minimum_never_bypassed(self):
        with self.assertRaises(ValueError):
            sync.check_count('test', 2, 10, 100, True)

    def test_exact_overrides(self):
        self.assertEqual(sync.apply_overrides(['+.a.com', '+.b.com'], {'remove': ['+.b.com'], 'add': ['+.c.com']}, 'domain'), ['+.a.com', '+.c.com'])

    def test_remove_missing_fails(self):
        with self.assertRaises(ValueError):
            sync.apply_overrides(['+.a.com'], {'remove': ['sub.a.com']}, 'domain')

    def test_empty_overrides_fail(self):
        with self.assertRaises(ValueError):
            sync.apply_overrides(['+.a.com'], {'remove': ['+.a.com']}, 'domain')

    def test_surges_domain_semantics(self):
        self.assertEqual(sync.surge_rules(['+.a.com', '.b.com', 'c.com'], 'domain'),
                         ['DOMAIN,c.com', 'DOMAIN-SUFFIX,a.com', 'DOMAIN-WILDCARD,*.b.com'])

    def test_surges_single_label_wildcard_not_silently_widened(self):
        for pattern in ('*', '*.a.com', 'a.*.com', '+.a.*.com'):
            with self.subTest(pattern=pattern), self.assertRaises(ValueError):
                sync.surge_rules([pattern], 'domain')

    def test_surges_ip_no_resolve(self):
        self.assertEqual(sync.surge_rules(['192.0.2.0/24', '2001:db8::/32'], 'ipcidr'),
                         ['IP-CIDR,192.0.2.0/24,no-resolve', 'IP-CIDR6,2001:db8::/32,no-resolve'])

    def test_same_commit_for_all_files(self):
        snapshots = {'meta': {'repository': 'test/repo', 'sha': 'a' * 40}}
        self.assertEqual(sync.source_url({'upstream': 'meta', 'path': 'geo/a!.mrs'}, snapshots),
                         'https://raw.githubusercontent.com/test/repo/' + 'a' * 40 + '/geo/a%21.mrs')

    def test_pin_validation(self):
        manifest = {'upstreams': {'meta': {'repository': 'test/repo', 'branch': 'meta'}}}
        with self.assertRaises(ValueError):
            sync.resolve_upstreams(manifest, {'meta': {'repository': 'other/repo', 'branch': 'meta', 'sha': 'a' * 40}})

    def test_metadata_only_change_does_not_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(sync.publish(root, {'Text/test.list': b'example.com\n'}, {'sha': 'old'}, False))
            self.assertFalse(sync.publish(root, {'Text/test.list': b'example.com\n'}, {'sha': 'new'}, False))
            self.assertEqual(json.loads((root / 'metadata/sync-state.json').read_text()), {'sha': 'old'})

    def test_check_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                sync.publish(root, {'Text/test.list': b'a.com\n'}, {}, True)
            self.assertEqual(list(root.iterdir()), [])

    def test_only_unchanged_recorded_obsolete_outputs_pruned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = b'example.com\n'
            state = {'output_sha256': {'Sources/old.txt': sync.digest(old)}}
            sync.publish(root, {'Sources/old.txt': old}, state, False)
            with self.assertRaises(ValueError):
                sync.publish(root, {}, {'output_sha256': {}}, True)
            self.assertTrue((root / 'Sources/old.txt').exists())
            sync.publish(root, {}, {'output_sha256': {}}, False)
            self.assertFalse((root / 'Sources/old.txt').exists())

    def test_modified_obsolete_outputs_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = b'example.com\n'
            state = {'output_sha256': {'Sources/old.txt': sync.digest(old)}}
            sync.publish(root, {'Sources/old.txt': old}, state, False)
            (root / 'Sources/old.txt').write_text('user edit\n')
            with self.assertRaisesRegex(ValueError, 'Refusing'):
                sync.publish(root, {}, {}, False)
            self.assertEqual((root / 'Sources/old.txt').read_text(), 'user edit\n')


@unittest.skipUnless((sync.ROOT / '.tools/mihomo').is_file(), 'Pinned Mihomo converter not installed')
class ConverterTests(unittest.TestCase):
    def test_composition_deduplicates_and_preserves_component_sources(self):
        data = (sync.ROOT / 'Clash/usbank.mrs').read_bytes()
        rule = {'name': 'bundle', 'behavior': 'domain', 'minimum_entries': 1, 'inputs': [
            {'id': 'first', 'upstream': 'test', 'path': 'a.mrs', 'minimum_entries': 1},
            {'id': 'second', 'upstream': 'test', 'path': 'b.mrs', 'minimum_entries': 1, 'select': ['+.bofa.com']}]}
        snapshots = {'test': {'repository': 'test/repo', 'sha': 'a' * 40}}
        artifacts, record = sync.build_rule(rule, {'first': data, 'second': data}, snapshots, {}, {},
                                            sync.ROOT / '.tools/mihomo', sync.ROOT, False)
        self.assertEqual(record['output_entries'], 6)
        self.assertEqual(record['components']['second']['selected_entries'], 1)
        self.assertEqual(artifacts['Sources/bundle/first.mrs'], data)
        self.assertEqual(artifacts['Sources/bundle/second.mrs'], data)
        self.assertFalse(record['upstream_mrs_preserved'])
        rule['inputs'][1]['select'] = ['+.not-in-source.example']
        with self.assertRaisesRegex(ValueError, 'absent upstream'):
            sync.build_rule(rule, {'first': data, 'second': data}, snapshots, {}, {},
                            sync.ROOT / '.tools/mihomo', sync.ROOT, False)

    def test_suffix_scope_and_bank_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bank.txt').write_text('+.example.com\n')
            rule = {'name': 'bank', 'behavior': 'domain', 'local': 'bank.txt', 'minimum_entries': 1,
                    'classical_yaml': True, 'aliases': ['OldBank']}
            artifacts, record = sync.build_rule(rule, None, {}, {}, {}, sync.ROOT / '.tools/mihomo', root, False)
            self.assertEqual(artifacts['Clash/bank.mrs'], artifacts['Clash/OldBank.mrs'])
            self.assertIn(b'DOMAIN-SUFFIX,example.com', artifacts['Surge/bank.list'])
            self.assertEqual(artifacts['Text/bank.list'], b'+.example.com\n')
            self.assertEqual(record['output_entries'], 1)

    def test_upstream_mrs_preserved_byte_for_byte(self):
        rule = {'name': 'bank', 'behavior': 'domain', 'upstream': 'test', 'path': 'bank.mrs', 'minimum_entries': 1}
        data = (sync.ROOT / 'Clash/usbank.mrs').read_bytes()
        snapshots = {'test': {'repository': 'test/repo', 'sha': 'a' * 40}}
        artifacts, record = sync.build_rule(rule, data, snapshots, {}, {}, sync.ROOT / '.tools/mihomo', sync.ROOT, False)
        self.assertEqual(artifacts['Clash/bank.mrs'], data)
        self.assertTrue(record['upstream_mrs_preserved'])

    def test_corrupt_binary_rejected(self):
        rule = {'name': 'bank', 'behavior': 'domain', 'upstream': 'test', 'path': 'bank.mrs', 'minimum_entries': 1}
        with self.assertRaisesRegex(ValueError, 'conversion failed'):
            sync.build_rule(rule, b'<html>404</html>', {'test': {'repository': 'test/repo', 'sha': 'a' * 40}},
                            {}, {}, sync.ROOT / '.tools/mihomo', sync.ROOT, False)


if __name__ == '__main__':
    unittest.main()

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
        self.assertEqual(len(manifest['rules']), 19)

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


@unittest.skipUnless((sync.ROOT / '.tools/mihomo').is_file(), 'Pinned Mihomo converter not installed')
class ConverterTests(unittest.TestCase):
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

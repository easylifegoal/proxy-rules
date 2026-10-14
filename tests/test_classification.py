# SPDX-License-Identifier: GPL-3.0-only
import unittest
from scripts.classification import Pattern, audit_classification, covered_by, overlap_witness


class ClassificationTests(unittest.TestCase):
    def test_exact_suffix_and_boundary(self):
        suffix = Pattern.parse('+.example.com')
        self.assertTrue(suffix.matches('example.com'))
        self.assertTrue(suffix.matches('DEEP.A.EXAMPLE.COM.'))
        self.assertFalse(suffix.matches('notexample.com'))
        self.assertFalse(Pattern.parse('example.com').matches('a.example.com'))

    def test_subdomain_only_excludes_apex(self):
        subonly = Pattern.parse('.example.com')
        self.assertFalse(subonly.matches('example.com'))
        self.assertTrue(subonly.matches('a.example.com'))
        self.assertIsNone(overlap_witness(subonly, Pattern.parse('example.com')))
        self.assertEqual(overlap_witness(subonly, Pattern.parse('+.example.com')), 'probe.example.com')

    def test_ancestor_overlap_not_just_literal_intersection(self):
        self.assertEqual(overlap_witness(Pattern.parse('+.com'), Pattern.parse('+.claude.com')), 'claude.com')
        self.assertEqual(overlap_witness(Pattern.parse('+.anthropic.com'), Pattern.parse('api.anthropic.com')), 'api.anthropic.com')
        self.assertIsNone(overlap_witness(Pattern.parse('+.example.com'), Pattern.parse('+.notexample.com')))

    def test_subset_union_and_direction(self):
        child = Pattern.parse('+.example.com')
        self.assertTrue(covered_by(child, [Pattern.parse('example.com'), Pattern.parse('.example.com')]))
        self.assertFalse(covered_by(child, [Pattern.parse('.example.com')]))
        self.assertTrue(covered_by(Pattern.parse('.example.com'), [child]))
        self.assertFalse(covered_by(child, [Pattern.parse('+.sub.example.com')]))

    def test_unsupported_patterns_fail_closed(self):
        for entry in ('*.example.com', 'a.*.com', 'with space', '', 'example.com,Proxy'):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                Pattern.parse(entry)

    def test_contract_checks_priority_and_records_allowed_overlap(self):
        data = {'claude': ['+.claude.ai'], 'ai': ['+.claude.ai', '+.openai.com'], 'media': ['+.youtube.com']}
        contract = {'schema_version': 1, 'domain_priority': ['claude', 'ai', 'media'],
                    'disjoint': [['media', 'ai']], 'subsets': [['claude', 'ai']],
                    'priority_overlaps': [['claude', 'ai']],
                    'samples': [{'domain': 'api.claude.ai', 'expected': 'claude'}]}
        report = audit_classification(data, contract)
        self.assertEqual(report['priority_overlaps'][0]['overlap_count'], 1)
        self.assertEqual(report['samples'][0]['all_matching_categories'], ['claude', 'ai'])
        contract['domain_priority'] = ['ai', 'claude', 'media']
        with self.assertRaisesRegex(ValueError, 'priority reversed'):
            audit_classification(data, contract)

    def test_media_ai_overlap_aborts_including_parent_suffix(self):
        data = {'media': ['+.com'], 'ai': ['+.anthropic.com']}
        contract = {'schema_version': 1, 'domain_priority': ['ai', 'media'], 'disjoint': [['media', 'ai']]}
        with self.assertRaisesRegex(ValueError, 'Forbidden category overlap'):
            audit_classification(data, contract)

    def test_forbidden_domain_aborts(self):
        contract = {'schema_version': 1, 'domain_priority': ['media'], 'forbidden': {'media': ['store.steampowered.com']}}
        with self.assertRaisesRegex(ValueError, 'Forbidden domain'):
            audit_classification({'media': ['+.steampowered.com']}, contract)

    def test_unknown_reference_and_subset_regression_fail(self):
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            audit_classification({}, {'schema_version': 1, 'domain_priority': ['missing']})
        with self.assertRaisesRegex(ValueError, 'subset broken'):
            audit_classification({'a': ['+.example.com'], 'b': ['+.sub.example.com']},
                                 {'schema_version': 1, 'domain_priority': ['a', 'b'], 'subsets': [['a', 'b']]})

    def test_sample_regression_fails(self):
        with self.assertRaisesRegex(ValueError, 'Classification regression'):
            audit_classification({'media': ['+.example.com']}, {'schema_version': 1, 'domain_priority': ['media'],
                                 'samples': [{'domain': 'example.com', 'expected': None}]})


if __name__ == '__main__':
    unittest.main()

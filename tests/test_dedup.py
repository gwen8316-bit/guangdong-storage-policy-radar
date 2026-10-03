import json
import tempfile
import unittest
from pathlib import Path
from collector.dedup import group_policies
from collector.storage import read_json, write_json
from analysis.__main__ import prepare, run_samples, fingerprint

CONFIG = json.loads(Path('config/analysis.json').read_text(encoding='utf-8'))


class DedupTests(unittest.TestCase):
    def policies(self):
        return {key: {'id': key, 'title': title, 'publish_date': '2026-10-01', 'content_status': 'complete',
                      'content_text': body, 'url': 'https://example.com/' + key, 'column_ids': [key]}
                for key, title, body in [('a', '“储能” 管理（试行）', '短正文'), ('b', '"储能"管理(试行)', '更完整的储能管理正文内容')]}

    def test_completed_first_then_fuller_body_all_sources_preserved(self):
        policies = self.policies()
        analyses = {'a': {'status': 'complete', 'interpretation': {'summary': 'a'}}}
        self.assertEqual(group_policies(policies, analyses)[0]['canonical_id'], 'a')
        analyses['b'] = {'status': 'complete', 'interpretation': {'summary': 'b'}}
        group = group_policies(policies, analyses)[0]
        self.assertEqual(group['canonical_id'], 'b')
        self.assertEqual({s['url'] for s in group['source_links']}, {p['url'] for p in policies.values()})
        self.assertEqual({c for s in group['source_links'] for c in s['column_ids']}, {'a', 'b'})
        policies['b']['content_status'] = 'partial'
        self.assertEqual(group_policies(policies, analyses)[0]['canonical_id'], 'a')

    def test_different_or_missing_publication_dates_never_merge(self):
        policies = self.policies()
        policies['b']['publish_date'] = '2026-10-02'
        self.assertEqual(len(group_policies(policies, {})), 2)
        for p in policies.values():
            p['publish_date'] = None
            p['list_date'] = '2026-10-01'
        self.assertEqual(len(group_policies(policies, {})), 2)

    def test_new_duplicate_is_grouped_without_changing_saved_decisions_or_calling_ai(self):
        policies = self.policies()
        class Never:
            model = 'test'
            def complete(self, *args):
                raise AssertionError('Existing completed interpretation must be reused')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = policies['a']
            saved = {'id': 'a', 'status': 'complete', 'relevance': '间接相关', 'input_hash': fingerprint(p),
                     'interpretation': {'summary': '原摘要', 'topics': []}}
            write_json(root / 'analysis/a.json', saved)
            write_json(root / 'policies/a.json', p)
            prepare(root, CONFIG)
            write_json(root / 'policies/b.json', policies['b'])
            loaded, summary = prepare(root, CONFIG)
            self.assertEqual((summary['raw_total'], summary['total']), (2, 1))
            self.assertEqual(run_samples(root, CONFIG, loaded, Never(), all_policies=True), 0)
            self.assertEqual(read_json(root / 'analysis/a.json', {}), saved)
            self.assertFalse((root / 'analysis/b.json').exists())
            self.assertEqual(len(read_json(root / 'policy-groups.json', [])[0]['source_links']), 2)

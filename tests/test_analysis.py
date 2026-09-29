import json
import tempfile
import unittest
from pathlib import Path
from analysis.__main__ import matches, validate, run_samples, source_text, relevance_text

CONFIG = json.loads(Path('config/analysis.json').read_text(encoding='utf-8'))


class AnalysisTests(unittest.TestCase):
    def test_keywords_match_title_or_body_only(self):
        self.assertIn('储能', matches({'title': '储能管理', 'content_text': ''}, CONFIG))
        self.assertIn('峰谷', matches({'title': '通知', 'content_text': '调整峰谷时段'}, CONFIG))
        self.assertEqual([], matches({'title': '通知', 'content_text': '会议', 'attachments': [{'text': '储能'}]}, CONFIG))

    def test_evidence_and_numbers_checked(self):
        result = {'summary': '规范储能工程建设', 'key_points': ['强化质量监督'] * 3,
                  'topics': ['安全管理与标准'], 'targets': [],
                  'impact': {'direction': '中性', 'reason': '明确监督要求'},
                  'evidence': ['加强新型储能工程质量监督管理'] * 3}
        source = '加强新型储能工程质量监督管理。'
        validate(result, source, CONFIG)
        result['summary'] = '新增100兆瓦'
        with self.assertRaises(ValueError):
            validate(result, source, CONFIG)
        result['summary'] = '规范储能工程建设'
        result['evidence'][0] = '原文并不存在的证据句子'
        with self.assertRaises(ValueError):
            validate(result, source, CONFIG)

    def test_three_real_samples_and_no_repeat(self):
        policies = {pid: json.loads((Path('data/policies') / (pid + '.json')).read_text(encoding='utf-8'))
                    for pid in CONFIG['sample_ids']}
        class Fake:
            model = 'fake-test-only'
            calls = 0
            def complete(self, system, text):
                self.calls += 1
                return {'relevance': '无关', 'reason': 'test'}, {}
        provider = Fake()
        with tempfile.TemporaryDirectory() as temp:
            run_samples(Path(temp), CONFIG, policies, provider)
            run_samples(Path(temp), CONFIG, policies, provider)
            self.assertEqual(provider.calls, 3)
        self.assertTrue(all(matches(p, CONFIG) for p in policies.values()))
        self.assertFalse(source_text(policies[CONFIG['sample_ids'][1]], CONFIG['max_input_chars'])[1])
        self.assertFalse(source_text(policies[CONFIG['sample_ids'][0]], CONFIG['max_input_chars'])[1])

    def test_budget_blocks_before_api(self):
        pid = CONFIG['sample_ids'][0]
        policy = json.loads((Path('data/policies') / (pid + '.json')).read_text(encoding='utf-8'))
        class Never:
            model = 'fake-test-only'
            def complete(self, *args):
                raise AssertionError('Must not call with zero budget')
        config = dict(CONFIG, sample_ids=[pid], monthly_budget_cny=0)
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(run_samples(Path(temp), config, {pid: policy}, Never()), 0)
            record = json.loads((Path(temp) / 'analysis' / (pid + '.json')).read_text(encoding='utf-8'))
            self.assertIn('budget', record['error'])

    def test_relevance_attachment_boundaries(self):
        text = relevance_text({'title': '标题', 'content_text': '甲' * 2001,
            'attachments': [{'text': '乙' * 1500}, {'text': '丙' * 600}]})
        self.assertEqual(text.count('甲'), 2000)
        self.assertEqual(text.count('乙'), 1500)
        self.assertEqual(text.count('丙'), 499)

if __name__ == '__main__':
    unittest.main()

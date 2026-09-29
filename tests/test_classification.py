import copy
import unittest
from collector.dedup import group_policies, normalize_title
from analysis.classification import apply_classification, validate_classification, classification_text

CONFIG = {'topics': ['辅助服务', '安全管理与标准'], 'targets': ['独立储能']}


class ClassificationTests(unittest.TestCase):
    def test_title_date_merge_prefers_complete_and_keeps_sources(self):
        policies = {'a': {'id': 'a', 'title': '“储能” 通知（试行）', 'publish_date': '2026-01-01', 'url': 'https://a', 'column_ids': ['a']},
                    'b': {'id': 'b', 'title': '"储能"通知(试行)', 'publish_date': '2026-01-01', 'url': 'https://b', 'column_ids': ['b']}}
        groups = group_policies(policies, {'b': {'interpretation': {'summary': '已完成'}}})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['canonical_id'], 'b')
        self.assertEqual({s['url'] for s in groups[0]['source_links']}, {'https://a', 'https://b'})
        policies['a']['publish_date'] = '2026-02-01'
        self.assertEqual(len(group_policies(policies, {})), 2)
        for p in policies.values():
            p['publish_date'] = None
        self.assertEqual(len(group_policies(policies, {})), 2)

    def test_evidence_required_for_each_label_and_summary_preserved(self):
        source = '独立储能参与辅助服务市场，按调频容量给予补偿。'
        result = {'relevance': '直接相关', 'reason': '实际规定储能补偿', 'evidence': '独立储能参与辅助服务市场',
                  'topics': [{'label': '辅助服务', 'evidence': '独立储能参与辅助服务市场'}],
                  'targets': [{'label': '独立储能', 'evidence': '独立储能参与辅助服务市场'}]}
        validate_classification(result, source, CONFIG)
        record = {'status': 'complete', 'interpretation': {'summary': '保留原摘要', 'key_points': ['原要点'], 'topics': [], 'targets': []}}
        apply_classification(record, result, 'now')
        self.assertEqual(record['interpretation']['summary'], '保留原摘要')
        self.assertEqual(record['interpretation']['key_points'], ['原要点'])
        self.assertEqual(record['interpretation']['topics'], ['辅助服务'])
        bad = copy.deepcopy(result)
        bad['topics'][0]['evidence'] = '原文不存在的补贴机制'
        with self.assertRaises(ValueError):
            validate_classification(bad, source, CONFIG)
        bad = dict(result, relevance='无关')
        with self.assertRaises(ValueError):
            validate_classification(bad, source, CONFIG)

    def test_context_preserves_original_quotes_and_marks_truncation(self):
        policy = {'title': '储能补偿办法', 'content_text': '背景' * 1000 + '独立储能参与辅助服务市场，按调频容量给予补偿。' + '说明' * 3000}
        source, truncated = classification_text(policy)
        self.assertTrue(truncated)
        self.assertIn('独立储能参与辅助服务市场', source)
        self.assertLessEqual(len(source), 3600)

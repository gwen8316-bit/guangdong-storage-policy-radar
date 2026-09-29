import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.update_site import update, analysis_errors
from analysis.__main__ import run_samples
from collector.storage import write_json, read_json


class SiteUpdateTests(unittest.TestCase):
    def test_failed_candidate_preserves_data_but_not_spent_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root / 'data/policies/old.json', {'title': 'old'})
            write_json(root / 'data/state/ai-budget.json', {'old': []})
            candidate = root / 'candidate'
            def fake_runner(command, **kwargs):
                if 'collector' in command:
                    write_json(candidate / 'policies/old.json', {'title': 'changed'})
                    write_json(candidate / 'status/latest-run.json', {'ended_at': 'now', 'result': 'success'})
                else:
                    self.assertEqual(command[command.index('--max-calls') + 1], '50')
                    write_json(candidate / 'state/ai-budget.json', {'spent': [0.2]})
                    write_json(candidate / 'analysis/failure.json', {'status': 'pending_review', 'error': 'network error'})
            with patch('scripts.update_site.ROOT', root):
                with self.assertRaisesRegex(RuntimeError, 'AI records failed'):
                    update(candidate, fake_runner)
            self.assertEqual(read_json(root / 'data/policies/old.json', {}), {'title': 'old'})
            self.assertEqual(read_json(root / 'data/state/ai-budget.json', {}), {'spent': [0.2]})

    def test_budget_deferral_is_not_provider_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root / 'analysis/a.json', {'status': 'pending_review', 'error': 'Run API call limit reached'})
            self.assertEqual(analysis_errors(root), [])

    def test_request_limit_includes_all_attempts(self):
        config = json.loads(Path('config/analysis.json').read_text(encoding='utf-8'))
        config.update(max_calls_per_run=2)
        policies = {str(i): {'id': str(i), 'title': '储能政策', 'url': 'https://example.com', 'content_text': '储能'} for i in range(4)}
        class Fake:
            model = 'test'
            calls = 0
            def complete(self, *args):
                self.calls += 1
                return {'relevance': '无关', 'reason': 'test'}, {}
        provider = Fake()
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(run_samples(Path(temp), config, policies, provider, all_policies=True), 2)
            self.assertEqual(provider.calls, 2)
            self.assertFalse((Path(temp) / 'analysis/3.json').exists())

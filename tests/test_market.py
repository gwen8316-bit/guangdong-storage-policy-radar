from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from market.data import snapshot
from market.__main__ import update
from scripts.prepare_publish import compose


class MarketTests(unittest.TestCase):
    end = date(2026, 10, 3)

    def rows(self):
        start = self.end - timedelta(days=365)
        return [{'date': (start + timedelta(days=i)).isoformat(), 'close': 100 + i}
                for i in range(366) if (start + timedelta(days=i)).weekday() < 5]

    def test_calendar_comparison_uses_previous_trading_day_and_close(self):
        rows = self.rows()
        # Friday Oct 2 minus 30 calendar days = Wednesday Sep 2; simulate closure.
        rows = [p for p in rows if p['date'] != '2026-09-02']
        data = snapshot(list(reversed(rows)) + rows[:1], self.end, 'now')
        self.assertEqual(data['latest']['date'], '2026-10-02')
        self.assertEqual(data['comparison']['target_date'], '2026-09-02')
        self.assertEqual(data['comparison']['baseline']['date'], '2026-09-01')
        self.assertAlmostEqual(data['comparison']['change_pct'], (464 / 433 - 1) * 100, places=3)
        self.assertEqual(len(data['series']), len(rows))

    def test_rejects_bad_short_conflicting_or_regressed_series(self):
        rows = self.rows()
        for bad in [[], rows[-5:], rows + [dict(rows[-1], close=0)], rows + [dict(rows[-1], close=float('nan'))], rows + [dict(rows[-1], close=99)]]:
            with self.assertRaises(ValueError):
                snapshot(bad, self.end, 'now')
        with self.assertRaises(ValueError):
            snapshot(rows, self.end, 'now', {'latest': {'date': '2026-10-05'}})

    def test_failed_fetch_preserves_saved_bytes_and_success_uses_isolated_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'market/lithium-carbonate.json'
            path.parent.mkdir()
            path.write_text('{"latest":{"date":"2026-10-02"}}', encoding='utf-8')
            original = path.read_bytes()
            def fail(*args, **kwargs):
                raise subprocess.TimeoutExpired('fetch', 90)
            with self.assertRaises(RuntimeError):
                update(Path(tmp), self.end, fail)
            self.assertEqual(path.read_bytes(), original)
            def succeed(command, **kwargs):
                self.assertEqual(kwargs['timeout'], 90)
                self.assertIn('market.fetch', command)
                return subprocess.CompletedProcess(command, 0, json.dumps(self.rows()))
            self.assertEqual(update(Path(tmp), self.end, succeed)['latest']['date'], '2026-10-02')

    def test_publish_composes_market_without_overwriting_policy_or_old_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ['saved/market', 'saved/policies', 'candidate/market']:
                (root / folder).mkdir(parents=True)
            (root / 'saved/policies/p.json').write_text('policy', encoding='utf-8')
            (root / 'saved/market/lithium-carbonate.json').write_text('old', encoding='utf-8')
            (root / 'candidate/market/lithium-carbonate.json').write_text('new', encoding='utf-8')
            compose(root / 'saved', root / 'published', root / 'candidate')
            self.assertEqual((root / 'published/policies/p.json').read_text(), 'policy')
            self.assertEqual((root / 'published/market/lithium-carbonate.json').read_text(), 'new')
            self.assertEqual((root / 'saved/market/lithium-carbonate.json').read_text(), 'old')
            compose(root / 'saved', root / 'fallback')
            self.assertEqual((root / 'fallback/market/lithium-carbonate.json').read_text(), 'old')

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { loadData, fingerprint, safeUrl, displayDate, recentCount, type Entry, type Policy } from '../src/lib/data.ts';
import { matchesFilters, type Filters } from '../src/lib/filter.ts';
import { loadBids, bidChart, loadMarket, priceChart, loadTariff, tariffValues } from '../src/lib/market.ts';

test('confirmed bid data breaks at missing months and retains isolated markers', () => {
  const { series } = loadBids();
  assert.equal(series.length, 12);
  assert.equal(series[0].month, '2025-09');
  assert.equal(series[11].month, '2026-08');
  assert.deepEqual(series.filter(p => p.system !== null).map(p => [p.month, p.system, p.epc]), [
    ['2025-09', .5959, 1.0858], ['2025-10', .5767, 1.0619],
    ['2026-01', .5309, 1.1673], ['2026-05', .6126, 1.0442],
    ['2026-07', .6233, 1.0280], ['2026-08', .6809, 1.1499],
  ]);
  for (const key of ['system', 'epc'] as const) {
    const chart = bidChart(series, key);
    assert.equal(chart.points.length, 6);
    assert.equal((chart.path.match(/M/g) || []).length, 4);
    assert.equal((chart.path.match(/L/g) || []).length, 2);
    assert.ok(chart.points.every(p => p.source_url && p.evidence.length === 2 && Number.isFinite(p.y)));
    assert.ok(chart.points.some(p => p.month === '2026-01'));
    assert.ok(chart.points.some(p => p.month === '2026-05'));
  }
});

test('confirmed tariff values retain precision and omit unverified sharp spreads', () => {
  const rows = loadTariff().series;
  assert.deepEqual(rows.map(p => p.month), ['2026-05','2026-06','2026-07','2026-08','2026-09','2026-10']);
  assert.deepEqual(rows.map(p => tariffValues(p).peakSpread), [0.8522,0.8488,0.8840,0.8610,0.9271,0.8913]);
  assert.deepEqual(rows.map(p => tariffValues(p).sharpSpread), [null,null,1.1687,1.1382,1.2256,null]);
  assert.ok(rows.every(p => p.sharp_listed && new URL(p.source_url).hostname === '95598.csg.cn'));
  assert.equal(tariffValues(rows[5]).sharp.toFixed(4), '1.4625');
  assert.equal((tariffValues(rows[5]).peakSpread - tariffValues(rows[4]).peakSpread).toFixed(4), '-0.0358');
});

test('market uses a sorted one-year LC0 series and finite chart coordinates', () => {
  const market = loadMarket();
  assert.ok(market);
  assert.equal(market.symbol, 'LC0');
  assert.ok(market.series.length >= 150);
  assert.deepEqual(market.latest, market.series.at(-1));
  assert.deepEqual(market.series.map(p => p.date), [...new Set(market.series.map(p => p.date))].sort());
  const chart = priceChart(market.series)!;
  assert.ok(chart.points.every(p => Number.isFinite(p.x) && Number.isFinite(p.y) && p.y >= 30 && p.y <= 258));
  assert.ok(!chart.path.includes('NaN'));
  assert.equal(priceChart([]), null);
  assert.ok(!priceChart([{date:'2026-01-01',close:100},{date:'2026-01-02',close:100}])!.path.includes('NaN'));
});

test('real data: current interpretations only, deduplicated and sorted', () => {
  const data = loadData();
  assert.ok(data.entries.length > 0);
  assert.equal(new Set(data.entries.map(e => e.policy.id)).size, data.entries.length);
  const keys = data.policies.filter(p => p.publish_date).map(p => p.title.normalize('NFKC').replace(/[\s\u200b\ufeff]+/gu, '').replace(/[“”]/gu, '"').replace(/[‘’]/gu, "'") + '|' + p.publish_date);
  assert.equal(new Set(keys).size, keys.length);
  assert.equal(data.policies.flatMap(p => p.source_links || []).length, data.rawPolicies.length);
  for (const policy of data.policies) {
    for (const source of policy.source_links || []) {
      assert.ok(source.column_ids.every(id => policy.column_ids.includes(id)));
    }
  }
  for (const entry of data.entries) {
    assert.equal(entry.analysis.input_hash, fingerprint(entry.policy, entry.analysis.rule_version));
    assert.ok(['直接相关', '间接相关'].includes(entry.analysis.relevance));
  }
  assert.deepEqual(data.entries.map(e => e.date), data.entries.map(e => e.date).sort().reverse());
});

test('stale and irrelevant records are hidden; known-relevant pending reviews remain visible', t => {
  const prefix = resolve(tmpdir(), 'policy-radar-test-');
  const root = mkdtempSync(prefix);
  t.after(() => { assert.ok(resolve(root).startsWith(prefix)); rmSync(root, { recursive: true, force: true }); });
  for (const dir of ['policies', 'analysis', 'config']) mkdirSync(join(root, dir));
  const write = (path: string, data: unknown) => writeFileSync(join(root, path), JSON.stringify(data));
  const p = { id: 'a'.repeat(64), title: '储能政策', content_hash: 'body', attachments_hash: 'files', publish_date: null, list_date: '2026-01-01', column_ids: [], source_ids: [] } as unknown as Policy;
  const a = { id: p.id, status: 'complete', relevance: '直接相关', rule_version: 'test', input_hash: fingerprint(p, 'test'), interpretation: {} };
  write('policies/' + p.id + '.json', p);
  write('analysis-index.json', [{ id: p.id, visible: true, status: 'complete', relevance: '直接相关' }]);
  write('analysis-summary.json', { rule_version: 'test', counts: {} });
  write('config/sources.json', { columns: [] });
  write('config/analysis.json', { topics: [], targets: [] });
  const load = () => loadData(root, join(root, 'config'));
  assert.equal(load().entries.length, 0);
  for (const override of [{ input_hash: 'old' }, { status: 'pending_review' }, { relevance: '无关' }, { rule_version: 'old' }]) {
    write('analysis/' + p.id + '.json', { ...a, ...override });
    assert.equal(load().entries.length, 0);
  }
  write('analysis/' + p.id + '.json', a);
  assert.equal(load().entries.length, 1);
  write('analysis/' + p.id + '.json', { ...a, status: 'pending_review', interpretation: undefined });
  write('analysis-index.json', [{ id: p.id, visible: false, status: 'pending_review', relevance: '直接相关' }]);
  assert.equal(load().entries.length, 1);
  assert.equal(load().entries[0].analysis.review_status, '待核查');
  assert.equal(load().entries[0].analysis.interpretation.impact.direction, '待判断');
  write('policies/' + p.id + '.json', { ...p, attachments_hash: 'changed' });
  assert.equal(load().entries.length, 0);
});

test('combined filters include secondary source, boundaries and empty dates', () => {
  const item = { text: '广东 储能 电力市场', sources: ['nea', 'gd'], topics: ['电力现货市场'], targets: ['独立储能'], relevance: '直接相关', review: '待核查', date: '2026-09-01', impact: '中性' };
  const filters: Filters = { q: '广东 储能', source: 'gd', topic: '电力现货市场', target: '独立储能', relevance: '直接相关', review: '待核查', from: item.date, to: item.date };
  assert.equal(matchesFilters(item, filters), true);
  for (const override of [{ q: '不存在' }, { source: 'nf' }, { from: '2026-09-02' }, { to: '2026-08-31' }, { review: '自动生成' }, { impact: '利好' }]) assert.equal(matchesFilters(item, { ...filters, ...override }), false);
  assert.equal(matchesFilters({ ...item, date: '' }, filters), false);
});

test('recent count uses 30 inclusive Beijing dates and excludes future records', () => {
  const entries = ['2026-08-30', '2026-08-31', '2026-09-29', '2026-09-30', ''].map(date => ({ date }) as Entry);
  assert.equal(recentCount(entries, new Date('2026-09-28T23:00:00Z')), 2);
});

test('dates do not substitute written date; links reject executable protocols', () => {
  assert.deepEqual(displayDate({ publish_date: null, list_date: '2026-02-01', written_date: '2026-01-01' } as Policy), { date: '2026-02-01', dateLabel: '列表日期' });
  assert.equal(safeUrl('javascript:alert(1)'), undefined);
  assert.equal(safeUrl('data:text/html,<script></script>'), undefined);
  assert.equal(safeUrl('https://www.nea.gov.cn/'), 'https://www.nea.gov.cn/');
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { loadData, fingerprint, safeUrl, displayDate, recentCount, latestCompleted, type Entry, type Policy } from '../src/lib/data.ts';
import { matchesFilters, type Filters } from '../src/lib/filter.ts';

test('real data: current interpretations only, deduplicated and sorted', () => {
  const data = loadData();
  assert.ok(data.entries.length > 0);
  assert.equal(new Set(data.entries.map(e => e.policy.id)).size, data.entries.length);
  const datedKeys = data.policies.filter(p => p.publish_date).map(p => p.title.normalize('NFKC').replace(/[\s\u200b\ufeff]+/gu, '').replace(/[“”]/gu, '"').replace(/[‘’]/gu, "'") + '|' + p.publish_date);
  assert.equal(new Set(datedKeys).size, datedKeys.length);
  assert.ok(data.policies.filter(p => (p.source_links?.length || 0) > 1).every(p => new Set(p.source_links!.map(s => s.url)).size === p.source_links!.length));
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
  assert.equal(latestCompleted(load().entries).length, 0);
  write('policies/' + p.id + '.json', { ...p, attachments_hash: 'changed' });
  assert.equal(load().entries.length, 0);
});

test('homepage excludes pending interpretations but preserves completed reviews', () => {
  const entries = [
    { analysis: { status: 'pending_review', review_status: '待核查' } },
    { analysis: { status: 'complete', review_status: '待核查' } },
    { analysis: { status: 'complete', review_status: '自动生成' } },
  ] as Entry[];
  assert.deepEqual(latestCompleted(entries, 1), [entries[1]]);
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

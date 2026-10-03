import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import assert from 'node:assert/strict';

const root = resolve('dist');
const base = '/guangdong-storage-policy-radar/';
function walk(dir) { return readdirSync(dir, { withFileTypes: true }).flatMap(d => d.isDirectory() ? walk(join(dir, d.name)) : [join(dir, d.name)]); }
const files = walk(root);
assert.ok(existsSync(join(root, 'index.html')));
assert.ok(existsSync(join(root, 'policies/index.html')));
assert.ok(existsSync(join(root, 'market/index.html')));
assert.ok(!existsSync(join(root, 'status')));
const pages = files.filter(f => f.endsWith('.html'));
for (const file of pages) {
  const html = readFileSync(file, 'utf8');
  assert.ok(html.includes('AI 生成，以原文为准'), `${file}: missing AI notice`);
  assert.ok(!html.includes('DEEPSEEK_API_KEY'), `${file}: server configuration exposed`);
  for (const match of html.matchAll(/(?:href|src)="([^"\s]+)"/g)) {
    const url = match[1];
    if (!url.startsWith('/')) continue;
    assert.ok(url.startsWith(base), `${file}: unprefixed URL ${url}`);
    let path = decodeURIComponent(url.slice(base.length).split(/[?#]/)[0]);
    if (!path || path.endsWith('/')) path += 'index.html';
    assert.ok(existsSync(resolve(root, path)), `${file}: broken internal link ${url}`);
  }
}
const home = readFileSync(join(root, 'index.html'), 'utf8');
assert.equal((home.match(/class="chart-row"/g) || []).length, 9);
assert.ok(home.includes('关于本项目'));
console.log(`Verified ${pages.length} pages, base paths, local links and all 9 themes.`);
const market = readFileSync(join(root, 'market/index.html'), 'utf8');
assert.ok(!market.includes('碳酸锂'));
assert.ok(market.includes('bid-description'));
assert.ok(market.indexOf('广东收益 ·') < market.indexOf('成本 ·'));
assert.ok(market.indexOf('成本 ·') < market.indexOf('全国背景 ·'));
assert.ok(market.includes('0.6809') && market.includes('1.1499'));
assert.ok(market.includes('政策 1') && market.includes('政策 2'));
assert.ok(market.includes('0.8913'));
assert.ok(market.includes('tariff-description'));
assert.ok(market.includes('暂无官方逐日执行记录，未计算'));
assert.equal((market.match(/>官方公告<\/a>/g) || []).length, 6);

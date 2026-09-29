import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import assert from 'node:assert/strict';

const root = resolve('dist');
const base = '/guangdong-storage-policy-radar/';
function walk(dir) { return readdirSync(dir, { withFileTypes: true }).flatMap(d => d.isDirectory() ? walk(join(dir, d.name)) : [join(dir, d.name)]); }
const files = walk(root);
assert.ok(existsSync(join(root, 'index.html')));
assert.ok(existsSync(join(root, 'policies/index.html')));
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

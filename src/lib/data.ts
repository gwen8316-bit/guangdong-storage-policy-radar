import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';

export interface Attachment { name: string; url: string; status: string; text?: string; error?: string; }
export interface Policy {
  id: string; title: string; url: string; content_hash?: string; attachments_hash?: string;
  source_ids: string[]; column_ids: string[]; publish_date: string | null; list_date: string | null;
  written_date: string | null; issuer: string | null; doc_number: string | null;
  content_text: string; content_status: string; attachments: Attachment[]; last_checked_at: string;
}
export interface Interpretation {
  summary: string; key_points: string[]; evidence: string[]; topics: string[]; targets: string[];
  impact: { direction: string; reason: string };
}
export interface Analysis {
  id: string; input_hash: string; rule_version: string; status: string; relevance: string;
  relevance_reason: string; review_status: string; review_reasons: string[];
  interpretation: Interpretation; analyzed_at: string; error?: string;
}
interface IndexRow { id: string; visible: boolean; status: string; relevance: string | null; }
interface Column { column_id: string; source_id: string; name: string; url: string; }
export interface Entry { policy: Policy; analysis: Analysis; date: string; dateLabel: string; }

function read<T>(path: string): T { return JSON.parse(readFileSync(path, 'utf8').replace(/^\uFEFF/, '')); }
function optional<T>(path: string, fallback: T): T {
  try { return read<T>(path); } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return fallback;
    throw error;
  }
}
export function safeUrl(value: string | undefined): string | undefined {
  try { const url = new URL(value ?? ''); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined; }
  catch { return undefined; }
}
export function fingerprint(policy: Policy, rule: string): string {
  // Match Python json.dumps(..., ensure_ascii=False), including default comma spaces.
  const values = [rule, policy.title, policy.content_hash ?? null, policy.attachments_hash ?? null];
  return createHash('sha256').update('[' + values.map(v => JSON.stringify(v)).join(', ') + ']').digest('hex');
}
export function displayDate(policy: Policy) {
  return { date: policy.publish_date || policy.list_date || '', dateLabel: policy.publish_date ? '发布日期' : policy.list_date ? '列表日期' : '日期未提供' };
}
export function loadData(root = resolve(process.env.POLICY_DATA_DIR || 'data'), configRoot = resolve('config')) {
  const index = read<IndexRow[]>(resolve(root, 'analysis-index.json'));
  const summary = read<{ rule_version: string; keyword_matches: number; counts: Record<string, number> }>(resolve(root, 'analysis-summary.json'));
  const columns = read<{ columns: Column[] }>(resolve(configRoot, 'sources.json')).columns;
  const policies = readdirSync(resolve(root, 'policies')).filter(f => f.endsWith('.json')).map(f => read<Policy>(resolve(root, 'policies', f)));
  const byId = new Map(policies.map(p => [p.id, p]));
  const entries: Entry[] = [];
  const warnings: string[] = [];
  for (const row of index) {
    if (!['直接相关', '间接相关'].includes(row.relevance || '')) continue;
    if (!/^[a-f0-9]{64}$/.test(row.id)) throw new Error('Invalid policy ID in analysis index');
    const policy = byId.get(row.id);
    const analysis = optional<Analysis | null>(resolve(root, 'analysis', `${row.id}.json`), null);
    if (!policy || !analysis || analysis.id !== row.id || !['complete', 'pending_review'].includes(analysis.status) || row.status !== analysis.status ||
        !['直接相关', '间接相关'].includes(analysis.relevance) || row.relevance !== analysis.relevance ||
        analysis.rule_version !== summary.rule_version || analysis.input_hash !== fingerprint(policy, summary.rule_version) || (analysis.status === 'complete' && !analysis.interpretation)) {
      warnings.push(`已隐藏缺失、未完成或过期的解读：${row.id}`);
      continue;
    }
    if (analysis.status !== 'complete') {
      // Keep known-relevant policies visible, without presenting unvalidated model output.
      analysis.review_status = '待核查';
      analysis.review_reasons = [...(analysis.review_reasons || []), '解读尚未通过校验，请以官方原文为准。'];
      analysis.interpretation = { summary: '解读尚未完成，请查看官方原文。', key_points: [], evidence: [], topics: [], targets: [], impact: { direction: '待判断', reason: '尚无通过校验的影响判断。' } };
    }
    entries.push({ policy, analysis, ...displayDate(policy) });
  }
  entries.sort((a, b) => b.date.localeCompare(a.date) || a.policy.id.localeCompare(b.policy.id));
  const analyzedAt = optional<{ ended_at?: string }>(resolve(root, 'analysis-last-run.json'), {}).ended_at;
  const updatedAt = optional<{ updated_at?: string }>(resolve(root, 'site-update.json'), {}).updated_at || analyzedAt;
  const taxonomy = read<{ topics: string[]; targets: string[] }>(resolve(configRoot, 'analysis.json'));
  return { entries, policies, columns, warnings, summary, analyzedAt, updatedAt, taxonomy };
}
export function formatTime(value: string | null | undefined): string {
  if (!value) return '暂无记录';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '时间无效';
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
}
export const sourceNames: Record<string, string> = { nea: '国家能源局', nf: '南方监管局', gd: '广东省发改委 / 能源局' };
export function issuerName(policy: Policy) {
  if (policy.issuer) return policy.issuer;
  // Attribute republications to the official document host rather than all discovery columns.
  const host = new URL(policy.url).hostname;
  return host === 'www.nea.gov.cn' ? '国家能源局' : host === 'nfj.nea.gov.cn' ? '南方监管局' :
    host === 'drc.gd.gov.cn' ? (policy.title.includes('广东省能源局') ? '广东省能源局' : '广东省发展改革委') : '未提供';
}
export function recentCount(entries: Entry[], now = new Date()) {
  const today = new Date(now.getTime() + 8 * 3600000).toISOString().slice(0, 10);
  const start = new Date(Date.parse(today) - 29 * 86400000).toISOString().slice(0, 10);
  return entries.filter(e => e.date >= start && e.date <= today).length;
}

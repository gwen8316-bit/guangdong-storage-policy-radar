import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export interface PricePoint { date: string; close: number; }
export interface BidPoint {
  month: string; system: number | null; epc: number | null;
  source_url: string | null; evidence: string[];
}
export function loadBids(root = resolve(process.env.POLICY_DATA_DIR || 'data')): { note: string; half_year_url: string; series: BidPoint[] } {
  return JSON.parse(readFileSync(resolve(root, 'market/storage-bids.json'), 'utf8'));
}
export function bidChart(series: BidPoint[], key: 'system' | 'epc') {
  let connected = false;
  const points = series.map((p, i) => ({ ...p, value: p[key], x: 65 + i * 60, y: p[key] === null ? null : 245 - p[key]! / 1.4 * 210 }));
  const path = points.map(p => {
    if (p.y === null) { connected = false; return ''; }
    const segment = `${connected ? 'L' : 'M'}${p.x},${p.y}`;
    connected = true; return segment;
  }).filter(Boolean).join(' ');
  return { path, points: points.filter(p => p.value !== null) };
}
export interface TariffPoint {
  month: string; source_url: string; zone: string;
  prices_fen: { sharp: number; peak: number; flat: number; valley: number };
  sharp_listed: boolean; sharp_execution: 'full_month' | 'unverified';
}
export interface TariffData {
  scope: string; zone_note: string; sharp_condition: string; sharp_note: string;
  series: TariffPoint[];
}
export function tariffValues(p: TariffPoint) {
  const { sharp, peak, flat, valley } = p.prices_fen;
  return { sharp: sharp / 100, peak: peak / 100, flat: flat / 100, valley: valley / 100,
    peakSpread: Number(((peak - valley) / 100).toFixed(4)),
    sharpSpread: p.sharp_execution === 'full_month' ? Number(((sharp - valley) / 100).toFixed(4)) : null };
}
export function loadTariff(root = resolve(process.env.POLICY_DATA_DIR || 'data')): TariffData {
  return JSON.parse(readFileSync(resolve(root, 'market/guangdong-tariff.json'), 'utf8'));
}
export interface StoragePoint {
  date: string; label: string; power: number; energy: number;
  original_power: string; original_energy: string;
  source_date: string; source_url: string; evidence: string; official_yoy?: string;
}
export interface StorageData {
  metric: string; frequency: string; power_unit: string; energy_unit: string;
  note: string; series: StoragePoint[];
}
export function loadStorage(root = resolve(process.env.POLICY_DATA_DIR || 'data')): StorageData {
  return JSON.parse(readFileSync(resolve(root, 'market/storage-capacity.json'), 'utf8'));
}
export interface MarketData {
  symbol: string; unit: string; fetched_at: string; requested_end: string;
  source: { provider: string; via: string; api: string; url: string; docs_url: string };
  latest: PricePoint;
  comparison: { target_date: string; baseline: PricePoint | null; change_pct: number | null };
  series: PricePoint[];
}
export function loadMarket(root = resolve(process.env.POLICY_DATA_DIR || 'data')): MarketData | null {
  try { return JSON.parse(readFileSync(resolve(root, 'market/lithium-carbonate.json'), 'utf8')); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw error;
  }
}
export function priceChart(series: PricePoint[]) {
  if (series.length < 2) return null;
  const prices = series.map(p => p.close);
  const low = Math.min(...prices), high = Math.max(...prices);
  const pad = Math.max((high - low) * 0.12, high * 0.01, 1);
  const min = Math.max(0, low - pad), max = high + pad;
  const first = Date.parse(series[0].date), last = Date.parse(series.at(-1)!.date);
  const points = series.map(p => ({ ...p, x: 132 + (Date.parse(p.date) - first) / Math.max(1, last - first) * 694,
    y: 258 - (p.close - min) / (max - min) * 228 }));
  return { points, path: points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' '),
    ticks: [0, 1, 2, 3, 4].map(i => ({ y: 258 - i * 57, value: min + (max - min) * i / 4 })) };
}

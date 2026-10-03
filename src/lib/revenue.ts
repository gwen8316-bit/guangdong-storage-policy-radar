export function estimateRevenue(p: { peak: number; flat: number; valley: number; efficiency: number; depth: number; days: number; cycles: number; cost: number }) {
  if (!Object.values(p).every(Number.isFinite) || p.efficiency <= 0 || p.efficiency > 1 || p.depth <= 0 || p.depth > 1 || p.days < 0 || p.days > 366 || !Number.isInteger(p.days) || ![1, 2].includes(p.cycles) || p.cost <= 0) throw new Error('参数无效');
  const first = p.depth * p.peak - p.depth / p.efficiency * p.valley;
  const second = p.cycles === 2 ? p.depth * p.peak - p.depth / p.efficiency * p.flat : 0;
  const daily = first + second;
  const annual = daily * p.days;
  return { first, second, daily, annual, investment: p.cost * 1000, payback: annual > 0 ? p.cost * 1000 / annual : null };
}

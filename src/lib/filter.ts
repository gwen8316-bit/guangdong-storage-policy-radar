export interface SearchItem { text: string; sources: string[]; topics: string[]; targets: string[]; relevance: string; review: string; date: string; impact?: string; }
export interface Filters { q: string; source: string; topic: string; target: string; relevance: string; review: string; from: string; to: string; impact?: string; }
export function matchesFilters(item: SearchItem, filters: Filters) {
  return filters.q.trim().toLocaleLowerCase().split(/\s+/).every(term => item.text.toLocaleLowerCase().includes(term)) &&
    (!filters.source || item.sources.includes(filters.source)) && (!filters.topic || item.topics.includes(filters.topic)) &&
    (!filters.target || item.targets.includes(filters.target)) && (!filters.relevance || item.relevance === filters.relevance) &&
    (!filters.review || item.review === filters.review) && (!filters.impact || item.impact === filters.impact) && (!filters.from || (!!item.date && item.date >= filters.from)) &&
    (!filters.to || (!!item.date && item.date <= filters.to));
}

"""Validate daily closes and calculate a calendar-day comparison."""
from datetime import date, timedelta
import math


def snapshot(rows, as_of, fetched_at, previous=None):
    start = as_of - timedelta(days=365)
    prices = {}
    for row in rows:
        day = date.fromisoformat(str(row['date'])[:10])
        if not start <= day <= as_of:
            continue
        close = float(row['close'])
        if not math.isfinite(close) or close <= 0:
            raise ValueError('Invalid daily close')
        key = day.isoformat()
        if key in prices and prices[key] != close:
            raise ValueError('Conflicting prices for the same date')
        prices[key] = close
    series = [{'date': day, 'close': prices[day]} for day in sorted(prices)]
    if len(series) < 150 or date.fromisoformat(series[0]['date']) > start + timedelta(days=20):
        raise ValueError('Insufficient history for a one-year daily chart')
    latest = series[-1]
    if previous and latest['date'] < previous['latest']['date']:
        raise ValueError('Refusing to replace saved data with an older series')
    target = (date.fromisoformat(latest['date']) - timedelta(days=30)).isoformat()
    baseline = next((p for p in reversed(series) if p['date'] <= target), None)
    return {'schema_version': 1, 'metric': 'lithium_carbonate_futures', 'symbol': 'LC0',
            'exchange': '广州期货交易所', 'unit': '元/吨', 'fetched_at': fetched_at,
            'requested_end': as_of.isoformat(), 'window_start': start.isoformat(),
            'source': {'provider': '新浪财经', 'via': 'AKShare', 'api': 'futures_main_sina',
                       'url': 'https://finance.sina.com.cn/futures/quotes/LC0.shtml',
                       'docs_url': 'https://akshare.akfamily.xyz/data/futures/futures.html'},
            'latest': latest, 'comparison': {'target_date': target, 'baseline': baseline,
                'change_pct': round((latest['close'] / baseline['close'] - 1) * 100, 4) if baseline else None},
            'series': series}

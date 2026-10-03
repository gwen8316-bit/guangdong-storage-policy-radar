"""Isolated AKShare request; caller enforces the process timeout."""
import argparse
from datetime import date, timedelta
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', required=True)
    args = parser.parse_args()
    import akshare as ak
    end = date.fromisoformat(args.as_of)
    frame = ak.futures_main_sina(symbol='LC0', start_date=(end - timedelta(days=365)).strftime('%Y%m%d'), end_date=end.strftime('%Y%m%d'))
    if not {'日期', '收盘价'}.issubset(frame.columns):
        raise ValueError('AKShare response is missing date/close columns')
    rows = [{'date': str(row['日期'])[:10], 'close': float(row['收盘价'])} for _, row in frame.iterrows()]
    print(json.dumps(rows, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()

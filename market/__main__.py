"""Fetch validated LC0 history atomically, without touching policy data."""
import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo
from collector.storage import read_json, write_json
from .data import snapshot


def update(root, as_of=None, runner=subprocess.run):
    current = datetime.now(ZoneInfo('Asia/Shanghai'))
    # Never present an intraday bar as a completed daily close.
    end = as_of or (current.date() if current.hour >= 16 else current.date() - timedelta(days=1))
    path = Path(root) / 'market/lithium-carbonate.json'
    previous = read_json(path, None)
    error = None
    for _ in range(2):
        try:
            result = runner([sys.executable, '-m', 'market.fetch', '--as-of', end.isoformat()],
                            capture_output=True, text=True, encoding='utf-8', timeout=90, check=True)
            data = snapshot(json.loads(result.stdout), end, current.isoformat(timespec='seconds'), previous)
            write_json(path, data)
            return data
        except (ValueError, subprocess.SubprocessError) as exc:
            error = exc
    raise RuntimeError('LC0 update failed; saved market data retained') from error


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--as-of', type=date.fromisoformat)
    args = parser.parse_args()
    data = update(Path(args.data_dir), args.as_of)
    print(json.dumps({'latest': data['latest'], 'comparison': data['comparison'], 'points': len(data['series'])}, ensure_ascii=False))

"""Compose the last good policy snapshot and independently fetched market data."""
import argparse
from pathlib import Path
import shutil


def compose(source, target, market=None):
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('.collector.lock', '*.tmp'))
    if market is not None:
        shutil.copytree(Path(market) / 'market', Path(target) / 'market', dirs_exist_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--market')
    args = parser.parse_args()
    compose(args.source, args.target, args.market)

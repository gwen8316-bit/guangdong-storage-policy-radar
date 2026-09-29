"""Build a candidate data snapshot. Never replace published data in this script."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collector.storage import read_json, write_json
from collector.http import now


def analysis_errors(candidate):
    # Budget deferral is expected with the daily cap. Provider/validation failures
    # reject the snapshot; the current site and its data remain untouched.
    deferred = {'Run API call limit reached', 'Monthly reserved budget reached'}
    return [p.stem for p in (candidate / 'analysis').glob('*.json')
            if (item := read_json(p, {})).get('status') == 'pending_review'
            and item.get('error') not in deferred]


def update(candidate, runner=subprocess.run):
    source = ROOT / 'data'
    candidate = Path(candidate).resolve()
    if candidate == source or source in candidate.parents or candidate in source.parents:
        raise ValueError('Candidate must be separate from the checked-in data directory')
    if candidate.exists():
        raise ValueError('Candidate directory already exists; use a fresh directory')
    shutil.copytree(source, candidate, ignore=shutil.ignore_patterns('.collector.lock', '*.tmp'))
    try:
        runner([sys.executable, '-m', 'collector', '--mode', 'incremental', '--batch-size', '100',
                '--data-dir', str(candidate)], cwd=ROOT, check=True)
        run = read_json(candidate / 'status/latest-run.json', {})
        if not run.get('ended_at') or run.get('result') != 'success':
            raise RuntimeError('Collection incomplete or returned errors; retain previous site')
        runner([sys.executable, '-m', 'analysis', '--all', '--max-calls', '50',
                '--data-dir', str(candidate)], cwd=ROOT, check=True)
        errors = analysis_errors(candidate)
        if errors:
            raise RuntimeError(f'{len(errors)} AI records failed; retain previous site')
        write_json(candidate / 'site-update.json', {'updated_at': now(), 'max_api_calls': 50})
    finally:
        # Reservations must survive failed updates, including interrupted calls.
        ledger = candidate / 'state/ai-budget.json'
        if ledger.exists():
            write_json(source / 'state/ai-budget.json', read_json(ledger, {}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    args = parser.parse_args()
    update(args.candidate)

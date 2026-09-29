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
from analysis.__main__ import fingerprint


def checkpoint(candidate):
    """Keep paid AI progress out of the published snapshot, even after failure."""
    candidate = Path(candidate)
    source = ROOT / 'data'
    ledger = candidate / 'state/ai-budget.json'
    if ledger.exists():
        write_json(source / 'state/ai-budget.json', read_json(ledger, {}))
    cache_path = source / 'state/update-analysis-cache.json'
    cache = read_json(cache_path, {})
    for path in (candidate / 'analysis').glob('*.json'):
        item = read_json(path, {})
        if item.get('input_hash') and item.get('relevance'):
            previous = cache.get(path.stem, {})
            if previous.get('input_hash') == item['input_hash'] and previous.get('status') in ('complete', 'irrelevant') and item.get('status') not in ('complete', 'irrelevant'):
                continue
            item.pop('raw_response', None)
            cache[path.stem] = item
    if cache:
        write_json(cache_path, cache)


def restore_analysis_cache(candidate):
    cache = read_json(ROOT / 'data/state/update-analysis-cache.json', {})
    for pid, item in cache.items():
        if len(pid) != 64 or any(c not in '0123456789abcdef' for c in pid):
            continue
        policy = read_json(candidate / 'policies' / (pid + '.json'), {})
        if not policy or item.get('input_hash') != fingerprint(policy):
            continue
        path = candidate / 'analysis' / (pid + '.json')
        saved = read_json(path, {})
        if saved.get('input_hash') == item['input_hash'] and saved.get('classification', {}).get('review_method') == 'assistant_source_review':
            continue  # An older failed-update cache must not undo a source review, even when the summary is pending.
        if saved.get('input_hash') == item['input_hash'] and saved.get('status') in ('complete', 'irrelevant'):
            continue  # Preserve published review annotations.
        write_json(path, item)


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
        restore_analysis_cache(candidate)
        runner([sys.executable, '-m', 'analysis', '--all', '--max-calls', '50',
                '--data-dir', str(candidate)], cwd=ROOT, check=True)
        errors = analysis_errors(candidate)
        if errors:
            raise RuntimeError(f'{len(errors)} AI records failed; retain previous site')
        write_json(candidate / 'site-update.json', {'updated_at': now(), 'max_api_calls': 50})
    finally:
        # Reservations must survive failed updates, including interrupted calls.
        checkpoint(candidate)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    args = parser.parse_args()
    update(args.candidate)

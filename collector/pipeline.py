"""Discover -> fetch -> attachments -> merge -> atomic JSON and status."""
import argparse
import hashlib
import json
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from . import attachments
from .http import Client, now
from .parsing import (normalize_url, policy_id, parse_detail, parse_html_list,
                      parse_nea_list, nea_data_url)
from .storage import Store, read_json, write_json


class RunLock:
    """OS-owned file lock releases automatically on process termination."""
    def __init__(self, root):
        self.path = Path(root) / '.collector.lock'

    def __enter__(self):
        import os
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('a+b')
        self.handle.write(b'0')
        self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError('Another collector is using this data directory')
        return self

    def __exit__(self, *exc):
        self.handle.close()


def membership(column, entry):
    return {k: column[k] for k in ('source_id', 'column_id')} | {
        'list_url': column['url'], 'list_date': entry['list_date'],
        'list_date_raw': entry.get('list_date_raw'), 'list_title': entry['title']}


def discover(client, column, store, since, mode, checkpoint, save, streak_limit):
    """Persist a discovered page before advancing; safe to resume after a crash."""
    if checkpoint.get('complete'):
        return list(checkpoint['entries'].values())
    entries = checkpoint.setdefault('entries', {})
    url = checkpoint.get('next_url') or column['url']
    seen_pages = set(checkpoint.get('visited', []))
    streak = 0
    while url:
        if url in seen_pages:
            raise ValueError(f'Pagination cycle: {url}')
        markup = client.text(url)
        if column['adapter'] == 'nea':
            data_url = nea_data_url(markup, url)
            found = parse_nea_list(client.text(data_url), data_url)
            next_url = None
        else:
            found, next_url = parse_html_list(markup, url, column['adapter'])
        if not found:
            raise ValueError('Empty list; cannot certify discovery completion')
        past_boundary = all(e['list_date'] and e['list_date'] < since for e in found)
        # NEA delivers one chronological JSON array; limit to logical batches for incremental stop.
        for entry in found:
            if entry['list_date'] and entry['list_date'] < since:
                continue
            old = store.get(entry['url'])
            known_here = old and column['column_id'] in old.get('column_ids', []) and old.get('content_status') != 'failed'
            streak = streak + 1 if known_here else 0
            entries[entry['url']] = entry
            if mode == 'incremental' and column['adapter'] == 'nea' and streak >= streak_limit:
                break
        seen_pages.add(url)
        stop_known = mode == 'incremental' and streak >= streak_limit
        checkpoint.update(next_url=next_url, visited=sorted(seen_pages),
                          complete=bool(past_boundary or stop_known or not next_url),
                          stop_reason='before_since' if past_boundary else ('known_streak' if stop_known else ('end' if not next_url else None)))
        save()
        if checkpoint['complete']:
            break
        url = next_url
    return list(entries.values())


def fetch_policy(client, entry, old):
    url = entry['url']
    try:
        response = client.get(url, max_bytes=16 * 1024 * 1024)
        from .http import decode
        new = parse_detail(decode(response['body'], response['headers'].get('content-type', '')), response['url'], entry)
        new.update(url=url, final_url=response['url'], last_fetch_error=None)
        metadata_errors = []
        from urllib.parse import urljoin
        for metadata_url in new.get('attachment_metadata_urls', []):
            try:
                metadata = json.loads(client.text(metadata_url))
                filename = metadata['name']
                new['attachments'].append({'name': filename,
                    'url': urljoin(url, '/hdjlpt/yjzj/api/attachments/view/' + str(metadata['id'])),
                    'format': Path(metadata['path']).suffix.lstrip('.').lower(), 'kind': 'attachment',
                    'size_bytes': None, 'sha256': None, 'status': 'pending', 'text': '', 'error': None})
            except Exception as exc:
                metadata_errors.append({'stage': 'attachment_metadata', 'url': metadata_url, 'reason': f'{type(exc).__name__}: {exc}'})
        new['attachments'] = [attachments.process(client, a) for a in new['attachments']]
        errors = [{'stage': 'attachment', 'url': a['url'], 'reason': a['error']}
                  for a in new['attachments'] if a['status'] == 'failed'] + metadata_errors
        new['collection_issues'] = errors
        return new, errors
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        return {'url': url, 'title': entry['title'], 'doc_number': None, 'issuer': None,
                'publish_date': None, 'written_date': None, 'content_text': '', 'content_status': 'failed',
                'attachments': [], 'field_evidence': {}, 'last_fetch_error': error,
                'collection_issues': [{'stage': 'detail', 'url': url, 'reason': error}]}, [
                    {'stage': 'detail', 'url': url, 'reason': error}]


def run(args):
    config = read_json(Path(args.config), {})
    columns = [c for c in config['columns'] if c.get('enabled', True)
               and (not args.columns or c['column_id'] in args.columns.split(','))]
    if not columns:
        raise ValueError('No enabled columns selected')
    if len({c['column_id'] for c in columns}) != len(columns):
        raise ValueError('Duplicate column_id in configuration')
    root = Path(args.data_dir)
    store = Store(root)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + args.mode
    client = Client(root / 'logs' / f'{run_id}.jsonl', config.get('request_interval_seconds', 3),
                    config.get('max_retries', 3), config.get('timeout_seconds', 30))
    summary = {'run_id': run_id, 'started_at': now(), 'ended_at': None, 'mode': args.mode,
               'since': args.since, 'columns': {}, 'total': {'new': 0, 'updated': 0, 'unchanged': 0, 'failed': 0}}
    summary_path = root / 'runs' / f'{run_id}.json'
    state_path = root / 'state' / 'backfill.json'
    state = read_json(state_path, {'since': args.since, 'columns': {}}) if args.mode == 'backfill' else {'since': args.since, 'columns': {}}
    if state['since'] != args.since:
        raise ValueError('Backfill checkpoint has a different since date; choose a separate data-dir or explicitly remove the checkpoint')
    status_path = root / 'status' / 'columns.json'
    health = read_json(status_path, {})
    pending_path = root / 'state' / 'incremental-pending.json'
    all_pending = read_json(pending_path, {}) if args.mode == 'incremental' else {}
    tasks = {url: {'entry': t['entry'], 'memberships': list(t['memberships'])} for url, t in all_pending.items()}
    active_ids = {c['column_id'] for c in columns}
    tasks = {url: t for url, t in tasks.items() if any(m['column_id'] in active_ids for m in t['memberships'])}
    for task in tasks.values():
        task['memberships'] = [m for m in task['memberships'] if m['column_id'] in active_ids]

    def save_state():
        if args.mode == 'backfill':
            write_json(state_path, state)

    def save_summary():
        write_json(summary_path, summary)

    for column in columns:
        cid = column['column_id']
        stats = summary['columns'][cid] = {'name': column['name'], 'new': 0, 'updated': 0,
                 'unchanged': 0, 'failed': 0, 'errors': [], 'discovered': 0, 'checked': 0,
                 'discovery_ok': False, 'discovery_pages': 0}
        fingerprint = hashlib.sha256(json.dumps(column, sort_keys=True).encode()).hexdigest()
        checkpoint = state['columns'].setdefault(cid, {})
        if checkpoint.get('fingerprint') != fingerprint:
            checkpoint.clear()
            checkpoint['fingerprint'] = fingerprint
        try:
            found = discover(client, column, store, args.since, args.mode, checkpoint,
                             save_state, config.get('known_streak', 10))
            stats.update(discovery_ok=True, discovered=len(found), discovery_pages=len(checkpoint.get('visited', [])),
                         discovery_stop=checkpoint.get('stop_reason'))
            for entry in found:
                m = membership(column, entry)
                old = store.get(entry['url'])
                if old:
                    store.add_memberships(entry['url'], [m])
                done = entry['url'] in checkpoint.get('processed', [])
                if args.mode == 'backfill' and done and old and not old.get('last_fetch_error') and not old.get('collection_issues'):
                    continue
                task = tasks.setdefault(entry['url'], {'entry': entry, 'memberships': []})
                merged = {member['column_id']: member for member in task['memberships']}
                merged[m['column_id']] = m
                task['memberships'] = list(merged.values())
        except Exception as exc:
            stats['failed'] += 1
            stats['errors'].append({'stage': 'list', 'url': column['url'], 'reason': f'{type(exc).__name__}: {exc}'})
        print(json.dumps({'column': cid, 'discovered': stats['discovered'], 'errors': stats['errors']}, ensure_ascii=False), flush=True)
        save_summary()

    # Incremental runs also rotate through older stored files so changes below the first page are eventually seen.
    if args.mode == 'incremental' and not args.discover_only:
        active = {c['column_id'] for c in columns if summary['columns'][c['column_id']]['discovery_ok']}
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.recheck_days)).isoformat()
        due = sorted((item for item in store.items.values() if active.intersection(item['column_ids'])
                      and (item.get('last_fetch_error') or item.get('collection_issues')
                           or item['last_checked_at'] < cutoff)), key=lambda item: item['last_checked_at'])
        for item in due[:args.recheck_limit]:
            memberships = [c for c in item['columns'] if c['column_id'] in active]
            if memberships:
                tasks.setdefault(item['url'], {'entry': {'url': item['url'], 'title': item['title'],
                                 'list_date': item['list_date']}, 'memberships': memberships})
    # Interleave domains so independent sources progress while another domain is paced.
    from urllib.parse import urlsplit
    queues = defaultdict(deque)
    for task in tasks.values():
        queues[urlsplit(task['entry']['url']).hostname].append(task)
    selected = []
    while any(queues.values()):
        for queue in queues.values():
            if queue:
                selected.append(queue.popleft())
    if args.batch_size:
        selected = selected[:args.batch_size]
    summary.update(queued=len(tasks), selected=0 if args.discover_only else len(selected))
    pending_tasks = dict(all_pending)
    for url, task in tasks.items():
        merged_memberships = {m['column_id']: m for m in pending_tasks.get(url, {}).get('memberships', [])}
        merged_memberships.update({m['column_id']: m for m in task['memberships']})
        pending_tasks[url] = {'entry': task['entry'], 'memberships': list(merged_memberships.values())}
    if args.mode == 'incremental':
        write_json(pending_path, pending_tasks)
    save_summary()
    if not args.discover_only:
        pool = ThreadPoolExecutor(max_workers=args.workers)
        try:
            futures = {pool.submit(fetch_policy, client, task['entry'], store.get(task['entry']['url'])): task for task in selected}
            for future in as_completed(futures):
                task = futures[future]
                new, errors = future.result()
                item, event = store.save(new, task['memberships'])
                summary['total'][event] += 1
                for m in task['memberships']:
                    cid = m['column_id']
                    stats = summary['columns'][cid]
                    stats['checked'] += 1
                    stats[event] += 1
                    if errors and event != 'failed':
                        stats['failed'] += 1
                    stats['errors'].extend(errors)
                    cp = state['columns'].get(cid, {})
                    if not errors:
                        processed = set(cp.get('processed', []))
                        processed.add(item['url'])
                        cp['processed'] = sorted(processed)
                print(json.dumps({'processed': sum(summary['total'].values()), 'event': event,
                                  'title': item['title'], 'errors': len(errors)}, ensure_ascii=False), flush=True)
                if args.mode == 'incremental' and not errors:
                    remaining_memberships = [m for m in pending_tasks.get(item['url'], {}).get('memberships', [])
                                             if m['column_id'] not in active_ids]
                    if remaining_memberships:
                        pending_tasks[item['url']]['memberships'] = remaining_memberships
                    else:
                        pending_tasks.pop(item['url'], None)
                    write_json(pending_path, pending_tasks)
                save_state()
                save_summary()
        except BaseException:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)
    store.index()
    for column in columns:
        cid = column['column_id']
        stats = summary['columns'][cid]
        stats['stored_count'] = sum(cid in item['column_ids'] for item in store.items.values())
        previous = health.get(cid, {})
        ok = stats['discovery_ok'] and not stats['failed']
        cp = state['columns'].get(cid, {})
        stats['backfill_remaining'] = len(set(cp.get('entries', {})) - set(cp.get('processed', []))) if args.mode == 'backfill' else None
        stats['pending_this_run'] = sum(any(m['column_id'] == cid for m in t['memberships']) for t in tasks.values()) - stats['checked']
        pending = args.discover_only or bool(stats['backfill_remaining']) or stats['pending_this_run'] > 0
        health[cid] = {'name': column['name'], 'last_run_id': run_id,
                       'last_attempt_at': now(), 'last_success_at': now() if ok and not pending else previous.get('last_success_at'),
                       'consecutive_failures': 0 if ok else previous.get('consecutive_failures', 0) + 1,
                       'last_errors': stats['errors'], 'status': ('pending' if pending else 'ok') if ok else 'degraded'}
        if args.mode == 'backfill':
            cp['collection_complete'] = bool(cp.get('complete') and not stats['backfill_remaining'])
    save_state()
    write_json(status_path, health)
    summary['ended_at'] = now()
    summary['result'] = 'with_errors' if any(s['failed'] for s in summary['columns'].values()) else 'success'
    save_summary()
    write_json(root / 'status' / 'latest-run.json', summary)
    print(json.dumps({'run_id': run_id, 'result': summary['result'], 'total': summary['total']}, ensure_ascii=False), flush=True)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=['incremental', 'backfill'], default='incremental')
    p.add_argument('--since', default='2025-10-01')
    p.add_argument('--config', default='config/sources.json')
    p.add_argument('--data-dir', default='data')
    p.add_argument('--columns', help='Comma-separated column IDs')
    p.add_argument('--batch-size', type=int, default=100, help='Maximum unique details this run; 0 = all queued')
    p.add_argument('--workers', type=int, default=3, choices=range(1, 5))
    p.add_argument('--discover-only', action='store_true')
    p.add_argument('--recheck-days', type=int, default=7)
    p.add_argument('--recheck-limit', type=int, default=20)
    args = p.parse_args()
    datetime.strptime(args.since, '%Y-%m-%d')
    if args.batch_size < 0 or args.recheck_days < 0 or args.recheck_limit < 0:
        p.error('Limits cannot be negative')
    with RunLock(args.data_dir):
        run(args)

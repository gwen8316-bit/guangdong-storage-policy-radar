"""Atomic JSON storage and URL-based merging."""
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from .http import now
from .parsing import normalize_url, policy_id


def read_json(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Windows readers/virus scanners can briefly deny delete-sharing on the target.
    for attempt in range(8):
        try:
            os.replace(temp, path)
            break
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(min(0.05 * 2 ** attempt, 1))


def content_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def attachments_hash(attachments):
    data = sorted((a['url'], a.get('sha256'), a.get('status'), a.get('text', '')) for a in attachments)
    return content_hash(json.dumps(data, ensure_ascii=False))


def merge(old, new, memberships):
    time = now()
    url = normalize_url(new['url'])
    item = dict(old or {})
    versions = list(item.get('versions', []))
    failed = new.get('content_status') == 'failed'
    # A failed check must never destroy the last successfully fetched body.
    if failed and old and old.get('content_status') != 'failed':
        item['last_fetch_error'] = new.get('last_fetch_error')
        event = 'failed'
    else:
        item.update(new)
        item['content_hash'] = content_hash(item.get('content_text', ''))
        item['attachments_hash'] = attachments_hash(item.get('attachments', []))
        changed = old and (old.get('content_hash') != item['content_hash'] or old.get('attachments_hash') != item['attachments_hash'])
        if changed:
            binary_keys = lambda files: sorted((a['url'], a.get('sha256') or '') for a in files)
            change_type = ('recovery' if old.get('content_status') == 'failed' else
                           'content' if old.get('content_hash') != item['content_hash'] else
                           'attachments' if binary_keys(old.get('attachments', [])) != binary_keys(item['attachments']) else 'parser_output')
            versions.append({'changed_at': time, 'old_content_hash': old.get('content_hash'),
                             'old_attachments_hash': old.get('attachments_hash'), 'change_type': change_type})
        event = 'failed' if failed else ('new' if not old else ('updated' if changed else 'unchanged'))
    columns = {(c['source_id'], c['column_id']): c for c in item.get('columns', [])}
    for column in memberships:
        columns[(column['source_id'], column['column_id'])] = column
    columns = sorted(columns.values(), key=lambda c: (c['source_id'], c['column_id']))
    first = old.get('columns', [columns[0]])[0] if old else columns[0]
    item.update(schema_version=1, id=policy_id(url), url=url,
                source_id=(old or {}).get('source_id', first['source_id']),
                column_id=(old or {}).get('column_id', first['column_id']),
                columns=columns, source_ids=sorted({c['source_id'] for c in columns}),
                column_ids=sorted({c['column_id'] for c in columns}),
                list_date=(old or {}).get('list_date') or first['list_date'],
                first_seen_at=(old or {}).get('first_seen_at', time), last_checked_at=time, versions=versions)
    return item, event


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.items = {p.stem: read_json(p, {}) for p in (self.root / 'policies').glob('*.json')}

    def get(self, url):
        with self.lock:
            return self.items.get(policy_id(url))

    def save(self, new, memberships):
        with self.lock:
            old = self.get(new['url'])
            item, event = merge(old, new, memberships)
            write_json(self.root / 'policies' / (item['id'] + '.json'), item)
            self.items[item['id']] = item
            return item, event

    def add_memberships(self, url, memberships):
        with self.lock:
            old = self.get(url)
            if old:
                item, _ = merge(old, old, memberships)
                # Metadata-only list discovery is not a new detail check.
                item['last_checked_at'] = old['last_checked_at']
                write_json(self.root / 'policies' / (item['id'] + '.json'), item)
                self.items[item['id']] = item

    def index(self):
        with self.lock:
            write_json(self.root / 'index.json', [{'id': i['id'], 'url': i['url'], 'title': i['title'],
                        'column_ids': i['column_ids'], 'list_date': i['list_date'], 'content_status': i['content_status']}
                       for i in sorted(self.items.values(), key=lambda i: i['id'])])

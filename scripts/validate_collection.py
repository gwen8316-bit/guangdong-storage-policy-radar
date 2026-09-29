"""Offline integrity checks and reproducible sample selection for acceptance."""
import argparse
import json
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector.parsing import policy_id, normalize_url
from collector.storage import content_hash, attachments_hash, read_json, write_json


def validate(root):
    root = Path(root)
    items = [read_json(p, {}) for p in sorted((root / 'policies').glob('*.json'))]
    errors, warnings = [], []
    ids, urls = set(), set()
    counts, statuses, attachment_statuses = Counter(), Counter(), Counter()
    for item in items:
        pid = item['id']
        if pid in ids or item['url'] in urls:
            errors.append(f'duplicate: {pid}')
        ids.add(pid)
        urls.add(item['url'])
        if policy_id(item['url']) != pid or normalize_url(item['url']) != item['url']:
            errors.append(f'noncanonical_id: {pid}')
        if content_hash(item['content_text']) != item['content_hash']:
            errors.append(f'body_hash_mismatch: {pid}')
        if attachments_hash(item['attachments']) != item['attachments_hash']:
            errors.append(f'attachment_hash_mismatch: {pid}')
        if len(item['columns']) != len({c['column_id'] for c in item['columns']}):
            errors.append(f'duplicate_membership: {pid}')
        for field in ('list_date', 'publish_date', 'written_date'):
            if item.get(field):
                try:
                    date.fromisoformat(item[field])
                except ValueError:
                    errors.append(f'invalid_date:{pid}:{field}')
        for field in ('publish_date', 'written_date', 'issuer', 'doc_number'):
            if item.get(field) and not item.get('field_evidence', {}).get(field):
                errors.append(f'no_field_evidence:{pid}:{field}')
        if item['content_status'] == 'image_only' and len(item['content_text']) >= 40:
            errors.append(f'image_only_with_text:{pid}')
        for token in ['设为首页', '网站地图', '扫一扫在手机打开当前页', '目录项的基本信息', 'ICP备']:
            if token in item['content_text']:
                warnings.append({'id': pid, 'reason': 'possible_navigation_text', 'token': token})
        if item.get('last_fetch_error') or item.get('collection_issues'):
            warnings.append({'id': pid, 'reason': 'unresolved_collection_issue'})
        counts.update(item['column_ids'])
        statuses.update([item['content_status']])
        attachment_statuses.update(a['status'] for a in item['attachments'])
    state = read_json(root / 'state' / 'backfill.json', {'columns': {}})
    coverage = {}
    for cid, cp in state['columns'].items():
        missing = sorted(set(cp.get('entries', {})) - urls)
        coverage[cid] = {'discovered': len(cp.get('entries', {})), 'stored': counts[cid],
                         'missing_urls': missing, 'discovery_complete': cp.get('complete'),
                         'collection_complete': cp.get('collection_complete')}
        if missing:
            errors.append(f'missing_discovered_documents:{cid}:{len(missing)}')
    sample = random.Random(20260929).sample(items, min(10, len(items)))
    return {'unique_documents': len(items), 'column_memberships': sum(counts.values()),
            'cross_column_documents': sum(len(i['columns']) > 1 for i in items),
            'column_counts': dict(counts), 'content_statuses': dict(statuses),
            'attachment_statuses': dict(attachment_statuses), 'coverage': coverage,
            'errors': errors, 'warnings': warnings,
            'sample_seed': 20260929,
            'sample': [{k: i.get(k) for k in ('id', 'url', 'title', 'list_date', 'publish_date', 'written_date',
                        'content_status', 'body_selector', 'field_evidence')} | {
                        'characters': len(i['content_text']), 'first_paragraph': i['content_text'].splitlines()[:2],
                        'last_paragraph': i['content_text'].splitlines()[-2:]} for i in sample]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--output', default='reports/collection-validation.json')
    args = parser.parse_args()
    result = validate(args.data_dir)
    write_json(Path(args.output), result)
    print(json.dumps({k: v for k, v in result.items() if k != 'sample'}, ensure_ascii=False, indent=2))
    sys.exit(bool(result['errors']))

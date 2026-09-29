"""Reclassify the approved scope in small resumable batches; preserve summaries."""
import argparse
import copy
import json
from pathlib import Path
from collector.storage import read_json, write_json
from collector.http import now
from collector.pipeline import RunLock
from collector.dedup import group_policies
from .__main__ import prepare, fingerprint
from .classification import CLASSIFICATION_VERSION, prompt, classification_text, validate_classification, apply_classification
from .provider import DeepSeek


def run(root, config, provider, max_calls=29):
    scope = read_json(root / 'reclassification-scope.json', {})['ids']
    policies = {pid: read_json(root / 'policies' / (pid + '.json'), {}) for pid in scope}
    records = {pid: read_json(root / 'analysis' / (pid + '.json'), {}) for pid in scope}
    groups = group_policies(policies, records)
    audit_path = root / 'reclassification-v3.json'
    audit = read_json(audit_path, {'version': CLASSIFICATION_VERSION, 'scope_count': len(scope), 'before': copy.deepcopy(records), 'results': {}, 'api_calls': 0})
    ledger_path = root / 'state/ai-budget.json'
    ledger = read_json(ledger_path, {})
    calls = 0
    queue = [g for g in groups if any(records[pid].get('classification_version') != CLASSIFICATION_VERSION for pid in g['member_ids'])]
    failures = {}
    while queue and calls < max_calls:
        batch, queue = queue[:3], queue[3:]
        sources = {g['canonical_id']: classification_text(policies[g['canonical_id']]) for g in batch}
        text = json.dumps([{'id': pid, 'source': value[0]} for pid, value in sources.items()], ensure_ascii=False)
        system = prompt(config)
        if len((system + text).encode('utf-8')) > 50000:
            raise ValueError('Classification input exceeds budget-safe limit')
        month = now()[:7]
        entries = ledger.setdefault(month, [])
        if round(sum(e['reserved_cny'] for e in entries) + config['reserve_per_call_cny'], 6) > config['monthly_budget_cny']:
            queue = batch + queue
            break
        entry = {'at': now(), 'policy_ids': list(sources), 'stage': 'reclassify-v3', 'reserved_cny': config['reserve_per_call_cny'], 'status': 'reserved'}
        entries.append(entry)
        write_json(ledger_path, ledger)
        calls += 1
        audit['api_calls'] += 1
        try:
            raw, usage = provider.complete(system, text)
            entry.update(status='returned', usage=usage)
            items = raw.get('items', [])
            mapped = {item.get('id'): item for item in items if isinstance(item, dict)}
            if len(mapped) != len(items) or set(mapped) != set(sources):
                raise ValueError('Batch IDs do not match request')
            for group in batch:
                pid = group['canonical_id']
                try:
                    result = validate_classification(mapped[pid], sources[pid][0], config)
                    for member in group['member_ids']:
                        record = records[member]
                        # Classification evidence comes from the retained canonical original.
                        apply_classification(record, result, now(), sources[pid][1])
                        record['classification']['source_id'] = pid
                        record['input_hash'] = fingerprint(policies[member])
                        write_json(root / 'analysis' / (member + '.json'), record)
                    audit['results'][pid] = {'member_ids': group['member_ids'], **result}
                    failures.pop(pid, None)
                except ValueError as exc:
                    failures[pid] = str(exc)
                    queue.append(group)
        except Exception as exc:
            entry['error'] = str(exc)
            if entry['status'] == 'reserved':
                entry['status'] = 'failed'
            for group in batch:
                failures[group['canonical_id']] = str(exc)
            queue.extend(batch)
        write_json(ledger_path, ledger)
        audit.update(last_updated_at=now(), failures=failures)
        write_json(audit_path, audit)
        print(json.dumps({'calls': calls, 'complete_groups': len(audit['results']), 'remaining': len(queue), 'failures': failures}, ensure_ascii=False), flush=True)
    _, summary = prepare(root, config)
    audit.update(complete=not queue, remaining_ids=[g['canonical_id'] for g in queue], counts=summary['counts'], ended_at=now())
    write_json(audit_path, audit)
    if queue:
        raise RuntimeError(f'Reclassification incomplete: {len(queue)} groups remain; keep current website')
    write_json(root / 'site-update.json', {'updated_at': now(), 'reason': 'deduplicate and reclassify-v3'})
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-calls', type=int, default=29)
    args = parser.parse_args()
    root = Path('data')
    config = read_json(Path('config/analysis.json'), {})
    with RunLock(root):
        run(root, config, DeepSeek(config['model'], max_tokens=2400), min(29, args.max_calls))

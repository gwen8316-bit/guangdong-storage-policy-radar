"""One-off, strictly two-page interpretation supplement; no backfill resume."""
import json
from pathlib import Path
from collector.http import Client, now
from collector.parsing import nea_data_url, parse_nea_list, parse_html_list
from collector.pipeline import fetch_policy, membership, RunLock
from collector.storage import Store, write_json

def main():
    root = Path('data')
    client = Client(root / 'logs' / 'interpretations-two-pages.jsonl', retries=0)
    store = Store(root)
    report = {'started_at': now(), 'columns': {}}
    columns = json.loads(Path('config/sources.json').read_text(encoding='utf-8'))['columns']
    for column in columns:
        if column['column_id'] not in ('nea_interpretations', 'nf_interpretations'):
            continue
        stats = report['columns'][column['column_id']] = {'new': 0, 'updated': 0, 'unchanged': 0, 'failed': 0, 'errors': []}
        url = column['url']
        found = []
        try:
            for page in range(2):
                html = client.text(url)
                if column['adapter'] == 'nea':
                    data_url = nea_data_url(html, url)
                    # Official jd.htm specifies pageSize: 25; JSON supplies all pages.
                    found = parse_nea_list(client.text(data_url), data_url)[:50]
                    break
                entries, url = parse_html_list(html, url, column['adapter'])
                found.extend(entries)
                if not url:
                    break
        except Exception as exc:
            stats['errors'].append(str(exc))
        stats['discovered'] = len(found)
        for entry in {e['url']: e for e in found}.values():
            new, errors = fetch_policy(client, entry, store.get(entry['url']))
            item, event = store.save(new, [membership(column, entry)])
            stats[event] += 1
            stats['errors'].extend(errors)
            print(json.dumps({'column': column['column_id'], 'title': item['title'], 'event': event}, ensure_ascii=False), flush=True)
            write_json(root / 'runs' / 'interpretations-two-pages.json', report)
        stats['stored'] = sum(column['column_id'] in p['column_ids'] for p in store.items.values())
    store.index()
    report.update(ended_at=now(), total=len(store.items))
    write_json(root / 'runs' / 'interpretations-two-pages.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    with RunLock('data'):
        main()

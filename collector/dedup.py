"""Logical policies retain every raw URL record and its collection checkpoint."""
import re
import unicodedata


def normalize_title(title):
    return re.sub(r'[\s\u200b\ufeff]+', '', unicodedata.normalize('NFKC', title)).translate(str.maketrans({'“': '"', '”': '"', '‘': "'", '’': "'"}))


def group_policies(policies, analyses):
    groups = {}
    for policy in policies.values():
        date = policy.get('publish_date')
        key = (normalize_title(policy['title']), date) if date else ('id', policy['id'])
        groups.setdefault(key, []).append(policy)
    result = []
    for members in groups.values():
        # Completed interpretation wins even if relevance is subsequently excluded.
        members.sort(key=lambda p: (not bool(analyses.get(p['id'], {}).get('interpretation')),
                                    p.get('content_status') != 'complete', p['id']))
        result.append({'canonical_id': members[0]['id'], 'member_ids': [p['id'] for p in members],
                       'source_links': [{'id': p['id'], 'url': p['url'], 'column_ids': p.get('column_ids', [])} for p in members]})
    return sorted(result, key=lambda group: group['canonical_id'])

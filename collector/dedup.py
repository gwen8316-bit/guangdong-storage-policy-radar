"""Group logical policies without changing raw files or AI decisions."""
import re
import unicodedata


def normalize_title(title):
    return re.sub(r'[\s\u200b\ufeff]+', '', unicodedata.normalize('NFKC', title)).translate(
        str.maketrans({'“': '"', '”': '"', '‘': "'", '’': "'"}))


def group_policies(policies, analyses):
    groups = {}
    for policy in policies.values():
        date = policy.get('publish_date')
        key = (normalize_title(policy['title']), date) if date else ('id', policy['id'])
        groups.setdefault(key, []).append(policy)
    result = []
    def priority(p):
        a = analyses.get(p['id'], {})
        completed = a.get('status') == 'complete' and bool(a.get('interpretation'))
        # Prefer successful extraction, then the amount of non-whitespace body text.
        return (not completed, p.get('content_status') != 'complete',
                -len(re.sub(r'\s+', '', p.get('content_text', ''))), p['id'])
    for members in groups.values():
        members.sort(key=priority)
        result.append({'canonical_id': members[0]['id'], 'member_ids': [p['id'] for p in members],
                       'source_links': [{'id': p['id'], 'url': p['url'],
                                         'column_ids': p.get('column_ids', [])} for p in members]})
    return sorted(result, key=lambda g: g['canonical_id'])

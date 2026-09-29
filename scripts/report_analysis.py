"""Refresh local statistics and the three-sample review document without API calls."""
import json
from pathlib import Path
from analysis.__main__ import prepare, fingerprint
from collector.storage import read_json


def main():
    root = Path('data')
    config = read_json(Path('config/analysis.json'), {})
    policies, summary = prepare(root, config)
    run = read_json(root / 'analysis-last-run.json', {})
    lines = ['# 新规则三份 DeepSeek 政策解读样例', '', 'AI 生成，以原文为准。', '',
             f"规则版本：{summary['rule_version']}；关键词命中 {summary['keyword_matches']} 条；最近运行 API 请求 {run.get('api_calls')} 次。", '']
    for pid in config['sample_ids']:
        record = read_json(root / 'analysis' / (pid + '.json'), {})
        assert record.get('input_hash') == fingerprint(policies[pid]), 'Sample not regenerated under current rules'
        lines += ['## ' + record['title'], '', '[原文](' + record['url'] + ')', '',
                  '相关性：' + str(record.get('relevance')) + '；状态：' + str(record.get('review_status')), '',
                  '```json', json.dumps(record.get('interpretation', record), ensure_ascii=False, indent=2), '```', '']
        if record.get('review_reasons'):
            lines += ['核查提示：' + '；'.join(record['review_reasons']), '']
    Path('docs/ai-samples.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'summary': summary, 'last_run': run}, ensure_ascii=False))


if __name__ == '__main__':
    main()

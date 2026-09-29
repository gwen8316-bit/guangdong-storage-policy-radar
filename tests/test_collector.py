import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collector.parsing import (parse_detail, parse_html_list, parse_nea_list, normalize_url, policy_id)
from collector.storage import Store, merge, content_hash
from collector.storage import write_json
from collector.pipeline import discover, fetch_policy
from collector.pipeline import run
from argparse import Namespace
from collector.http import Client, RequestError

FIXTURES = Path(__file__).parent / 'fixtures'
MANIFEST = {r['file']: r for r in json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))}


def fixture(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


def parsed(name):
    return parse_detail(fixture(name), MANIFEST[name]['url'], {'title': 'fallback'})


class ListTests(unittest.TestCase):
    def test_nea_real_json_excerpt_handles_embedded_link_title(self):
        entries = parse_nea_list(fixture('nea-list-excerpt.json'), 'https://www.nea.gov.cn/policy/zxwj.htm')
        self.assertEqual(entries[0]['title'], '关于披露中国能源传媒集团有限公司负责人2025年度薪酬情况的通知')
        self.assertEqual(entries[0]['list_date'], '2026-09-28')
        self.assertTrue(entries[0]['url'].startswith('https:'))

    def test_nf_real_page_and_zero_based_pagination(self):
        entries, next_url = parse_html_list(fixture('nf-list.html'), MANIFEST['nf-list.html']['url'], 'nf')
        self.assertEqual(len(entries), 15)
        self.assertEqual(entries[0]['list_date'], '2025-08-29')
        self.assertEqual(entries[1]['list_date'], '2026-09-21')
        self.assertTrue(next_url.endswith('/index_1.html'))

    def test_gd_real_page_and_one_based_pagination(self):
        entries, next_url = parse_html_list(fixture('gd-list.html'), MANIFEST['gd-list.html']['url'], 'gd')
        self.assertEqual(len(entries), 20)
        self.assertEqual(entries[0]['list_date'], '2026-09-24')
        self.assertTrue(next_url.endswith('/index_2.html'))

    def test_old_pinned_entry_does_not_stop_discovery(self):
        entries, _ = parse_html_list(fixture('nf-list.html'), MANIFEST['nf-list.html']['url'], 'nf')
        class FakeClient:
            def text(self, url):
                return fixture('nf-list.html')
        with tempfile.TemporaryDirectory() as temp, patch('collector.pipeline.parse_html_list', return_value=(entries, None)):
            state = {}
            found = discover(FakeClient(), {'url': MANIFEST['nf-list.html']['url'], 'adapter': 'nf', 'column_id': 'nf'},
                             Store(temp), '2025-10-01', 'backfill', state, lambda: None, 10)
            self.assertTrue(any(e['list_date'] == '2026-09-21' for e in found))
            self.assertFalse(any(e['list_date'] == '2025-08-29' for e in found))

    def test_challenge_is_not_empty_success(self):
        with self.assertRaises(ValueError):
            parse_html_list('<html>验证码</html>', 'https://example.test', 'gd')


class DetailTests(unittest.TestCase):
    def test_public_consultation_embedded_json_not_navigation_or_form(self):
        item = parsed('gd-consultation.html')
        self.assertEqual(item['publish_date'], '2026-09-09')
        self.assertEqual(item['written_date'], '2026-09-09')
        self.assertIn('远程异地评标', item['content_text'])
        self.assertNotIn('提交问卷', item['content_text'])
        self.assertEqual(len(item['attachment_metadata_urls']), 1)
        self.assertIsNone(item['doc_number'])

    def test_nea_written_date_not_publication_and_no_cited_doc_number(self):
        item = parsed('nea-detail.html')
        self.assertEqual(item['written_date'], '2026-09-16')
        self.assertIsNone(item['publish_date'])
        self.assertIsNone(item['doc_number'])  # cited 人社厅函 is not this document's number
        self.assertNotIn('目录项的基本信息', item['content_text'])
        self.assertNotIn('公开事项名称', item['content_text'])
        self.assertEqual(item['attachments'][0]['format'], 'xlsx')

    def test_gd_date_document_number_and_body(self):
        item = parsed('gd-detail.html')
        self.assertEqual(item['publish_date'], '2026-09-24')
        self.assertEqual(item['written_date'], '2026-09-07')
        self.assertEqual(item['doc_number'], '粤发改能源〔2026〕290号')
        self.assertIn('三、保障措施', item['content_text'])
        self.assertNotIn('相关导读', item['content_text'])
        self.assertNotIn('分享到', item['content_text'])
        self.assertEqual(item['attachments'][0]['format'], 'xls')

    def test_nf_relative_attachments_and_ui_removal(self):
        item = parsed('nf-detail.html')
        self.assertEqual(item['publish_date'], '2026-09-21')
        self.assertEqual(len(item['attachments']), 2)
        self.assertTrue(item['attachments'][0]['url'].endswith('/202609/P020260921321281443864.pdf'))
        self.assertNotIn('扫一扫', item['content_text'])
        self.assertNotIn('网站地图', item['content_text'])

    def test_image_only_no_fake_body(self):
        item = parsed('gd-image.html')
        self.assertEqual(item['content_status'], 'image_only')
        self.assertEqual(item['content_text'], '')
        self.assertEqual(len(item['attachments']), 3)

    def test_interpretation_is_not_issued_by_every_referenced_department(self):
        item = parsed('nea-interpretation.html')
        self.assertEqual(item['publish_date'], '2026-09-09')
        self.assertIsNone(item['doc_number'])
        self.assertIsNone(item['written_date'])
        self.assertEqual(item['attachments'], [])


class StorageTests(unittest.TestCase):
    def test_transient_windows_file_lock_retries_atomic_replace(self):
        import os
        original = os.replace
        attempts = []
        def flaky(source, target):
            attempts.append(1)
            if len(attempts) < 3:
                raise PermissionError('simulated transient reader lock')
            return original(source, target)
        with tempfile.TemporaryDirectory() as temp, patch('collector.storage.os.replace', side_effect=flaky), patch('collector.storage.time.sleep'):
            target = Path(temp) / 'result.json'
            write_json(target, {'complete': True})
            self.assertEqual(json.loads(target.read_text()), {'complete': True})
            self.assertEqual(len(attempts), 3)

    def setUp(self):
        self.new = parsed('nea-detail.html') | {'url': MANIFEST['nea-detail.html']['url']}
        self.one = {'source_id': 'nea', 'column_id': 'latest', 'list_date': '2026-09-28'}
        self.two = self.one | {'column_id': 'notices'}

    def test_stable_url_and_cross_column_merge(self):
        a = self.new['url']
        b = a.replace('http:', 'https:') + '?utm_source=test#body'
        self.assertEqual(policy_id(a), policy_id(b))
        first, _ = merge(None, self.new, [self.one])
        second, event = merge(first, self.new | {'url': b}, [self.two])
        self.assertEqual(second['id'], first['id'])
        self.assertEqual(len(second['columns']), 2)
        self.assertEqual(event, 'unchanged')
        self.assertEqual(second['versions'], [])
        self.assertEqual(second['first_seen_at'], first['first_seen_at'])

    def test_changed_body_appends_old_hash_once(self):
        first, _ = merge(None, self.new, [self.one])
        changed = self.new | {'content_text': self.new['content_text'] + '\n修订条款'}
        second, event = merge(first, changed, [self.two])
        self.assertEqual(event, 'updated')
        self.assertEqual(second['versions'][0]['old_content_hash'], first['content_hash'])
        third, _ = merge(second, changed, [self.one])
        self.assertEqual(len(third['versions']), 1)

    def test_failed_check_preserves_good_content(self):
        first, _ = merge(None, self.new, [self.one])
        failed = self.new | {'content_status': 'failed', 'content_text': '', 'last_fetch_error': 'HTTP 503'}
        second, event = merge(first, failed, [self.two])
        self.assertEqual(event, 'failed')
        self.assertEqual(second['content_text'], first['content_text'])
        self.assertEqual(second['versions'], [])

    def test_atomic_store_only_one_file(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            store.save(self.new, [self.one])
            store.save(self.new, [self.two])
            self.assertEqual(len(list((Path(temp) / 'policies').glob('*.json'))), 1)
            self.assertEqual(len(Store(temp).get(self.new['url'])['columns']), 2)

    def test_reserved_url_characters_and_identity_query_preserved(self):
        self.assertNotEqual(policy_id('https://example.test/a%2Fb'), policy_id('https://example.test/a/b'))
        self.assertNotEqual(policy_id('https://example.test/a?from=1'), policy_id('https://example.test/a?from=2'))
        self.assertEqual(normalize_url('https://EXAMPLE.test:443/%7ea#frag'), 'https://example.test/~a')

    def test_attachment_only_change_has_version(self):
        first, _ = merge(None, self.new, [self.one])
        changed = copy.deepcopy(self.new)
        changed['attachments'][0]['sha256'] = 'new-binary-hash'
        second, event = merge(first, changed, [self.one])
        self.assertEqual(event, 'updated')
        self.assertEqual(second['content_hash'], first['content_hash'])
        self.assertEqual(len(second['versions']), 1)


class NetworkAndIsolationTests(unittest.TestCase):
    def test_consultation_resolves_public_attachment_metadata(self):
        class FakeClient:
            def get(self, url, **kwargs):
                return {'url': url, 'body': fixture('gd-consultation.html').encode(), 'headers': {}}
            def text(self, url):
                return fixture('gd-consultation-attachment.json')
        with patch('collector.attachments.process', side_effect=lambda c,a: a | {'status': 'needs_manual_review'}):
            result, errors = fetch_policy(FakeClient(), {'url': MANIFEST['gd-consultation.html']['url'], 'title': 'fallback'}, None)
        self.assertEqual(errors, [])
        self.assertEqual(result['attachments'][0]['format'], 'doc')
        self.assertIn('/api/attachments/view/2395951001a82c0174ca1c6411c0a66a', result['attachments'][0]['url'])

    def test_mislabeled_pdf_link_returning_html_is_not_parsed_as_pdf(self):
        from collector.attachments import process
        class FakeClient:
            def get(self, url, **kwargs):
                return {'url': url, 'body': fixture('nea-attachment-landing.html').encode(), 'headers': {'content-type': 'text/html'}}
        result = process(FakeClient(), {'url': MANIFEST['nea-attachment-landing.html']['url'], 'format': 'pdf', 'name': 'label.pdf', 'text': ''})
        self.assertEqual(result['status'], 'needs_manual_review')
        self.assertEqual(result['format'], 'html')
        self.assertEqual(result['error'], 'attachment_link_returns_html')

    def test_one_bad_column_does_not_stop_other_columns(self):
        good_url = MANIFEST['gd-list.html']['url']
        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass
            def text(self, url):
                if 'deliberately-missing' in url:
                    raise RequestError('HTTP 404: deliberately missing column')
                return fixture('gd-list.html')
            def get(self, url, **kwargs):
                return {'url': url, 'body': fixture('gd-detail.html').encode(), 'headers': {}}
        entries, _ = parse_html_list(fixture('gd-list.html'), good_url, 'gd')
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'sources.json'
            config.write_text(json.dumps({'columns': [
                {'source_id': 'gd', 'column_id': 'bad', 'name': 'bad', 'adapter': 'gd', 'url': good_url + 'deliberately-missing'},
                {'source_id': 'gd', 'column_id': 'good', 'name': 'good', 'adapter': 'gd', 'url': good_url}]}), encoding='utf-8')
            args = Namespace(config=str(config), columns=None, data_dir=str(Path(temp) / 'data'), mode='backfill',
                             since='2025-10-01', batch_size=0, discover_only=False, workers=2, recheck_days=7, recheck_limit=20)
            with patch('collector.pipeline.Client', FakeClient), patch('collector.pipeline.parse_html_list', return_value=(entries, None)), \
                 patch('collector.attachments.process', side_effect=lambda c,a: a | {'status': 'needs_manual_review', 'error': 'legacy_file'}), \
                 patch('builtins.print'):
                summary = run(args)
            self.assertEqual(summary['columns']['bad']['failed'], 1)
            self.assertIn('HTTP 404', summary['columns']['bad']['errors'][0]['reason'])
            self.assertEqual(summary['columns']['good']['new'], 20)
            self.assertEqual(summary['columns']['good']['failed'], 0)
            status = json.loads((Path(temp) / 'data/status/columns.json').read_text(encoding='utf-8'))
            self.assertEqual(status['bad']['consecutive_failures'], 1)
            self.assertEqual(status['good']['status'], 'ok')

    def test_robots_wildcard_and_more_specific_allow(self):
        with tempfile.TemporaryDirectory() as temp:
            client = Client(Path(temp) / 'requests.jsonl')
            rules = b'User-agent: *\nDisallow: /*.pdf$\nAllow: /public/ok.pdf\nCrawl-delay: 5\n'
            with patch.object(client, 'raw', return_value={'status': 200, 'body': rules, 'headers': {}}):
                with self.assertRaisesRegex(RequestError, 'robots_disallowed'):
                    client.allowed('https://example.test/private/a.pdf')
                client.allowed('https://example.test/public/ok.pdf')
                self.assertEqual(client.delay['example.test'], 5)

    def test_backfill_page_checkpoint_can_resume(self):
        entries, _ = parse_html_list(fixture('gd-list.html'), MANIFEST['gd-list.html']['url'], 'gd')
        class FakeClient:
            def text(self, url):
                return fixture('gd-list.html')
        column = {'url': MANIFEST['gd-list.html']['url'], 'adapter': 'gd', 'column_id': 'gd'}
        checkpoint = {}
        def stop_after_save():
            raise InterruptedError('simulate interruption after atomic checkpoint')
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            with self.assertRaises(InterruptedError), patch('collector.pipeline.parse_html_list', return_value=(entries, 'https://drc.gd.gov.cn/ywtz/index_2.html')):
                discover(FakeClient(), column, store, '2025-10-01', 'backfill', checkpoint, stop_after_save, 10)
            self.assertEqual(checkpoint['next_url'], 'https://drc.gd.gov.cn/ywtz/index_2.html')
            with patch('collector.pipeline.parse_html_list', return_value=(entries, None)):
                result = discover(FakeClient(), column, store, '2025-10-01', 'backfill', checkpoint, lambda: None, 10)
            self.assertEqual(len(result), 20)
            self.assertTrue(checkpoint['complete'])

    def test_robots_denial_never_fetches_page(self):
        with tempfile.TemporaryDirectory() as temp:
            client = Client(Path(temp) / 'requests.jsonl')
            with patch.object(client, 'raw', return_value={'status': 200, 'body': b'User-agent: *\nDisallow: /\n', 'headers': {}}) as mock:
                with self.assertRaisesRegex(RequestError, 'robots_disallowed'):
                    client.get('https://example.test/page')
                self.assertEqual(mock.call_count, 1)

    def test_attachment_failure_preserves_detail(self):
        class FakeClient:
            def get(self, url, **kwargs):
                return {'url': url, 'body': fixture('nf-detail.html').encode(), 'headers': {}}
        with patch('collector.attachments.process', side_effect=lambda c,a: a | {'status': 'failed', 'error': 'test failure'}):
            result, errors = fetch_policy(FakeClient(), {'url': MANIFEST['nf-detail.html']['url'], 'title': 'sample'}, None)
            self.assertEqual(result['content_status'], 'complete')
            self.assertIn('行政许可', result['content_text'])
            self.assertEqual(len(errors), 2)


if __name__ == '__main__':
    unittest.main()

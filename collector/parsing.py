"""Pure parsers; no network I/O. Preserve evidence instead of guessing dates."""
import copy
import hashlib
import json
import re
import urllib.parse
from datetime import date
from pathlib import PurePosixPath
from lxml import html, etree
from html import escape

DATE = re.compile(r'(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})日?')
FILE_EXTS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'zip', 'rar', '7z', 'jpg', 'jpeg', 'png', 'gif', 'tif', 'tiff', 'bmp', 'wps', 'ppt', 'pptx'}
MANUAL_EXTS = FILE_EXTS - {'pdf', 'docx', 'xlsx'}


def clean(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def iso_date(value):
    m = DATE.search(value or '')
    if m:
        try:
            return date(*map(int, m.groups())).isoformat()
        except ValueError:
            pass
    return None


def title_issuer(title):
    match = re.match(r'^(国家能源局南方监管局|国家能源局综合司|国家能源局|广东省发展和改革委员会|广东省发展改革委|广东省能源局|南方能源监管局|国家发展和改革委员会|国家发展改革委|广东省人民政府)\s*(?=关于|行政许可通告|公告|通告|通知|公示|令)', title)
    return match.group(1) if match else None


def title_doc_number(title):
    match = re.search(r'国家能源局公告\s*20\d{2}年第\d+号', title)
    return clean(match.group()) if match else None


def normalize_url(url):
    parts = urllib.parse.urlsplit(url.strip())
    scheme, host = parts.scheme.lower(), (parts.hostname or '').lower()
    original_scheme = scheme
    if scheme not in ('http', 'https') or not host or parts.username:
        raise ValueError(f'Invalid public HTTP URL: {url}')
    # These official hosts serve identical HTTP/HTTPS article paths (verified).
    if host in ('www.nea.gov.cn', 'nfj.nea.gov.cn', 'drc.gd.gov.cn'):
        scheme = 'https'
    port = parts.port
    default_port = 80 if original_scheme == 'http' else 443
    netloc = host if port in (None, default_port) else f'{host}:{port}'
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith('utm_')]
    unreserved = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~'
    path = re.sub(r'%([0-9A-Fa-f]{2})', lambda m: chr(int(m.group(1), 16)) if chr(int(m.group(1), 16)) in unreserved else m.group().upper(), parts.path or '/')
    path = urllib.parse.quote(path, safe="/:@!$&'()*+,;=-._~%")
    return urllib.parse.urlunsplit((scheme, netloc, path, urllib.parse.urlencode(sorted(query, key=lambda p: p[0])), ''))


def policy_id(url):
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()


def class_xpath(name):
    return f"//*[contains(concat(' ',normalize-space(@class),' '),' {name} ')]"


def document(text):
    doc = html.fromstring(text)
    for n in doc.xpath('//script|//style|//noscript'):
        n.drop_tree()
    return doc


def nea_data_url(markup, url):
    doc = html.fromstring(markup)
    nodes = doc.xpath('//*[@id="showData0"][@data]')
    if not nodes:
        raise ValueError('NEA datasource node missing')
    identifier = nodes[0].get('data').split(':')[-1]
    if not re.fullmatch('[a-f0-9]{32}', identifier):
        raise ValueError('Invalid NEA datasource identifier')
    return urllib.parse.urljoin(url, f'ds_{identifier}.json')


def parse_nea_list(text, url):
    entries = []
    for item in json.loads(text)['datasource']:
        title_doc = html.fromstring('<div>' + (item.get('showTitle') or item.get('title') or '') + '</div>')
        link = item.get('publishUrl') or next(iter(title_doc.xpath('.//a/@href')), '')
        if link:
            try:
                link = normalize_url(urllib.parse.urljoin(url, link))
            except ValueError:
                continue
            entries.append({'url': link, 'title': clean(title_doc.text_content()),
                            'list_date': iso_date(item.get('publishTime')),
                            'list_date_raw': item.get('publishTime')})
    # Pinned links must not terminate a chronological backfill early.
    return sorted(entries, key=lambda e: e['list_date'] or '9999', reverse=True)


def parse_html_list(text, url, adapter):
    doc = document(text)
    entries = []
    for row in doc.xpath('//li'):
        dated = DATE.search(clean(row.text_content()))
        if not dated:
            continue
        for a in row.xpath('.//a[@href]'):
            title = clean(a.get('title') or a.text_content())
            title = DATE.sub('', title).strip(' []')
            try:
                link = normalize_url(urllib.parse.urljoin(url, a.get('href')))
            except ValueError:
                continue
            if len(title) > 8:
                entries.append({'url': link, 'title': title, 'list_date': iso_date(dated.group()),
                                'list_date_raw': dated.group()})
                break
    entries = list({e['url']: e for e in entries}.values())
    if not entries:
        raise ValueError('No dated policy entries found; page may be blocked or template changed')
    next_url = None
    if adapter == 'nf':
        current = re.search(r'currentPage\s*=\s*Number\(["\x27](\d+)', text)
        count = re.search(r'countPage\s*=\s*Number\(["\x27](\d+)', text)
        if not (current and count):
            raise ValueError('NF pagination metadata missing')
        if int(current.group(1)) + 1 < int(count.group(1)):
            next_url = urllib.parse.urljoin(url, f'index_{int(current.group(1)) + 1}.html')
    else:
        for a in doc.xpath('//a[@href]'):
            if clean(a.text_content()) == '下一页':
                next_url = urllib.parse.urljoin(url, a.get('href'))
                break
    return entries, next_url


def visible_text(node):
    node = copy.deepcopy(node)
    for n in node.xpath('.//script|.//style|.//noscript'):
        n.drop_tree()
    # Preserve paragraph/table boundaries; do not concatenate numbers from cells.
    for n in node.iter():
        if n.tag in ('p', 'div', 'br', 'tr', 'li', 'h1', 'h2', 'h3'):
            n.tail = '\n' + (n.tail or '')
        elif n.tag in ('td', 'th'):
            n.tail = '\t' + (n.tail or '')
    return '\n'.join(filter(None, (clean(line) for line in node.text_content().splitlines())))


def attachments_in(root, url):
    result = {}
    for a in root.xpath('.//a[@href] | .//img[@src]'):
        image = a.tag == 'img'
        raw = a.get('src') if image else a.get('href')
        if image and ('fileTypeImages/' in raw or a.get('needdownload') == 'false'):
            continue
        try:
            link = normalize_url(urllib.parse.urljoin(url, raw))
        except ValueError:
            continue
        path = urllib.parse.unquote(urllib.parse.urlsplit(link).path)
        ext = PurePosixPath(path).suffix.lstrip('.').lower()
        name = clean(a.get('download') or a.get('title') or a.get('alt') or a.text_content())
        if ext not in FILE_EXTS:
            name_ext = PurePosixPath(name).suffix.lstrip('.').lower()
            if name_ext in FILE_EXTS:
                ext = name_ext
            elif a.get('appendix') == 'true' or a.get('download'):
                ext = 'unknown'
            else:
                continue
        result[link] = {'name': name or PurePosixPath(path).name, 'url': link, 'format': ext,
                        'kind': 'inline_image' if image else 'attachment', 'size_bytes': None,
                        'sha256': None, 'status': 'pending', 'text': '', 'error': None}
    return list(result.values())


def parse_detail(text, url, entry):
    embedded = re.search(r'\bquestion_data\s*:\s*', text)
    if embedded and '/hdjlpt/yjzj/' in url:
        payload, _ = json.JSONDecoder().raw_decode(text[embedded.end():])
        article = payload['article']
        rendered = ('<html><head><meta name="ArticleTitle" content="' + escape(article.get('title') or entry['title'], quote=True)
                    + '"><meta name="PubDate" content="' + escape(article.get('published_at') or '', quote=True)
                    + '"></head><body><div id="content1">' + article['content'] + '</div></body></html>')
        result = parse_detail(rendered, url, entry)
        result['body_selector'] = 'window._CONFIG.question_data.article.content'
        if result['publish_date']:
            result['field_evidence']['publish_date'] = {'json_field': 'question_data.article.published_at', 'value': article['published_at']}
        result['attachment_metadata_urls'] = [urllib.parse.urljoin(url, '/hdjlpt/yjzj/api/attachments/' + str(fid))
                                              for fid in article.get('attachments', []) if fid and re.fullmatch('[a-f0-9]{32}', str(fid))]
        return result
    doc = document(text)
    meta = {m.get('name', '').lower(): m.get('content') or '' for m in doc.xpath('//meta[@name]')}
    title = clean(meta.get('articletitle'))
    if not title:
        candidates = doc.xpath(class_xpath('wrapper_deatil_title') + '|//h1')
        title = clean(candidates[0].text_content()) if candidates else entry['title']
    selectors = ["//*[@id='detailContent']", "//*[@id='content1']", class_xpath('TRS_UEDITOR'),
                 class_xpath('TRS_Editor'), "//*[@id='UCAP-CONTENT']", "//*[@id='zoom']"]
    root, selected = None, None
    for selector in selectors:
        nodes = doc.xpath(selector)
        if nodes:
            root, selected = copy.deepcopy(nodes[0]), selector
            break
    if root is None:
        raise ValueError('Article body container not recognized; refusing whole-page text')
    files = attachments_in(root, url)
    for n in root.xpath('.//*[@id="xxddk"]|.//*[contains(concat(" ",@class," ")," xgdd ")]'):
        n.drop_tree()
    for n in root.xpath('.//*[contains(concat(" ",@class," ")," fjlis ")]'):
        # Attachment links already captured; remove surrounding UI label.
        n.drop_tree()
    content = visible_text(root)
    images = [a for a in files if a['kind'] == 'inline_image']
    status = 'image_only' if images and len(content) < 40 else ('partial' if images or len(content) < 30 else 'complete')
    if not content and not images and not files:
        raise ValueError('Empty article body')
    evidence = {}
    publish_date, written_date = None, None
    # Explicit metadata-table labels, not arbitrary dates in referenced documents.
    for tr in doc.xpath('//tr'):
        cells = tr.xpath('./td|./th')
        for i, cell in enumerate(cells[:-1]):
            label = clean(cell.text_content()).rstrip(':：')
            value = clean(cells[i + 1].text_content())
            if label in ('制发日期', '成文日期', '签发日期') and iso_date(value):
                written_date = iso_date(value)
                evidence['written_date'] = {'label': label, 'value': value}
            if label in ('发布日期', '发布时间') and iso_date(value):
                publish_date = iso_date(value)
                evidence['publish_date'] = {'label': label, 'value': value}
    # Only inspect visible header dates, never the entire article for publication.
    for selector in [class_xpath('wrapper_deatil_date'), class_xpath('jbxx'), class_xpath('article-info')]:
        nodes = doc.xpath(selector)
        if nodes:
            value = clean(nodes[0].text_content())
            d = iso_date(value)
            if d:
                publish_date = d
                evidence['publish_date'] = {'selector': selector, 'value': value[:250]}
                break
    if not publish_date:
        # NEA's PubDate can be the written date on formal-file templates.
        if not written_date:
            publish_date = iso_date(meta.get('pubdate') or meta.get('publishdate'))
            if publish_date:
                evidence['publish_date'] = {'meta': 'PubDate/publishdate', 'value': meta.get('pubdate') or meta.get('publishdate')}
    # A standalone right-aligned signing date with an adjacent issuer signature.
    issuer = None
    paragraphs = root.xpath('.//p')
    org_pattern = re.compile(r'(?:国家|广东省|中国人民银行|国家能源局|南方能源监管局)[^，。；：:《》]{0,65}(?:局|厅|委员会|委|部|办公室|分行|人民政府|司)$')
    for i, p in enumerate(paragraphs):
        value = clean(p.text_content())
        if DATE.fullmatch(value) and ('right' in p.get('style', '') or p.get('align') == 'right'):
            organizations = []
            for prior in paragraphs[max(0, i - 6):i]:
                val = clean(prior.text_content())
                if ('right' in prior.get('style', '') or prior.get('align') == 'right') and org_pattern.fullmatch(val):
                    organizations.append(val)
            if organizations:
                if not written_date:
                    written_date = iso_date(value)
                    evidence['written_date'] = {'label': 'signature_date', 'value': value}
                issuer = '；'.join(organizations)
                evidence['issuer'] = {'label': 'signature', 'value': issuer}
                break
    if not issuer:
        prefix = title.split('关于', 1)[0]
        if len(prefix) < 70 and org_pattern.fullmatch(prefix):
            issuer = prefix
            evidence['issuer'] = {'label': 'title_prefix', 'value': prefix}
    if not issuer and title_issuer(title):
        issuer = title_issuer(title)
        evidence['issuer'] = {'label': 'explicit_issuer_in_title', 'value': issuer}
    doc_number = None
    number_pattern = re.compile(r'[\u4e00-\u9fffA-Za-z]{1,20}(?:〔|\[|［|\()20\d{2}(?:〕|\]|］|\))\s*\d+号')
    for line in content.splitlines()[:15]:
        if number_pattern.fullmatch(line):
            doc_number = line
            evidence['doc_number'] = {'label': 'standalone_header', 'value': line}
            break
    if not doc_number and title_doc_number(title):
        doc_number = title_doc_number(title)
        evidence['doc_number'] = {'label': 'announcement_number_in_title', 'value': doc_number}
    return {'title': title, 'doc_number': doc_number, 'issuer': issuer,
            'publish_date': publish_date, 'written_date': written_date,
            'content_text': content, 'content_status': status, 'attachments': files,
            'field_evidence': evidence, 'body_selector': selected,
            'date_metadata': {k: v for k, v in meta.items() if 'date' in k or 'time' in k}}

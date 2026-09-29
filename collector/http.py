"""Robots-aware, domain-paced requests; redirects never bypass robots."""
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from protego import Protego
from datetime import datetime, timezone

UA = 'GuangdongStoragePolicyRadar/1.0 (+https://github.com/gwen8316-bit/guangdong-storage-policy-radar)'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def decode(body, content_type=''):
    import re
    m = re.search(r'charset\s*=\s*["\x27]?([\w-]+)', content_type + body[:4096].decode('ascii', 'ignore'), re.I)
    for encoding in ([m.group(1)] if m else []) + ['utf-8', 'gb18030']:
        try:
            return body.decode(encoding)
        except (UnicodeError, LookupError):
            pass
    raise ValueError('Unable to decode document without replacement characters')


class RequestError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, log_path, interval=3, retries=3, timeout=30):
        self.interval = max(3, interval)
        self.retries = retries
        self.timeout = timeout
        self.log_path = log_path
        self.guard = threading.RLock()
        self.robots_guard = threading.RLock()
        self.locks, self.last, self.robots = {}, {}, {}
        self.delay = {}
        log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, **record):
        with self.guard, self.log_path.open('a', encoding='utf-8') as out:
            out.write(json.dumps({'time': now(), **record}, ensure_ascii=False) + '\n')

    def raw(self, url, method='GET', max_bytes=80 * 1024 * 1024):
        host = urllib.parse.urlsplit(url).hostname
        if not host or urllib.parse.urlsplit(url).scheme not in ('http', 'https'):
            raise RequestError(f'Unsupported URL: {url}')
        with self.guard:
            lock = self.locks.setdefault(host, threading.Lock())
        for attempt in range(self.retries + 1):
            error, retry_after = None, 0
            with lock:
                time.sleep(max(0, self.delay.get(host, self.interval) - (time.monotonic() - self.last.get(host, 0))))
                self.last[host] = started = time.monotonic()
                try:
                    req = urllib.request.Request(url, method=method, headers={
                        'User-Agent': UA, 'Accept': '*/*', 'Accept-Language': 'zh-CN,zh;q=0.9'})
                    try:
                        response = urllib.request.build_opener(NoRedirect).open(req, timeout=self.timeout)
                    except urllib.error.HTTPError as exc:
                        response = exc
                    with response:
                        status = response.code
                        headers = {k.lower(): v for k, v in response.headers.items()}
                        if int(headers.get('content-length', '0') or 0) > max_bytes and method != 'HEAD':
                            raise RequestError(f'Attachment exceeds {max_bytes} byte limit')
                        body = response.read(max_bytes + 1)
                        if len(body) > max_bytes:
                            raise RequestError(f'Response exceeds {max_bytes} byte limit')
                    self.log(url=url, method=method, status=status, attempt=attempt + 1,
                             seconds=round(time.monotonic() - started, 3), size_bytes=len(body))
                    if status not in (408, 429) and status < 500:
                        return {'url': url, 'status': status, 'headers': headers, 'body': body}
                    error = f'HTTP {status}'
                    try:
                        retry_after = float(headers.get('retry-after', 0))
                    except ValueError:
                        from email.utils import parsedate_to_datetime
                        try:
                            retry_after = max(0, (parsedate_to_datetime(headers['retry-after']) - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError, KeyError):
                            pass
                except RequestError:
                    raise
                except Exception as exc:
                    error = f'{type(exc).__name__}: {exc}'
                    self.log(url=url, method=method, attempt=attempt + 1, error=error,
                             seconds=round(time.monotonic() - started, 3))
            if attempt < self.retries:
                time.sleep(max(2 ** attempt, retry_after))
        raise RequestError(f'{url}: failed after {self.retries + 1} attempts: {error}')

    def allowed(self, url):
        parts = urllib.parse.urlsplit(url)
        origin = f'{parts.scheme}://{parts.netloc}'
        # Reentrant lock prevents duplicate robots requests from worker threads.
        with self.robots_guard:
            cached = self.robots.get(origin)
            if cached and time.monotonic() - cached[0] < 1800:
                policy = cached[1]
            else:
                robots_url = origin + '/robots.txt'
                response = self.raw(robots_url, max_bytes=2 * 1024 * 1024)
                # Fail closed on redirect, 403, malformed HTML or transient error.
                if response['status'] in (404, 410):
                    policy = None
                elif response['status'] == 200:
                    text = decode(response['body'], response['headers'].get('content-type', ''))
                    if '<html' in text.lower() or '<!doctype' in text.lower():
                        raise RequestError('robots_unavailable: HTML challenge instead of robots.txt')
                    policy = Protego.parse(text)
                    delay = policy.crawl_delay(UA) or 0
                    rate = policy.request_rate(UA)
                    if rate and rate.requests:
                        delay = max(delay, rate.seconds / rate.requests)
                    self.delay[parts.hostname] = max(self.interval, delay)
                else:
                    raise RequestError(f'robots_unavailable: HTTP {response["status"]} at {robots_url}')
                self.log(kind='robots', url=robots_url, status=response['status'],
                         sha256=hashlib.sha256(response['body']).hexdigest(),
                         rules=decode(response['body']) if response['status'] == 200 else None)
                self.robots[origin] = (time.monotonic(), policy)
            if policy and not policy.can_fetch(url, UA):
                self.log(kind='robots_denied', url=url)
                raise RequestError(f'robots_disallowed: {url}')

    def get(self, url, method='GET', max_bytes=80 * 1024 * 1024):
        visited = set()
        for _ in range(6):
            if url in visited:
                raise RequestError(f'Redirect loop: {url}')
            visited.add(url)
            self.allowed(url)
            response = self.raw(url, method, max_bytes)
            if response['status'] in (301, 302, 303, 307, 308):
                target = response['headers'].get('location')
                if not target:
                    raise RequestError('Redirect without Location')
                url = urllib.parse.urljoin(url, target)
                continue
            if response['status'] != 200:
                raise RequestError(f'HTTP {response["status"]}: {url}')
            return response
        raise RequestError(f'Too many redirects: {url}')

    def text(self, url):
        response = self.get(url, max_bytes=16 * 1024 * 1024)
        return decode(response['body'], response['headers'].get('content-type', ''))

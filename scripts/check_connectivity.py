"""Read-only list/detail connectivity probe; no production crawling or AI."""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from lxml import html

USER_AGENT = "GuangdongStoragePolicyRadar/0.1 (public-policy connectivity check)"
LAST_REQUEST = 0.0


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []
        self.links = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        if tag == "a" and dict(attrs).get("href"):
            self.links += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def fetch(url, interval=3.0):
    global LAST_REQUEST
    time.sleep(max(0, interval - (time.monotonic() - LAST_REQUEST)))
    LAST_REQUEST = time.monotonic()
    started = time.monotonic()
    result = {"url": url, "status_code": None, "error": None}
    body = b""
    headers = {}
    try:
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        try:
            response = urllib.request.build_opener(NoRedirect).open(request, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            result["status_code"] = response.code
            headers = dict(response.headers.items())
            body = response.read(4 * 1024 * 1024 + 1)
            result["truncated"] = len(body) > 4 * 1024 * 1024
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["response_seconds"] = round(time.monotonic() - started, 3)
    result["bytes"] = len(body)
    result["headers"] = {k.lower(): v for k, v in headers.items()
                         if k.lower() in ("content-type", "location", "retry-after")}
    if result["status_code"] in (301, 302, 303, 307, 308):
        result["error"] = "Redirect not followed; review target and its robots rules first"
    return result, body


def decode(body, content_type=""):
    declared = re.search(r"charset\s*=\s*[\"']?([\w-]+)",
                         content_type + body[:4096].decode("ascii", "ignore"), re.I)
    for encoding in ([declared.group(1)] if declared else []) + ["utf-8", "gb18030"]:
        try:
            return body.decode(encoding), encoding
        except (UnicodeError, LookupError):
            pass
    return body.decode("utf-8", "replace"), "utf-8-with-replacement"


def probe(url, include_html=False):
    parsed = urllib.parse.urlsplit(url)
    robots_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
    robots, body = fetch(robots_url)
    robots["text_preview"] = decode(body)[0][:4000]
    robots["sha256"] = hashlib.sha256(body).hexdigest()
    result = {"url": url, "robots": robots, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    interval = 3.0
    if robots["status_code"] in (404, 410):
        result["robots_decision"] = "no_robots_file"
        result["robots_allowed"] = True
    elif robots["status_code"] == 200 and not robots.get("truncated"):
        robots_text, _ = decode(body)
        if "<html" in robots_text.lower() or "<!doctype" in robots_text.lower():
            return {**result, "outcome": "skipped_invalid_robots_response"}
        parser = urllib.robotparser.RobotFileParser(robots_url)
        parser.parse(robots_text.splitlines())
        if not parser.can_fetch(USER_AGENT, url):
            return {**result, "robots_allowed": False, "outcome": "skipped_robots_disallowed"}
        interval = max(interval, parser.crawl_delay(USER_AGENT) or 0)
        rate = parser.request_rate(USER_AGENT)
        if rate and rate.requests:
            interval = max(interval, rate.seconds / rate.requests)
        result["robots_decision"] = "allowed"
        result["robots_allowed"] = True
    else:
        return {**result, "outcome": "skipped_robots_unavailable"}
    page, body = fetch(url, interval)
    text, encoding = decode(body, page["headers"].get("content-type", ""))
    parser = PageText()
    parser.feed(text)
    visible = "\n".join(parser.parts)
    markers = [m for m in ("验证码", "访问过于频繁", "访问被拒绝", "Access Denied", "verify you are human")
               if m.lower() in visible.lower()]
    candidate = (page["status_code"] == 200 and len(visible) >= 100
                 and parser.links >= 3 and not markers and not page.get("truncated"))
    result.update({"page": page, "encoding": encoding,
                   "text_characters": len(visible), "link_count": parser.links,
                   "block_page_markers": markers, "body_sha256": hashlib.sha256(body).hexdigest(),
                   "text_preview": visible[:3000], "list_content_candidate": candidate,
                   "outcome": "needs_manual_content_check" if candidate else "not_confirmed"})
    if include_html and page["status_code"] == 200:
        result["_html"] = text
    return result


DATE = re.compile(r"20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2}日?")


def clean(value):
    return " ".join(value.split())


def check_source(source):
    result = probe(source["url"], include_html=True)
    result["name"] = source["name"]
    markup = result.pop("_html", None)
    if not markup:
        return result
    doc = html.fromstring(markup)
    result["page_title"] = clean(" ".join(doc.xpath("//title/text()")))
    entries = []
    # NEA's published page script resolves datasource IDs to adjacent JSON files.
    if urllib.parse.urlsplit(source["url"]).hostname == "www.nea.gov.cn":
        nodes = doc.xpath('//*[@id="showData0"][@data]')
        if nodes:
            node = nodes[0]
            identifier = node.get("data", "").split(":")[-1]
            if re.fullmatch(r"[a-f0-9]{32}", identifier) and node.get("preview") == "ds_":
                data_url = urllib.parse.urljoin(source["url"], f"ds_{identifier}.json")
                data_probe = probe(data_url, include_html=True)
                data_text = data_probe.pop("_html", None)
                result["list_data_request"] = data_probe
                if data_text:
                    try:
                        for item in json.loads(data_text).get("datasource", []):
                            title = clean(html.fromstring("<div>" + item.get("showTitle", "") + "</div>").text_content())
                            link = item.get("publishUrl", "")
                            if link and title:
                                entries.append({"title": title, "date": item.get("publishTime"),
                                                "url": urllib.parse.urljoin(source["url"], link)})
                    except (ValueError, TypeError) as exc:
                        result["list_parse_error"] = str(exc)
    else:
        for row in doc.xpath("//li"):
            date = DATE.search(clean(row.text_content()))
            if not date:
                continue
            for anchor in row.xpath(".//a[@href]"):
                title = clean(anchor.get("title") or anchor.text_content())
                title = DATE.sub("", title).strip(" []")
                link = urllib.parse.urljoin(source["url"], anchor.get("href"))
                if len(title) > 8 and urllib.parse.urlsplit(link).scheme in ("https", "http"):
                    entries.append({"title": title, "date": date.group(), "url": link})
                    break
    entries = list({entry["url"]: entry for entry in entries}.values())
    result["parsed_entry_count"] = len(entries)
    result["list_sample"] = entries[:3]
    result["list_fields_ok"] = bool(entries and all(entries[0].get(k) for k in ("title", "date", "url")))
    if not entries:
        result["outcome"] = "list_not_parsed"
        return result
    # Prefer a same-host detail, avoiding unrelated external destinations.
    sample = next((e for e in entries if urllib.parse.urlsplit(e["url"]).hostname ==
                   urllib.parse.urlsplit(source["url"]).hostname), entries[0])
    detail = probe(sample["url"], include_html=True)
    detail["list_entry"] = sample
    detail_markup = detail.pop("_html", None)
    if detail_markup:
        detail_doc = html.fromstring(detail_markup)
        for element in detail_doc.xpath("//script | //style | //noscript"):
            element.drop_tree()
        meta = {m.get("name", "").lower(): m.get("content", "") for m in detail_doc.xpath("//meta[@name]")}
        detail["article_title"] = meta.get("articletitle") or clean(" ".join(detail_doc.xpath("//h1//text()")))
        if not detail["article_title"]:
            detail["article_title"] = clean(" ".join(detail_doc.xpath("//title/text()")))
        detail["article_date"] = meta.get("pubdate") or meta.get("publishtime")
        selectors = ["//*[@id='content1']", "//*[@id='zoom']", "//*[@id='UCAP-CONTENT']",
                     "//*[contains(concat(' ',normalize-space(@class),' '),' article-content ')]",
                     "//*[contains(concat(' ',normalize-space(@class),' '),' TRS_Editor ')]",
                     "//*[contains(concat(' ',normalize-space(@class),' '),' TRS_UEDITOR ')]"]
        detail["body_found"] = False
        for selector in selectors:
            nodes = detail_doc.xpath(selector)
            if nodes:
                body_text = clean(nodes[0].text_content())
                detail["body_image_count"] = len(nodes[0].xpath(".//img"))
                detail["body_characters"] = len(body_text)
                if len(body_text) >= 50:
                    detail.update({"body_found": True, "body_selector": selector,
                                   "body_characters": len(body_text), "body_preview": body_text[:2500]})
                    break
        if not detail["body_found"] and detail.get("body_image_count"):
            detail["body_limitation"] = "image_based_content_no_ocr"
        if not detail.get("article_date"):
            dates = DATE.findall(clean(detail_doc.text_content()))
            detail["article_date_candidates"] = dates[:5]
            if dates:
                detail["article_date"] = dates[0]
                detail["article_date_method"] = "first_visible_date_requires_review"
    result["detail"] = detail
    result["outcome"] = "sample_body_extracted" if detail.get("body_found") else "detail_not_confirmed"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="config/connectivity-sources.json")
    parser.add_argument("--urls-json", help='Optional JSON array overriding configured list-page URLs')
    parser.add_argument("--attempts", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--output", default="reports/connectivity.json")
    args = parser.parse_args()
    sources = ([{"name": u, "url": u} for u in json.loads(args.urls_json)] if args.urls_json
               else json.loads(Path(args.sources).read_text(encoding="utf-8")))
    urls = [s["url"] for s in sources]
    if not isinstance(urls, list) or not urls or not all(
        isinstance(u, str) and urllib.parse.urlsplit(u).scheme in ("http", "https")
        and urllib.parse.urlsplit(u).hostname and not urllib.parse.urlsplit(u).username for u in urls
    ):
        parser.error("Provide a nonempty JSON array of HTTP(S) URLs without credentials")
    records = []
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, args.attempts + 1):
        for source in sources:
            try:
                result = check_source(source)
            except Exception as exc:
                result = {**source, "outcome": "probe_error", "error": f"{type(exc).__name__}: {exc}"}
            result["attempt"] = attempt
            records.append(result)
            print(json.dumps({k: result.get(k) for k in ("name", "attempt", "outcome", "parsed_entry_count")}, ensure_ascii=False), flush=True)
            output.write_text(json.dumps({"environment": "github-actions" if os.getenv("GITHUB_ACTIONS") else "local",
                                          "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

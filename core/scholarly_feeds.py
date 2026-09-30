"""On-demand, fixed-provider scholarly feed metadata; no article body downloads."""
# [작성: 0 이영 · Codex] 2026-10-01T00:39:32.3171675+09:00, 담당 버전 0.
# 수정 이유: 논문·국내 과학정보 RSS를 고정 주소로 수집하고 발행/관측 시각과 지문을 구분한다.
# 영향/검증: 이 모듈과 mock RSS/Atom 회귀시험; 실제 GET 성공은 호출 응답으로만 표시한다.
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from core.integration_http import get_xml

ATOM = "http://www.w3.org/2005/Atom"
PROVIDERS = {
    "arxiv": {
        "label": "arXiv · cs.LG / stat.ML / stat.ME",
        "host": "rss.arxiv.org", "path": "/rss/cs.LG+stat.ML+stat.ME", "params": None,
        "url": "https://rss.arxiv.org/rss/cs.LG+stat.ML+stat.ME",
        "link_hosts": frozenset({"arxiv.org", "www.arxiv.org"}),
        "documentation_url": "https://info.arxiv.org/help/rss.html",
        "publication_meaning": "arXiv announcement date; preprint metadata, peer review unverified",
    },
    "biorxiv": {
        "label": "bioRxiv · bioinformatics",
        "host": "connect.biorxiv.org", "path": "/biorxiv_xml.php", "params": {"subject": "bioinformatics"},
        "url": "https://connect.biorxiv.org/biorxiv_xml.php?subject=bioinformatics",
        "link_hosts": frozenset({"biorxiv.org", "www.biorxiv.org"}),
        "documentation_url": "https://www.medrxiv.org/alertsrss",
        "publication_meaning": "preprint posting date; peer review unverified",
    },
    "kisti": {
        "label": "KISTI · DATA INSIGHT",
        "host": "www.kisti.re.kr", "path": "/rss/data-insight", "params": None,
        "url": "https://www.kisti.re.kr/rss/data-insight",
        "link_hosts": frozenset({"www.kisti.re.kr", "kisti.re.kr"}),
        "documentation_url": "https://www.kisti.re.kr/rss-help/pageView/178",
        "publication_meaning": "KISTI item publication date; contextual information, scholarly validation unverified",
    },
}


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag.rsplit(":", 1)[-1].lower() in {"script", "style", "iframe", "object"}:
            self.blocked += 1

    def handle_endtag(self, tag):
        if tag.rsplit(":", 1)[-1].lower() in {"script", "style", "iframe", "object"} and self.blocked:
            self.blocked -= 1

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def _plain(value, maximum=500):
    parser = _TextOnly()
    parser.feed(unescape(value or ""))
    parser.close()
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()[:maximum]


def _tag(element):
    return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""


def _child(element, name):
    return next((child for child in element if _tag(child) == name), None)


def _text(element, name, maximum=500):
    child = _child(element, name)
    if child is None:
        return ""
    # [수정: 0 이영 · Codex] 2026-10-01T00:52:24.4173154+09:00 — CDATA 재직렬화로 HTML이 이중 인코딩되는 오류를 방지한다.
    # Preserve inner text and child markup so script/style contents remain removable; never include the outer title tag.
    inner = (child.text or "") + "".join(ET.tostring(part, encoding="unicode") for part in child)
    return _plain(inner, maximum)


def _safe_link(value, source):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (not value or len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value)
            or any(c in value for c in ('\\', '<', '>', '"', "'"))):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() != "https" or parsed.hostname not in source["link_hosts"]
                or parsed.port not in (None, 443) or parsed.username or parsed.password):
            return None
        # Fragments and redundant port 443 do not create distinct feed entries.
        return urlunsplit(("https", parsed.hostname, parsed.path, parsed.query, ""))
    except ValueError:
        return None


def _published(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    # A date without an offset cannot be safely converted into a known instant.
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        return None


def _entry_link(entry, source, atom):
    if atom:
        for child in entry:
            if _tag(child) == "link" and child.get("rel", "alternate") == "alternate":
                safe = _safe_link(child.get("href"), source)
                if safe:
                    return safe
        return None
    return _safe_link(_text(entry, "link", 2048), source)


def _parse_items(root, source, observed, limit):
    if not isinstance(root, ET.Element):
        raise ValueError("FEED_INVALID_FORMAT")
    rdf = root.tag == "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"
    if rdf:
        # [수정: 0 이영 · Codex] 2026-10-01T01:02:09.2228628+09:00 — bioRxiv 실제 공식 응답은 RSS 1.0/RDF이다.
        # RSS1 items are siblings of channel; dc:identifier/date preserve their distinct metadata meaning.
        namespace = "{http://purl.org/rss/1.0/}"
        if root.find(namespace + "channel") is None:
            raise ValueError("FEED_INVALID_FORMAT")
        entries, atom = list(root.findall(namespace + "item")), False
    elif root.tag == "rss":
        channel = _child(root, "channel")
        if channel is None:
            raise ValueError("FEED_INVALID_FORMAT")
        entries, atom = [item for item in channel if _tag(item) == "item"], False
    elif root.tag == "{" + ATOM + "}feed":
        entries, atom = list(root.findall("{" + ATOM + "}entry")), True
    else:
        raise ValueError("FEED_INVALID_FORMAT")
    items, ids, links = [], set(), set()
    # Fixed transport caps bytes; also cap work on unexpectedly dense XML trees.
    for entry in entries[:2000]:
        title = _text(entry, "title")
        link = _entry_link(entry, source, atom)
        if rdf:
            identifier = (_text(entry, "identifier", 1000)
                          or _plain(entry.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about", ""), 1000)
                          or link)
        else:
            identifier = _text(entry, "id" if atom else "guid", 1000) or link
        if not title or not link or identifier in ids or link in links:
            continue
        published_raw = (_text(entry, "date", 100) or _text(entry, "publicationDate", 100)) if rdf else _text(
            entry, "published" if atom else "pubDate", 100)
        # Atom updated is a revision timestamp, never silently treated as publication.
        updated = _published(_text(entry, "updated", 100)) if atom else None
        announce_type = _text(entry, "announce_type", 50) or None
        metadata = {
            "reference_only": True, "assessment": "판정불가",
            "publication_meaning": source["publication_meaning"],
            "updated": updated, "announce_type": announce_type,
        }
        digest = sha256(json.dumps({"id": identifier, "link": link, "title": title,
                                   "published": published_raw, "updated": updated},
                                  ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        items.append({"title": title, "link": link, "id": identifier,
                      "published": _published(published_raw), "source": source["label"],
                      "observed_at_kst": observed, "metadata_sha256": digest,
                      "metadata": metadata})
        ids.add(identifier)
        links.add(link)
        if len(items) == limit:
            break
    return items, len(entries)


def get_feed(provider, limit=5):
    """GET one configured feed on demand; successful empty holiday feeds are valid.

    HTTP status, observation time and response hash come from the bounded shared
    transport. These metadata do not approve a claim or establish peer review.
    """
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise ValueError("UNKNOWN_FEED_PROVIDER")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
        raise ValueError("FEED_LIMIT_MUST_BE_1_TO_10")
    source = PROVIDERS[provider]
    response = get_xml(source["host"], source["path"], params=source["params"])
    result = {
        "ok": False, "enabled": False, "provider": provider, "source": source["label"],
        "source_url": response.get("source_url", source["url"]),
        "documentation_url": source["documentation_url"],
        "retrieved_at_kst": response.get("retrieved_at_kst"),
        "response_sha256": response.get("response_sha256"),
        "http_status": response.get("http_status"), "cached": bool(response.get("cached", False)),
        "items": [], "count": 0, "feed_items_seen": 0,
        "reference_only": True, "assessment": "판정불가", "error": response.get("error"),
    }
    if not response.get("ok") or response.get("http_status") != 200:
        result["error"] = result["error"] or "FEED_HTTP_FAILED"
        return result
    try:
        items, seen = _parse_items(response.get("data"), source, result["retrieved_at_kst"], limit)
    except ValueError:
        result["error"] = "FEED_INVALID_FORMAT"
        return result
    result.update(ok=True, enabled=True, items=items, count=len(items), feed_items_seen=seen, error=None)
    return result

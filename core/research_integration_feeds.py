"""Fixed public discovery feeds, queried on demand; metadata is never approval."""
# [작성: 0 이영] 2026-10-01 KST — 기존 공식 피드를 재사용하고 실패 뒤 마지막 성공을
# 지우지 않는다. DOI/명시 버전별 중복, 관측/발행 시각, 캐시와 오류를 별도로 검증한다.
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from threading import RLock
from time import monotonic
from urllib.parse import unquote, urlsplit, urlunsplit

from core import research_news, research_trends, scholarly_feeds

CACHE_TTL_SECONDS = 300
ERROR_TTL_SECONDS = 30
_CACHE = {}
_LOCK = RLock()
_PRIVATE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\bsk-(?:proj-)?[\w-]{16,}|\bBearer\s+[\w.-]{16,}", re.I)
_DOI = re.compile(r"10\.\d{4,9}/[\w.();:/+-]+", re.I)
_PROVIDERS = {
    **{key: {"kind": "scholarly", "label": value["label"], "url": value["url"],
             "documentation_url": value["documentation_url"], "hosts": value["link_hosts"]}
       for key, value in scholarly_feeds.PROVIDERS.items()},
    **{key: {"kind": "news", "label": value["label"], "url": value["url"],
             "documentation_url": value["verification_url"], "hosts": value["domains"]}
       for key, value in research_news.SOURCES.items()},
    **{"trends_" + geo.lower(): {"kind": "trends", "label": "Google Trends · " + label,
       "url": "https://trends.google.com/trending/rss?geo=" + geo,
       "documentation_url": "https://support.google.com/trends/answer/3076011?hl=en",
       "hosts": {"trends.google.com"}, "geo": geo} for geo, label in research_trends.GEOS.items()},
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def list_feed_providers():
    """Static catalogue; listing it makes no request."""
    return [{"provider": key, "label": value["label"], "kind": value["kind"],
             "source_url": value["url"], "documentation_url": value["documentation_url"]}
            for key, value in _PROVIDERS.items()]


def clear_cache():
    """Discard only this process's metadata cache; no persistent files change."""
    with _LOCK:
        _CACHE.clear()


def _text(value, maximum=500):
    if not isinstance(value, str):
        return None
    return _PRIVATE.sub("[연락처·인증값 제외]", scholarly_feeds._plain(value, maximum))


def _link(value, hosts):
    if not isinstance(value, str) or len(value) > 2048 or _PRIVATE.search(value):
        return None
    if any(ord(c) < 33 or ord(c) == 127 for c in value) or any(c in value for c in ('\\', '<', '>', '"', "'")):
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.hostname not in hosts or p.port not in (None, 443) or p.username or p.password:
            return None
        return urlunsplit(("https", p.hostname, p.path, p.query, ""))
    except ValueError:
        return None


def _identity(item, link):
    # DOI and arXiv explicit version are separate; a new version is not deduplicated away.
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    values = [item.get("doi"), metadata.get("doi"), item.get("id"), unquote(link)]
    version = None
    for value in values:
        if isinstance(value, str):
            m = re.search(r"(?:\d|\.)v(\d+)(?:[./?#]|$)", value)
            if m:
                version = "v" + m.group(1)
                break
    if version is None and isinstance(item.get("version"), str) and re.fullmatch(r"v?\d{1,6}", item["version"]):
        version = "v" + item["version"].lstrip("v")
    doi = None
    for value in values:
        match = _DOI.search(value) if isinstance(value, str) else None
        if match:
            doi = re.sub(r"v\d+(?:\.full|\.abstract)?$", "", match.group(0).rstrip(".;)")).casefold()
            break
    if doi:
        base = "doi:" + doi
    else:
        arxiv = re.search(r"/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:[./?#]|$)", link)
        base = "arxiv:" + arxiv.group(1) if arxiv else link
    return doi, version, base + "@" + (version or "version-unspecified")


def _normalize(report, source):
    raw = report.get("articles") if source["kind"] == "news" else report.get("items")
    if not isinstance(raw, list) or len(raw) > 2000:
        raise ValueError("FEED_INVALID_RESPONSE")
    items, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"))
        link = _link(item.get("link"), source["hosts"])
        if not title or not link:
            continue
        doi, version, key = _identity(item, link)
        if source["kind"] == "trends":
            # [수정: 0 이영] 2026-10-01 KST — 실조회에서 서로 다른 검색어가
            # 같은 지역 페이지 링크를 사용했다. 논문 DOI 중복 규칙을 관심 검색어에 적용하지 않는다.
            key = "trends:" + title.casefold() + "@" + link
        if key in seen:
            continue
        seen.add(key)
        normalized = {"title": title, "link": link, "doi": doi, "version": version,
                      "work_key": key, "published": _text(item.get("published"), 100),
                      "reference_only": True, "assessment": "판정불가"}
        if source["kind"] == "trends":
            normalized["approximate_traffic"] = _text(item.get("approximate_traffic"), 100)
        # Only the selected public metadata fields enter snapshots, never remote raw bodies.
        normalized["metadata_sha256"] = sha256(json.dumps(normalized, sort_keys=True,
            ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        items.append(normalized)
    return items


def _fetch(provider, source):
    if source["kind"] == "scholarly":
        report = scholarly_feeds.get_feed(provider, limit=10)
        if report.get("ok") is not True:
            code = report.get("error")
            raise ValueError(code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", code) else "FEED_UNAVAILABLE")
        return report
    if source["kind"] == "news":
        return research_news.fetch_research_news(provider)
    return research_trends.fetch_trends(source["geo"])


def get_integration_feed(provider, limit=8, refresh=False):
    """One fixed provider per explicit call; failed refresh preserves last success.

    refresh bypasses this wrapper's cache. The existing scholarly transport may
    still return its own cached HTTP metadata, which remains labelled CACHED.
    Cache persistence is process-local; it does not claim durable subscriptions.
    """
    if not isinstance(provider, str) or provider not in _PROVIDERS:
        raise ValueError("UNKNOWN_FEED_PROVIDER")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("FEED_LIMIT_MUST_BE_1_TO_10")
    if type(refresh) is not bool:
        raise ValueError("FEED_REFRESH_MUST_BE_BOOLEAN")
    source = _PROVIDERS[provider]
    with _LOCK:
        previous = _CACHE.get(provider)
        ttl = ERROR_TTL_SECONDS if previous and previous[1].get("error") else CACHE_TTL_SECONDS
        if previous and not refresh and monotonic() - previous[0] < ttl:
            result = deepcopy(previous[1])
            result["cached"] = True
            if result["ok"]:
                result["status"] = "CACHED"
            result["checked_at"] = _now()
        else:
            checked = _now()
            result = {"provider": provider, "kind": source["kind"], "label": source["label"],
                      "source_url": source["url"], "documentation_url": source["documentation_url"],
                      "ok": False, "status": "ERROR", "cached": False, "stale": False,
                      "observed_at": checked, "checked_at": checked, "last_success_at": None,
                      "items": [], "count": 0, "error": None, "response_sha256": None,
                      "scope": "발견용 공개 메타데이터. 뉴스·검색 관심도·preprint는 논문 검산이나 사람 승인 증거가 아닙니다."}
            try:
                report = _fetch(provider, source)
                if not isinstance(report, dict):
                    raise ValueError("FEED_INVALID_RESPONSE")
                items = _normalize(report, source)
                observed = report.get("retrieved_at_kst") or report.get("as_of") or checked
                if not isinstance(observed, str) or datetime.fromisoformat(observed.replace("Z", "+00:00")).tzinfo is None:
                    raise ValueError("FEED_INVALID_TIMESTAMP")
                result.update(ok=True, status="CACHED" if report.get("cached") else "LIVE",
                              cached=bool(report.get("cached")), items=items, count=len(items),
                              observed_at=observed, last_success_at=observed,
                              response_sha256=report.get("response_sha256"))
            except Exception as exc:
                code = str(exc)
                result["error"] = code if re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", code) else "FEED_UNAVAILABLE"
                if previous and previous[1]["last_success_at"]:
                    prior = previous[1]
                    result.update(items=deepcopy(prior["items"]), count=prior["count"],
                                  last_success_at=prior["last_success_at"],
                                  response_sha256=prior.get("response_sha256"), stale=True, status="STALE_ERROR")
            _CACHE[provider] = (monotonic(), deepcopy(result))
        result["items"] = result["items"][:limit]
        result["count"] = len(result["items"])
        return result

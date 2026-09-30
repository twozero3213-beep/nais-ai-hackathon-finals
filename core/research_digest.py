# 작성: 공개 연구 digest 담당 | 2026-09-29 case95 | 논문 검색·대학 피드·KR/US Trends 35개 고정 항목 저장
# 입력/출력: core.research_fields 30분야+3 news+2 trends, schema 1 / 검증: tests/test_case95_digest.py
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import quote

from core.research_news import SOURCES, _safe_article_link, fetch_research_news
from core.research_trends import GEOS, _safe_link as _safe_trends_link, fetch_trends
from core.research_corpus import strict_json

MAX_BYTES = 1024 * 1024
ERROR_CODE = "SOURCE_UNAVAILABLE"
PAPER_PROVIDERS = {"crossref", "openalex", "europepmc"}
PAPER_ATTEMPT_CODES = {"OK", "INVALID_REQUEST", "HTTP_ERROR", "RESPONSE_TOO_LARGE", "INVALID_RESPONSE",
                       "SOURCE_UNAVAILABLE", "TIMEOUT", "UNSUPPORTED_SCOPE", "CIRCUIT_OPEN_FOR_BATCH"}


def search_resilient(*args, **kwargs):
    # Import at call time because this engine is supplied by the parallel paper-source task.
    from core.paper_sources import search_resilient as search
    return search(*args, **kwargs)


def _entry_spec():
    from core.research_fields import FIELDS
    return tuple(
        [("papers:" + key, item["label"], "papers", item["query"])
         for key, item in FIELDS.items()]
        + [("news:" + key, source["label"], "news", key) for key, source in SOURCES.items()]
        + [("trends:" + geo, "Google 급상승 검색어 · " + label, "trends", geo)
           for geo, label in GEOS.items()]
    )


def _now():
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value, *, allow_none=False):
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Invalid digest timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Invalid digest timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Digest timestamps require timezone")
    if parsed.astimezone(timezone.utc) > datetime.now(timezone.utc):
        raise ValueError("Future digest timestamp")
    return parsed.astimezone(timezone.utc)


def _paper_data(query, report):
    items = report["items"]
    if not isinstance(items, list) or len(items) > 8:
        raise ValueError("Invalid paper result")
    # Keep only compact metadata needed by the viewer; discard affiliations/long limitations.
    safe_items = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid paper item")
        safe_items.append({key: item.get(key) for key in
                           ("doi", "title", "published", "registered_at", "citations", "journal", "url")})
    return {"query": query, "mode": "latest", "years": 1, "checked_at": report["checked_at"],
            "source": report["source"], "provider": report["provider"], "attempts": report["attempts"],
            "fallback_used": report["fallback_used"], "limitations": report["limitations"],
            "scope": report["scope"], "items": safe_items}


def _news_data(source_id, report):
    if report.get("source_id") != source_id or not isinstance(report.get("articles"), list) or len(report["articles"]) > 8:
        raise ValueError("Invalid news result")
    articles = []
    for article in report["articles"]:
        if not isinstance(article, dict):
            raise ValueError("Invalid news item")
        articles.append({key: article.get(key) for key in ("title", "link", "published", "categories")})
    # Keep body-free source metadata and at most eight article headlines.
    return {key: report[key] for key in ("source_id", "source", "feed_url", "verification_url", "as_of",
                                         "feed_items_seen", "category_data_available", "category_counts")} | {
        "articles": articles
    }


def _trends_data(geo, report):
    if report.get("geo") != geo or not isinstance(report.get("items"), list) or len(report["items"]) > 10:
        raise ValueError("Invalid trends result")
    return {key: report[key] for key in ("geo", "label", "source", "feed_url", "source_url", "as_of",
                                         "feed_items_seen", "items")}


def _entry_data(kind, key, label, query, report):
    if kind == "papers":
        data = _paper_data(query, report)
    elif kind == "news":
        data = _news_data(key, report)
    else:
        data = _trends_data(key, report)
    return data


def _validate_data(entry_id, kind, data):
    if data is None:
        return
    if not isinstance(data, dict):
        raise ValueError("Invalid digest data")
    if kind == "papers":
        expected_query = next(query for key, _, _, query in _entry_spec() if key == entry_id)
        if (set(data) != {"query", "mode", "years", "checked_at", "source", "provider", "attempts",
                          "fallback_used", "limitations", "scope", "items"}
                or data["query"] != expected_query or data["mode"] != "latest" or data["years"] != 1
                or not isinstance(data["items"], list) or len(data["items"]) > 8):
            raise ValueError("Invalid paper digest data")
        _timestamp(data["checked_at"])
        if (not isinstance(data["provider"], str) or data["provider"] not in PAPER_PROVIDERS
                or not isinstance(data["source"], str) or len(data["source"]) > 4000
                or not isinstance(data["scope"], str) or len(data["scope"]) > 2000
                or type(data["fallback_used"]) is not bool
                or not isinstance(data["limitations"], list) or len(data["limitations"]) > 20
                or any(not isinstance(line, str) or len(line) > 2000 for line in data["limitations"])):
            raise ValueError("Invalid paper metadata")
        provider_hosts = {"crossref": "https://api.crossref.org/", "openalex": "https://api.openalex.org/",
                          "europepmc": "https://www.ebi.ac.uk/"}
        if not data["source"].startswith(provider_hosts[data["provider"]]):
            raise ValueError("Paper source/provider mismatch")
        if not isinstance(data["attempts"], list) or not 1 <= len(data["attempts"]) <= 3:
            raise ValueError("Invalid provider attempts")
        seen_providers = set()
        for attempt in data["attempts"]:
            if (not isinstance(attempt, dict) or set(attempt) != {"provider", "status", "code", "checked_at"}
                    or attempt["provider"] not in PAPER_PROVIDERS or attempt["status"] not in {"ok", "error", "skipped"}
                    or attempt["code"] is not None and (not isinstance(attempt["code"], str) or len(attempt["code"]) > 64)):
                raise ValueError("Invalid provider attempt")
            code = attempt["code"]
            if (attempt["provider"] in seen_providers or not isinstance(code, str)
                    or code not in PAPER_ATTEMPT_CODES and not (code.startswith("HTTP_") and code[5:].isdigit()
                                                                and 100 <= int(code[5:]) <= 599)
                    or attempt["status"] == "ok" and code != "OK"
                    or attempt["status"] == "skipped" and code not in {"UNSUPPORTED_SCOPE", "CIRCUIT_OPEN_FOR_BATCH"}
                    or attempt["status"] == "error" and code in {"OK", "UNSUPPORTED_SCOPE", "CIRCUIT_OPEN_FOR_BATCH"}):
                raise ValueError("Invalid provider attempt code")
            seen_providers.add(attempt["provider"])
            _timestamp(attempt["checked_at"])
        if data["attempts"][-1]["provider"] != data["provider"] or data["attempts"][-1]["status"] != "ok":
            raise ValueError("Selected paper source has no successful attempt")
        for item in data["items"]:
            if (not isinstance(item, dict) or set(item) != {"doi", "title", "published", "registered_at", "citations", "journal", "url"}
                    or not isinstance(item["doi"], str) or len(item["doi"]) > 200
                    or not isinstance(item["title"], str) or len(item["title"]) > 600
                    or item["citations"] is not None and (type(item["citations"]) is not int or item["citations"] < 0)):
                raise ValueError("Invalid paper item")
            if (item["url"] != "https://doi.org/" + quote(item["doi"], safe="/")
                    or not isinstance(item["published"], str) or len(item["published"]) > 20
                    or item["registered_at"] is not None and (not isinstance(item["registered_at"], str) or len(item["registered_at"]) > 40)
                    or item["journal"] is not None and (not isinstance(item["journal"], str) or len(item["journal"]) > 200)):
                raise ValueError("Invalid paper metadata")
            try:
                date.fromisoformat(item["published"])
            except ValueError:
                raise ValueError("Invalid paper date") from None
            if item["registered_at"] is not None:
                _timestamp(item["registered_at"])
    elif kind == "news":
        source_id = entry_id.removeprefix("news:")
        if (source_id not in SOURCES or set(data) != {"source_id", "source", "feed_url", "verification_url", "as_of",
                                                      "feed_items_seen", "category_data_available", "category_counts", "articles"}
                or data["source_id"] != source_id or data["source"] != SOURCES[source_id]["label"]
                or data["feed_url"] != SOURCES[source_id]["url"]
                or data["verification_url"] != SOURCES[source_id]["verification_url"]
                or type(data["feed_items_seen"]) is not int or not 0 <= data["feed_items_seen"] <= 10000
                or type(data["category_data_available"]) is not bool
                or not isinstance(data["category_counts"], list) or len(data["category_counts"]) > 5
                or not isinstance(data["articles"], list) or len(data["articles"]) > 8):
            raise ValueError("Invalid news digest data")
        _timestamp(data["as_of"])
        for category in data["category_counts"]:
            if (not isinstance(category, dict) or set(category) != {"name", "count", "denominator", "article_denominator"}
                    or not isinstance(category["name"], str) or len(category["name"]) > 100
                    or any(type(category[key]) is not int or category[key] < 0
                           for key in ("count", "denominator", "article_denominator"))):
                raise ValueError("Invalid category metadata")
        for item in data["articles"]:
            if (not isinstance(item, dict) or set(item) != {"title", "link", "published", "categories"}
                    or not isinstance(item["title"], str) or len(item["title"]) > 500
                    or not _safe_article_link(item["link"], source_id)
                    or item["published"] is not None and (not isinstance(item["published"], str) or len(item["published"]) > 60)
                    or not isinstance(item["categories"], list) or len(item["categories"]) > 20
                    or any(not isinstance(category, str) or len(category) > 100 for category in item["categories"])):
                raise ValueError("Invalid news item")
    else:
        geo = entry_id.removeprefix("trends:")
        if (geo not in GEOS or set(data) != {"geo", "label", "source", "feed_url", "source_url", "as_of",
                                            "feed_items_seen", "items"}
                or data["geo"] != geo or data["label"] != GEOS[geo]
                or data["source"] != "Google Trends 급상승 검색어"
                or data["feed_url"] != f"https://trends.google.com/trending/rss?geo={geo}"
                or data["source_url"] != f"https://trends.google.com/trending?geo={geo}"
                or type(data["feed_items_seen"]) is not int or not 0 <= data["feed_items_seen"] <= 10000
                or not isinstance(data["items"], list) or len(data["items"]) > 10):
            raise ValueError("Invalid trends digest data")
        _timestamp(data["as_of"])
        for item in data["items"]:
            if (not isinstance(item, dict) or set(item) != {"title", "approximate_traffic", "published", "link", "source_order"}
                    or not isinstance(item["title"], str) or len(item["title"]) > 300
                    or item["approximate_traffic"] is not None and (not isinstance(item["approximate_traffic"], str) or len(item["approximate_traffic"]) > 100)
                    or item["published"] is not None and (not isinstance(item["published"], str) or len(item["published"]) > 60)
                    or not _safe_trends_link(item["link"])
                    or type(item["source_order"]) is not int or not 1 <= item["source_order"] <= 10):
                raise ValueError("Invalid trend item")


def validate_digest(value):
    """Fail closed on unknown schema, IDs, status, timestamps, size or nested data."""
    if (not isinstance(value, dict) or set(value) != {"schema", "generated_at", "entries"}
            or type(value.get("schema")) is not int or value.get("schema") != 1):
        raise ValueError("Invalid digest schema")
    generated = _timestamp(value["generated_at"])
    entries = value["entries"]
    spec = _entry_spec()
    if not isinstance(entries, list) or len(entries) != len(spec):
        raise ValueError("Invalid digest entries")
    expected = {entry_id: (label, kind) for entry_id, label, kind, _ in spec}
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"id", "label", "kind", "attempted_at", "last_success_at",
                                                         "status", "data", "error"}:
            raise ValueError("Invalid digest entry")
        entry_id = entry["id"]
        if entry_id not in expected or entry_id in seen or (entry["label"], entry["kind"]) != expected[entry_id]:
            raise ValueError("Unexpected digest entry ID")
        seen.add(entry_id)
        attempted = _timestamp(entry["attempted_at"])
        last_success = _timestamp(entry["last_success_at"], allow_none=True)
        if attempted > generated or last_success and last_success > generated:
            raise ValueError("Inconsistent digest timestamps")
        if entry["status"] not in {"ok", "error"}:
            raise ValueError("Invalid digest status")
        if entry["status"] == "ok" and (entry["error"] is not None or last_success is None or entry["data"] is None):
            raise ValueError("Successful digest entry is incomplete")
        if entry["status"] == "error" and (entry["error"] != ERROR_CODE or (last_success is None) != (entry["data"] is None)):
            raise ValueError("Unsafe or inconsistent digest error")
        if (entry["status"] == "ok" and last_success < attempted
                or entry["status"] == "error" and last_success and last_success > attempted):
            raise ValueError("Inconsistent digest timestamps")
        _validate_data(entry_id, entry["kind"], entry["data"])
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ValueError("Digest too large")
    return value


def _previous_index(previous):
    if previous is None:
        return {}
    validate_digest(previous)
    return {entry["id"]: entry for entry in previous["entries"]}


def _rate_limited_providers(attempts):
    # Only an explicit 429 is a batch-wide circuit signal; transient errors retry next field.
    return {attempt["provider"] for attempt in attempts
            if isinstance(attempt, dict) and attempt.get("provider") in PAPER_PROVIDERS
            and attempt.get("status") == "error" and attempt.get("code") == "HTTP_429"}


def build_digest(previous=None):
    """Build bounded entries; preserve prior successes and circuit only explicit HTTP 429s."""
    old = _previous_index(previous)
    entries = []
    unavailable_providers = set()
    for entry_id, label, kind, query in _entry_spec():
        attempted = _now()
        try:
            if kind == "papers":
                report = search_resilient(query, mode="latest", years=1, limit=8,
                                          unavailable_providers=tuple(sorted(unavailable_providers)))
                unavailable_providers.update(_rate_limited_providers(report["attempts"]))
            else:
                report = fetch_research_news(query) if kind == "news" else fetch_trends(query)
            data = _entry_data(kind, query, label, query, report)
            success_at, status, error = _now(), "ok", None
        except Exception as exc:
            if kind == "papers":
                unavailable_providers.update(_rate_limited_providers(getattr(exc, "attempts", [])))
            prior = old.get(entry_id, {})
            data = prior.get("data")
            success_at = prior.get("last_success_at")
            status, error = "error", ERROR_CODE
        entries.append({"id": entry_id, "label": label, "kind": kind, "attempted_at": attempted,
                        "last_success_at": success_at, "status": status, "data": data, "error": error})
    digest = {"schema": 1, "generated_at": _now(), "entries": entries}
    return validate_digest(digest)


def load_digest(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Digest too large")
    return validate_digest(strict_json(raw))


def atomic_write_digest(path, digest):
    validate_digest(digest)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(digest, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    if len(encoded) > MAX_BYTES:
        raise ValueError("Digest too large")
    file_descriptor, temporary = tempfile.mkstemp(prefix="." + target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return len(encoded)

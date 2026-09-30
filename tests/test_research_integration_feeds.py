"""[0 이영] 2026-10-01 KST: fixed on-demand feed/cache boundaries; no live calls."""
from copy import deepcopy
import pytest

from core import research_integration_feeds as feeds

OBSERVED = "2026-10-01T02:00:00+09:00"


@pytest.fixture(autouse=True)
def reset_cache():
    feeds.clear_cache()
    yield
    feeds.clear_cache()


def scholarly(items=None, **extra):
    return {"ok": True, "retrieved_at_kst": OBSERVED, "cached": False,
            "response_sha256": "a" * 64, "items": items or [], **extra}


def test_catalog_is_static_and_all_eight_providers_are_available(monkeypatch):
    monkeypatch.setattr(feeds, "_fetch", lambda *args: pytest.fail("catalog must not fetch"))
    assert {row["provider"] for row in feeds.list_feed_providers()} == {
        "arxiv", "biorxiv", "kisti", "mit", "harvard", "kaist", "trends_kr", "trends_us"}


@pytest.mark.parametrize("provider,limit,refresh", [
    ("https://example.org", 5, False), ("arxiv", True, False), ("arxiv", 1.0, False),
    ("arxiv", 0, False), ("arxiv", 11, False), ("arxiv", 5, "false"),
])
def test_invalid_inputs_are_rejected_before_network(monkeypatch, provider, limit, refresh):
    monkeypatch.setattr(feeds, "_fetch", lambda *args: pytest.fail("invalid input fetched"))
    with pytest.raises(ValueError):
        feeds.get_integration_feed(provider, limit, refresh)


def test_empty_success_is_valid_and_cache_does_not_fetch_again(monkeypatch):
    calls = []
    monkeypatch.setattr(feeds, "_fetch", lambda *args: calls.append(args) or scholarly())
    first = feeds.get_integration_feed("arxiv")
    second = feeds.get_integration_feed("arxiv")
    assert first["ok"] and first["status"] == "LIVE" and first["items"] == []
    assert second["status"] == "CACHED" and second["last_success_at"] == OBSERVED
    assert len(calls) == 1


def test_failed_refresh_and_repeated_failures_preserve_success_and_error(monkeypatch):
    item = {"title": "Paper", "link": "https://arxiv.org/abs/2609.12345v1"}
    monkeypatch.setattr(feeds, "_fetch", lambda *args: scholarly([item]))
    first = feeds.get_integration_feed("arxiv")
    def failed(*args):
        raise ValueError("RSS_UNAVAILABLE")
    monkeypatch.setattr(feeds, "_fetch", failed)
    for _ in range(2):
        result = feeds.get_integration_feed("arxiv", refresh=True)
        assert not result["ok"] and result["status"] == "STALE_ERROR" and result["stale"]
        assert result["items"] == first["items"] and result["last_success_at"] == OBSERVED
        assert result["error"] == "RSS_UNAVAILABLE"
    result = feeds.get_integration_feed("arxiv")
    assert result["cached"] and result["status"] == "STALE_ERROR" and not result["ok"]


def test_recovery_clears_stale_error_and_preserves_return_copy(monkeypatch):
    monkeypatch.setattr(feeds, "_fetch", lambda *args: scholarly())
    feeds.get_integration_feed("arxiv")
    monkeypatch.setattr(feeds, "_fetch", lambda *args: {"ok": False})
    assert feeds.get_integration_feed("arxiv", refresh=True)["stale"]
    monkeypatch.setattr(feeds, "_fetch", lambda *args: scholarly([{"title": "New", "link": "https://arxiv.org/abs/2609.12345v2"}]))
    result = feeds.get_integration_feed("arxiv", refresh=True)
    assert result["ok"] and not result["stale"] and result["error"] is None
    result["items"].clear()
    assert feeds.get_integration_feed("arxiv")["count"] == 1


def test_same_doi_version_deduplicates_but_different_versions_survive(monkeypatch):
    items = [{"title": "A", "link": "https://www.biorxiv.org/content/10.1101/2026.09.29.123456v1.full"},
             {"title": "B", "link": "https://www.biorxiv.org/content/10.1101/2026.09.29.123456v1.abstract"},
             {"title": "C", "link": "https://www.biorxiv.org/content/10.1101/2026.09.29.123456v2.full"}]
    monkeypatch.setattr(feeds, "_fetch", lambda *args: scholarly(items))
    result = feeds.get_integration_feed("biorxiv")
    assert result["count"] == 2
    assert [item["version"] for item in result["items"]] == ["v1", "v2"]
    assert {item["doi"] for item in result["items"]} == {"10.1101/2026.09.29.123456"}


def test_arxiv_versions_and_https_host_allowlist(monkeypatch):
    items = [{"title": "A", "link": "https://arxiv.org/abs/2609.12345v1"},
             {"title": "A duplicate", "link": "https://www.arxiv.org/abs/2609.12345v1"},
             {"title": "A revision", "link": "https://arxiv.org/abs/2609.12345v2"},
             {"title": "Unsafe", "link": "https://arxiv.org.evil.example/abs/2609.12345"},
             {"title": "HTTP", "link": "http://arxiv.org/abs/2609.12345"}]
    monkeypatch.setattr(feeds, "_fetch", lambda *args: scholarly(items))
    result = feeds.get_integration_feed("arxiv")
    assert result["count"] == 2
    assert all(i["reference_only"] and i["assessment"] == "판정불가" for i in result["items"])


def test_official_arxiv_doi_field_survives_parser_to_dedup(monkeypatch):
    import xml.etree.ElementTree as ET
    raw = '<rss xmlns:arxiv="http://arxiv.org/schemas/atom"><channel><item><title>A</title><link>https://arxiv.org/abs/2609.12345v1</link><guid>a</guid><arxiv:DOI>10.5802/jep.257</arxiv:DOI></item></channel></rss>'
    monkeypatch.setattr(feeds.scholarly_feeds, "get_xml", lambda *a, **kw: {
        "ok": True, "http_status": 200, "data": ET.fromstring(raw), "retrieved_at_kst": OBSERVED})
    result = feeds.get_integration_feed("arxiv")
    assert result["items"][0]["doi"] == "10.5802/jep.257"
    assert result["items"][0]["version"] == "v1"


def test_remote_private_strings_and_exception_messages_never_escape(monkeypatch):
    items = [{"title": "Contact: mock@example.invalid", "link": "https://arxiv.org/abs/2609.12345"}]
    monkeypatch.setattr(feeds, "_fetch", lambda *args: scholarly(items))
    result = feeds.get_integration_feed("arxiv")
    assert "mock@example.invalid" not in str(result)
    def failed(*args):
        raise RuntimeError("upstream mock@example.invalid")
    monkeypatch.setattr(feeds, "_fetch", failed)
    result = feeds.get_integration_feed("arxiv", refresh=True)
    assert result["error"] == "FEED_UNAVAILABLE" and "mock@example.invalid" not in str(result)


@pytest.mark.parametrize("provider,report", [
    ("mit", {"as_of": OBSERVED, "articles": [{"title": "News", "link": "https://news.mit.edu/2026/sample"}]}),
    ("trends_kr", {"as_of": OBSERVED, "items": [{"title": "Topic", "link": "https://trends.google.com/trending?geo=KR", "approximate_traffic": "100+"}]}),
])
def test_news_and_trends_are_distinct_discovery_metadata(monkeypatch, provider, report):
    monkeypatch.setattr(feeds, "_fetch", lambda *args: deepcopy(report))
    result = feeds.get_integration_feed(provider)
    assert result["ok"] and result["count"] == 1
    assert result["items"][0]["assessment"] == "판정불가"


def test_distinct_trends_queries_with_shared_region_link_survive(monkeypatch):
    link = "https://trends.google.com/trending?geo=KR"
    report = {"as_of": OBSERVED, "items": [{"title": "Topic A", "link": link},
              {"title": "Topic B", "link": link}, {"title": "Topic A", "link": link}]}
    monkeypatch.setattr(feeds, "_fetch", lambda *args: report)
    result = feeds.get_integration_feed("trends_kr")
    assert result["count"] == 2

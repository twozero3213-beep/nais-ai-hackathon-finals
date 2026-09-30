"""Mock-only checks for fixed scholarly feeds; never contact providers."""
# [작성: 0 이영 · Codex] 2026-10-01 KST, 담당 버전 0.
# 수정 이유/검증: 발행·관측 시각, RSS/Atom ID, 중복 제거, 링크·스크립트 경계와 실제 실패 표시를 확인한다.
from hashlib import sha256
import xml.etree.ElementTree as ET

import pytest

from core import scholarly_feeds as feeds

OBSERVED = "2026-10-01T00:40:00+09:00"


def _install(monkeypatch, xml, status=200, ok=True, error=None):
    calls = []

    def mock_get_xml(host, path, params=None):
        calls.append((host, path, params))
        return {"ok": ok, "http_status": status, "data": ET.fromstring(xml),
                "source_url": "https://" + host + path, "retrieved_at_kst": OBSERVED,
                "response_sha256": sha256(xml.encode()).hexdigest(), "error": error}

    monkeypatch.setattr(feeds, "get_xml", mock_get_xml)
    return calls


def test_arxiv_single_combined_get_preserves_guid_announcement_and_hash(monkeypatch):
    xml = '''<rss xmlns:a="http://arxiv.org/schemas/atom"><channel><item>
    <title>Learning &amp; statistics</title><link>https://arxiv.org/abs/2609.00001</link>
    <guid isPermaLink="false">oai:arXiv.org:2609.00001v2</guid>
    <pubDate>Wed, 30 Sep 2026 00:00:00 -0400</pubDate><a:announce_type>replace-cross</a:announce_type>
    <description>Full-text content must not be returned</description></item></channel></rss>'''
    calls = _install(monkeypatch, xml)
    result = feeds.get_feed("arxiv")
    assert calls == [("rss.arxiv.org", "/rss/cs.LG+stat.ML+stat.ME", None)]
    assert result["ok"] is True and result["enabled"] is True
    assert result["retrieved_at_kst"] == OBSERVED
    assert result["response_sha256"] == sha256(xml.encode()).hexdigest()
    item = result["items"][0]
    assert item["id"] == "oai:arXiv.org:2609.00001v2"
    assert item["published"] == "2026-09-30T04:00:00+00:00"
    assert item["observed_at_kst"] == OBSERVED
    assert item["metadata"]["announce_type"] == "replace-cross"
    assert item["metadata"]["assessment"] == "판정불가"
    assert "Full-text" not in str(result) and "description" not in item
    assert len(item["metadata_sha256"]) == 64
    assert feeds.get_feed("arxiv")["items"][0]["metadata_sha256"] == item["metadata_sha256"]


def test_atom_id_published_updated_are_distinct_and_skip_non_alternate(monkeypatch):
    xml = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <id>doi:10.1101/2026.09.29.000001</id><title>Bioinformatics preprint</title>
    <link rel="enclosure" href="https://www.biorxiv.org/content/10.1101/test.full.pdf" />
    <link rel="alternate" href="https://www.biorxiv.org/content/10.1101/testv1" />
    <published>2026-09-29T12:00:00Z</published><updated>2026-09-30T13:00:00Z</updated>
    <content type="html">Body must not be returned</content></entry></feed>'''
    calls = _install(monkeypatch, xml)
    result = feeds.get_feed("biorxiv")
    assert calls == [("connect.biorxiv.org", "/biorxiv_xml.php", {"subject": "bioinformatics"})]
    item = result["items"][0]
    assert item["id"] == "doi:10.1101/2026.09.29.000001"
    assert item["link"].endswith("testv1")
    assert item["published"] == "2026-09-29T12:00:00+00:00"
    assert item["metadata"]["updated"] == "2026-09-30T13:00:00+00:00"
    assert "Body must" not in str(result)


def test_atom_updated_only_does_not_become_published(monkeypatch):
    _install(monkeypatch, '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Revision only</title>
    <link href="https://biorxiv.org/content/test"/><updated>2026-09-30T00:00:00Z</updated></entry></feed>''')
    item = feeds.get_feed("biorxiv")["items"][0]
    assert item["published"] is None
    assert item["id"] == item["link"]
    assert item["metadata"]["updated"] == "2026-09-30T00:00:00+00:00"


def test_duplicate_ids_and_canonical_links_do_not_spend_limit(monkeypatch):
    entries = '''<item><title>One</title><guid>a</guid><link>https://arxiv.org:443/abs/1#one</link></item>
    <item><title>Same link</title><guid>b</guid><link>https://arxiv.org/abs/1#two</link></item>
    <item><title>Same ID</title><guid>a</guid><link>https://arxiv.org/abs/2</link></item>
    <item><title>Two</title><guid>c</guid><link>https://arxiv.org/abs/3</link></item>'''
    _install(monkeypatch, "<rss><channel>" + entries + "</channel></rss>")
    result = feeds.get_feed("arxiv", 2)
    assert result["feed_items_seen"] == 4 and result["count"] == 2
    assert [item["id"] for item in result["items"]] == ["a", "c"]


@pytest.mark.parametrize("link", [
    "https://evil.example/abs/1", "https://arxiv.org.evil.example/abs/1", "javascript:alert(1)",
    "http://arxiv.org/abs/1", "https://arxiv.org@evil.example/abs/1", "https://user@arxiv.org/abs/1",
    "https://arxiv.org:444/abs/1", "https://arxiv.org\\@evil.example/abs/1", "https://arxiv.org/ab&#10;s/1",
])
def test_unsafe_links_excluded(monkeypatch, link):
    _install(monkeypatch, "<rss><channel><item><title>Unsafe</title><link>" + link + "</link></item></channel></rss>")
    result = feeds.get_feed("arxiv")
    assert result["count"] == 0
    assert result["ok"] is True


def test_sanitizes_escaped_and_xml_child_scripts(monkeypatch):
    _install(monkeypatch, '''<rss><channel>
    <item><title><![CDATA[Good <b>title</b><script>steal()</script><style>bad-css</style>]]></title>
    <link>https://arxiv.org/abs/1</link></item>
    <item><title>Another <script>hidden()</script><b>title</b></title><link>https://arxiv.org/abs/2</link></item>
    </channel></rss>''')
    result = feeds.get_feed("arxiv")
    assert [item["title"] for item in result["items"]] == ["Good title", "Another title"]
    assert "steal" not in str(result) and "hidden" not in str(result) and "bad-css" not in str(result)


@pytest.mark.parametrize("date", ["not a date", "2026-09-30", "2026-09-30T12:00:00"])
def test_unzoned_or_invalid_date_is_not_invented(monkeypatch, date):
    _install(monkeypatch, "<rss><channel><item><title>Unknown date</title><link>https://arxiv.org/abs/1</link>"
             + "<pubDate>" + date + "</pubDate></item></channel></rss>")
    assert feeds.get_feed("arxiv")["items"][0]["published"] is None


@pytest.mark.parametrize("limit", [0, 11, True, False, "5", 1.5, None])
def test_invalid_limit_makes_no_request(monkeypatch, limit):
    calls = _install(monkeypatch, "<rss><channel/></rss>")
    with pytest.raises(ValueError, match="FEED_LIMIT"):
        feeds.get_feed("arxiv", limit)
    assert calls == []


@pytest.mark.parametrize("provider", ["https://evil.example", "unknown", None, []])
def test_unknown_provider_makes_no_request(monkeypatch, provider):
    calls = _install(monkeypatch, "<rss><channel/></rss>")
    with pytest.raises(ValueError, match="UNKNOWN_FEED"):
        feeds.get_feed(provider)
    assert calls == []


def test_limit_ten_and_kisti_fixed_address(monkeypatch):
    xml = "<rss><channel>" + "".join(
        "<item><title>Insight " + str(i) + "</title><link>https://www.kisti.re.kr/insight/" + str(i)
        + "</link><pubDate>Wed, 30 Sep 2026 12:00:00 +0900</pubDate></item>" for i in range(12)) + "</channel></rss>"
    calls = _install(monkeypatch, xml)
    result = feeds.get_feed("kisti", 10)
    assert calls == [("www.kisti.re.kr", "/rss/data-insight", None)]
    assert result["count"] == 10 and result["feed_items_seen"] == 12
    assert result["items"][0]["published"] == "2026-09-30T03:00:00+00:00"


def test_valid_empty_holiday_feed_is_success(monkeypatch):
    _install(monkeypatch, "<rss><channel><title>Empty holiday</title></channel></rss>")
    result = feeds.get_feed("arxiv")
    assert result["ok"] is True and result["enabled"] is True and result["count"] == 0


@pytest.mark.parametrize("status,error", [(301, "HTTP_301"), (404, "HTTP_404"), (None, "CONNECTION_OR_RESPONSE_ERROR")])
def test_failure_is_disabled_with_observed_error(monkeypatch, status, error):
    _install(monkeypatch, "<error/>", status=status, ok=False, error=error)
    result = feeds.get_feed("kisti")
    assert result["ok"] is False and result["enabled"] is False and result["items"] == []
    assert result["http_status"] == status and result["error"] == error


@pytest.mark.parametrize("xml", ["<rss/>", "<html/>", "<feed/>"])
def test_invalid_feed_shape_is_disabled(monkeypatch, xml):
    _install(monkeypatch, xml)
    result = feeds.get_feed("arxiv")
    assert result["enabled"] is False and result["error"] == "FEED_INVALID_FORMAT"


# [수정: 0 이영 · Codex] 2026-10-01T01:02:09.2228628+09:00 — 실제 bioRxiv RDF/RSS1 구조의 ID·날짜·스크립트 경계를 재현한다.
def test_biorxiv_rdf_rss1_sibling_items_dc_identifier_and_date(monkeypatch):
    xml = '''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:prism="http://purl.org/rss/1.0/modules/prism/">
      <channel rdf:about="https://connect.biorxiv.org/biorxiv_xml.php?subject=bioinformatics"><title>bioinformatics</title></channel>
      <item rdf:about="https://www.biorxiv.org/content/testv2"><title><![CDATA[Genome <b>methods</b><script>hidden()</script>]]></title>
        <link>https://www.biorxiv.org/content/testv2</link><dc:identifier>doi:10.1101/testv2</dc:identifier>
        <dc:date>2026-09-30T07:15:00-04:00</dc:date><prism:publicationDate>2026-09-29T00:00:00Z</prism:publicationDate>
        <description>Do not return the abstract</description></item></rdf:RDF>'''
    calls = _install(monkeypatch, xml)
    result = feeds.get_feed("biorxiv")
    assert result["ok"] is True and result["enabled"] is True
    assert calls == [("connect.biorxiv.org", "/biorxiv_xml.php", {"subject": "bioinformatics"})]
    item = result["items"][0]
    assert item["id"] == "doi:10.1101/testv2" and item["title"] == "Genome methods"
    assert item["published"] == "2026-09-30T11:15:00+00:00" and item["observed_at_kst"] == OBSERVED
    assert "hidden" not in str(result) and "Do not return" not in str(result)


def test_rdf_about_id_prism_date_and_duplicate_link(monkeypatch):
    xml = '''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns="http://purl.org/rss/1.0/" xmlns:prism="http://purl.org/rss/1.0/modules/prism/">
      <channel/><item rdf:about="bioRxiv:version2"><title>Prism dated</title><link>https://biorxiv.org/content/testv2</link>
        <prism:publicationDate>2026-09-30T08:30:00Z</prism:publicationDate></item>
      <item rdf:about="different-id"><title>Duplicate</title><link>https://biorxiv.org/content/testv2#article</link></item>
      </rdf:RDF>'''
    _install(monkeypatch, xml)
    result = feeds.get_feed("biorxiv")
    assert result["count"] == 1 and result["feed_items_seen"] == 2
    assert result["items"][0]["id"] == "bioRxiv:version2"
    assert result["items"][0]["published"] == "2026-09-30T08:30:00+00:00"


def test_rdf_without_rss1_channel_is_not_a_valid_feed(monkeypatch):
    _install(monkeypatch, '''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
      <item><title>Unsupported RDF</title><link>https://www.biorxiv.org/content/test</link></item></rdf:RDF>''')
    result = feeds.get_feed("biorxiv")
    assert result["ok"] is False and result["enabled"] is False and result["error"] == "FEED_INVALID_FORMAT"

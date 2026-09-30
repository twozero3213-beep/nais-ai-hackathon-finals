"""[0 이영] 역방향 갱신 관계·식별자 불일치·공개 출력 경계를 모의 응답으로 검증한다."""
# [작성: 0 이영 · Codex] 2026-10-01 00:38 KST — 실 API 성공이나 검산 PASS로 모의 시험을 오인하지 않는다.
import json
import xml.etree.ElementTree as ET

import pytest

from core import publication_extensions as extension

DOI = "10.5555/original"
NOTICE = "10.5555/notice"
DATE = {"date-parts": [[2023, 4, 22]], "date-time": "2023-04-22T00:00:00Z", "timestamp": 1682121600000}


def envelope(data=None, **changes):
    result = {"ok": True, "http_status": 200, "data": data, "source_url": "https://api.crossref.org/works/mock",
              "retrieved_at_kst": "2026-10-01T00:38:00+09:00", "response_sha256": "a" * 64,
              "cached": False, "error": None}
    result.update(changes)
    return result


def work(doi=DOI, **fields):
    return {"status": "ok", "message": {"DOI": doi, **fields}}


@pytest.mark.parametrize("value", [None, 123, "", " 10.5555/paper", "https://doi.org/10.5555/paper",
                                  "10.5555/a?api_key=x", "10.5555/a#fragment", "10.5555/a&token=x",
                                  "10.5555/a@example.org", "10.5555/sk-proj-" + "x" * 25,
                                  "10.5555/" + "x" * 193, "10.5555/a\n"])
def test_doi_credentials_urls_and_oversize_rejected_without_network(monkeypatch, value):
    monkeypatch.setattr(extension, "get_json", lambda *a, **k: pytest.fail("invalid input reached network"))
    result = extension.publication_updates(value)
    assert result["ok"] is False
    assert result["error"] == "INVALID_DOI"
    assert "doi" not in result


def test_reverse_update_lookup_preserves_sources_dates_and_identity(monkeypatch):
    calls = []
    original = work(**{"updated-by": [{"DOI": NOTICE.upper(), "type": "retraction", "source": "publisher", "label": "Retraction", "updated": DATE},
                                    {"DOI": NOTICE, "type": "retraction", "source": "retraction-watch", "record-id": 42, "updated": DATE}],
                       "relation": {"is-preprint-of": [{"id-type": "doi", "id": "10.5555/preprint", "asserted-by": "subject"}]},
                       "indexed": {"date-parts": [[2026, 10, 1]]}, "author": [{"email": "private@example.invalid"}]})
    notice = work(NOTICE, **{"update-to": [{"DOI": DOI, "type": "retraction", "source": "publisher", "updated": DATE}]})

    def fake(host, path, params=None):
        calls.append((host, path, params))
        return envelope(original if len(calls) == 1 else notice)

    monkeypatch.setattr(extension, "get_json", fake)
    result = extension.publication_updates(DOI.upper())
    assert result["ok"] is True and result["semantic_status"] == "UPDATE_METADATA_FOUND"
    assert len(calls) == 2 and all(c[0] == "api.crossref.org" for c in calls)
    assert result["update_to"] == []
    assert {e["source"] for e in result["updated_by"]} == {"publisher", "retraction-watch"}
    assert result["updated_by"][0]["updated"] == DATE
    assert result["updated_by"][1]["record-id"] == 42
    assert result["notices"][0]["identity_verified"] is True
    assert result["notices"][0]["links_to_requested_doi"] is True
    assert result["relations"]["is-preprint-of"][0]["id"] == "10.5555/preprint"
    assert "private@example.invalid" not in json.dumps(result)
    assert result["retrieved_at_kst"] != DATE["date-time"]
    assert result["verification_pass"] is False


@pytest.mark.parametrize("returned, expected", [(work("10.5555/wrong"), "DOI_IDENTITY_MISMATCH"),
                                               ({"status": "ok", "message": []}, "INVALID_CROSSREF_RESPONSE"),
                                               (work(**{"updated-by": "retracted"}), "INVALID_UPDATE_METADATA"),
                                               (work(**{"relation": []}), "INVALID_RELATION_METADATA")])
def test_http_success_is_not_semantic_success(monkeypatch, returned, expected):
    monkeypatch.setattr(extension, "get_json", lambda *a, **k: envelope(returned))
    result = extension.publication_updates(DOI)
    assert result["ok"] is False and result["error"] == expected
    assert result["semantic_status"] == "LOOKUP_FAILED"


@pytest.mark.parametrize("notice_payload, identity, linked, error", [
    (work("10.5555/other", **{"update-to": [{"DOI": DOI}]}), False, False, "DOI_IDENTITY_MISMATCH"),
    (work(NOTICE, **{"update-to": [{"DOI": "10.5555/other"}]}), True, False, None),
])
def test_notice_requires_identity_and_reverse_link(monkeypatch, notice_payload, identity, linked, error):
    responses = iter([envelope(work(**{"updated-by": [{"DOI": NOTICE, "type": "correction"}]})), envelope(notice_payload)])
    monkeypatch.setattr(extension, "get_json", lambda *a, **k: next(responses))
    notice = extension.publication_updates(DOI)["notices"][0]
    assert (notice["identity_verified"], notice["links_to_requested_doi"], notice["error"]) == (identity, linked, error)


def test_notice_queries_are_bounded_and_self_links_are_not_followed(monkeypatch):
    calls = []
    updates = [{"DOI": DOI, "type": "retraction"}] + [{"DOI": f"10.5555/notice{i}", "type": "correction"} for i in range(8)]

    def fake(host, path, params=None):
        calls.append(path)
        return envelope(work(**{"updated-by": updates})) if len(calls) == 1 else envelope(ok=False, http_status=404, error="HTTP_404")

    monkeypatch.setattr(extension, "get_json", fake)
    result = extension.publication_updates(DOI)
    assert len(calls) == 4 and len(result["notices"]) == 3
    assert result["notice_lookup_truncated"] is True
    assert all(not n["identity_verified"] and n["error"] == "HTTP_404" for n in result["notices"])


def test_no_updates_is_not_retraction_absence_or_verification(monkeypatch):
    monkeypatch.setattr(extension, "get_json", lambda *a, **k: envelope(work(**{"deposited": {"date-parts": [[2026, 10, 1]]}})))
    result = extension.publication_updates(DOI)
    assert result["ok"] and result["semantic_status"] == "NO_UPDATE_METADATA_FOUND"
    assert result["retraction_absence_proven"] is False and result["verification_pass"] is False
    assert "철회 없음" in result["limitations"][0]


def pubmed_xml(pmid="12345", corrections="", publication_type="Journal Article", extra_ids="", extra=""):
    return ET.fromstring(f"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>{pmid}</PMID>
    <DateRevised><Year>2026</Year><Month>09</Month><Day>30</Day></DateRevised><Article>
    <ArticleTitle>A <i>bounded</i> title</ArticleTitle><Journal><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
    <Abstract><AbstractText>PRIVATE_LONG_ABSTRACT</AbstractText></Abstract>
    <AuthorList><Author><LastName>PRIVATE_AUTHOR</LastName><Affiliation>private@example.invalid</Affiliation></Author></AuthorList>
    <ELocationID EIdType="doi" ValidYN="Y">10.5555/paper</ELocationID>
    <PublicationTypeList><PublicationType>{publication_type}</PublicationType></PublicationTypeList></Article>
    <CommentsCorrectionsList>{corrections}</CommentsCorrectionsList></MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.5555/PAPER</ArticleId><ArticleId IdType="pmc">PMC1234</ArticleId>{extra_ids}</ArticleIdList></PubmedData>
    </PubmedArticle>{extra}</PubmedArticleSet>""")


@pytest.mark.parametrize("value", [None, 12345, "", "0", "00123", "-1", "123?api_key=x", "123@example.org", "123\n", "1" * 11])
def test_invalid_pmid_never_reaches_network(monkeypatch, value):
    monkeypatch.setattr(extension, "get_xml", lambda *a, **k: pytest.fail("invalid input reached network"))
    result = extension.pubmed_record(value)
    assert result["ok"] is False and result["error"] == "INVALID_PMID"


@pytest.mark.parametrize("kind", ["ErratumIn", "ErratumFor", "RetractionIn", "RetractionOf", "ExpressionOfConcernIn", "ExpressionOfConcernFor",
                                 "CorrectedandRepublishedIn", "CorrectedandRepublishedFrom", "UpdateIn", "UpdateOf"])
def test_pubmed_preserves_exact_relation_direction_without_private_text(monkeypatch, kind):
    corrections = f'<CommentsCorrections RefType="{kind}"><RefSource>PRIVATE_COMMENT</RefSource><PMID>54321</PMID><Note>PRIVATE_NOTE</Note></CommentsCorrections>'
    calls = []

    def fake(host, path, params=None):
        calls.append((host, path, params))
        return envelope(pubmed_xml(corrections=corrections), source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=12345")

    monkeypatch.setattr(extension, "get_xml", fake)
    result = extension.pubmed_record("12345")
    assert result["ok"] is True and result["semantic_status"] == "UPDATE_METADATA_FOUND"
    assert result["comments_corrections"][0]["ref_type"] == kind
    assert result["comments_corrections"][0]["pmid"] == "54321"
    assert result["dois"] == ["10.5555/paper"] and result["pmc_ids"] == ["PMC1234"]
    assert result["title"] == "A bounded title"
    assert result["publication_date"] == {"Year": "2020"}
    assert result["index_revision_date"] == {"Year": "2026", "Month": "09", "Day": "30"}
    assert all(marker not in json.dumps(result) for marker in ("PRIVATE_", "private@example.invalid"))
    assert len(calls) == 1 and calls[0][0] == "eutils.ncbi.nlm.nih.gov"
    assert "email" not in calls[0][2] and "api_key" not in calls[0][2]


@pytest.mark.parametrize("xml, expected", [
    (pubmed_xml(pmid="54321"), "PMID_IDENTITY_MISMATCH"),
    (pubmed_xml(extra_ids='<ArticleId IdType="pubmed">54321</ArticleId>'), "PMID_IDENTITY_MISMATCH"),
    (ET.fromstring("<PubmedArticleSet/>"), "PUBMED_RECORD_COUNT_MISMATCH"),
    (ET.fromstring("<PubmedArticleSet><ERROR>not found</ERROR></PubmedArticleSet>"), "INVALID_PUBMED_RESPONSE"),
    (ET.fromstring("<unexpected/>"), "INVALID_PUBMED_RESPONSE"),
])
def test_pubmed_http200_requires_exact_primary_identity(monkeypatch, xml, expected):
    monkeypatch.setattr(extension, "get_xml", lambda *a, **k: envelope(xml))
    result = extension.pubmed_record("12345")
    assert result["ok"] is False and result["error"] == expected


def test_pubmed_dates_and_no_relation_do_not_prove_retraction_absence(monkeypatch):
    monkeypatch.setattr(extension, "get_xml", lambda *a, **k: envelope(pubmed_xml()))
    result = extension.pubmed_record("12345")
    assert result["ok"] and result["semantic_status"] == "NO_UPDATE_METADATA_FOUND"
    assert result["retraction_absence_proven"] is False and result["verification_pass"] is False


def test_retracted_publication_type_is_a_signal_without_comments_relation(monkeypatch):
    monkeypatch.setattr(extension, "get_xml", lambda *a, **k: envelope(pubmed_xml(publication_type="Retracted Publication")))
    result = extension.pubmed_record("12345")
    assert result["comments_corrections"] == []
    assert result["semantic_status"] == "UPDATE_METADATA_FOUND"


def test_transport_failure_does_not_look_like_empty_metadata(monkeypatch):
    failed = envelope(ok=False, http_status=429, error="HTTP_429")
    monkeypatch.setattr(extension, "get_json", lambda *a, **k: failed)
    monkeypatch.setattr(extension, "get_xml", lambda *a, **k: failed)
    for result in (extension.publication_updates(DOI), extension.pubmed_record("12345")):
        assert result["ok"] is False and result["semantic_status"] == "LOOKUP_FAILED"
        assert result["error"] == "HTTP_429" and result["http_status"] == 429


def test_input_notice_forward_update_is_not_followed_or_reversed(monkeypatch):
    calls = []

    def fake(host, path, params=None):
        calls.append(path)
        return envelope(work(NOTICE, **{"update-to": [{"DOI": DOI, "type": "retraction", "updated": DATE}]}))

    monkeypatch.setattr(extension, "get_json", fake)
    result = extension.publication_updates(NOTICE)
    assert result["update_to"][0]["DOI"] == DOI
    assert result["updated_by"] == [] and result["notices"] == [] and len(calls) == 1
    assert "retracted" not in result


def test_pubmed_namespace_and_book_identity(monkeypatch):
    xml = ET.fromstring('''<PubmedArticleSet xmlns="urn:fixture"><PubmedBookArticle><BookDocument>
    <PMID>12345</PMID><ArticleTitle>Book chapter</ArticleTitle></BookDocument>
    <PubmedBookData><ArticleIdList><ArticleId IdType="pubmed">12345</ArticleId>
    <ArticleId IdType="doi">10.5555/chapter</ArticleId></ArticleIdList></PubmedBookData>
    </PubmedBookArticle></PubmedArticleSet>''')
    monkeypatch.setattr(extension, "get_xml", lambda *a, **k: envelope(xml))
    result = extension.pubmed_record("12345")
    assert result["ok"] and result["title"] == "Book chapter"
    assert result["dois"] == ["10.5555/chapter"] and result["pmc_ids"] == []


def test_pubmed_relation_without_target_preserves_signal_and_flags_truncation(monkeypatch):
    corrections = '<CommentsCorrections RefType="RetractionIn"><RefSource>PRIVATE</RefSource></CommentsCorrections>' * 31
    monkeypatch.setattr(extension, "get_xml", lambda *a, **k: envelope(pubmed_xml(corrections=corrections)))
    result = extension.pubmed_record("12345")
    assert result["ok"] and result["record_fields_truncated"] is True
    assert len(result["comments_corrections"]) == 30
    assert "pmid" not in result["comments_corrections"][0]
    assert result["semantic_status"] == "UPDATE_METADATA_FOUND"


def test_pubmed_narrative_comments_are_not_update_signals(monkeypatch):
    corrections = '<CommentsCorrections RefType="CommentOn"><PMID>54321</PMID><Note>PRIVATE</Note></CommentsCorrections>'
    monkeypatch.setattr(extension, "get_xml", lambda *a, **k: envelope(pubmed_xml(corrections=corrections)))
    result = extension.pubmed_record("12345")
    assert result["comments_corrections"] == []
    assert result["semantic_status"] == "NO_UPDATE_METADATA_FOUND"

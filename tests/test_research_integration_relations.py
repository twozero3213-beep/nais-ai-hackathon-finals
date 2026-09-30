"""Offline contracts: candidates, direction, exact IDs, locations and safe boundaries."""
# [작성: 0 이영 · Codex] 2026-10-01 KST — 외부 관계·원문을 사용 원자료나 승인으로 오인하지 않는 경계를 모의 응답으로 검증한다.
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from core import research_integration_relations as relations

DOI = "10.5555/paper"
DATA = "10.5555/data"


def record(relation="IsSupplementTo", target=DOI, **attrs):
    values = {"doi": DATA, "titles": [{"title": "Public dataset"}],
              "types": {"resourceTypeGeneral": "Dataset"}, "version": "2",
              "url": "https://zenodo.org/records/123",
              "relatedIdentifiers": [{"relatedIdentifier": target, "relatedIdentifierType": "DOI", "relationType": relation}]}
    values.update(attrs)
    return {"id": DATA, "attributes": values}


def mock_datacite(monkeypatch, rows):
    calls = []
    def request(provider, path):
        calls.append((provider, path))
        return {"data": rows}
    monkeypatch.setattr(relations.research_data_sources, "_request", request)
    return calls


def article(body=None, license=True, doi=DOI, pmc="123", namespace=False):
    license_xml = '<permissions><license href="https://creativecommons.org/licenses/by/4.0/"></license></permissions>' if license else ""
    body = body or '<sec id="da"><title>Data Availability</title><p>Available in <ext-link href="https://doi.org/10.5555/data">repository</ext-link>.</p></sec>'
    ns = ' xmlns="urn:jats"' if namespace else ""
    return f'<article{ns}><front><article-meta><article-id pub-id-type="doi">{doi}</article-id><article-id pub-id-type="pmc">{pmc}</article-id>{license_xml}</article-meta></front><body><p>Background.</p>{body}</body><back><ref-list><ref id="R1"><element-citation><pub-id pub-id-type="doi">10.5555/cited-data</pub-id></element-citation></ref></ref-list></back></article>'.encode()


def mock_jats(monkeypatch, xml=None, rows=None):
    calls = []
    metadata = {"resultList": {"result": rows if rows is not None else [{"doi": DOI, "pmcid": "PMC123", "isOpenAccess": "Y"}]}}
    metadata_bytes = json.dumps(metadata).encode()
    def read(url):
        calls.append(url)
        return metadata_bytes if "/search?" in url else (xml if xml is not None else article())
    monkeypatch.setattr(relations.public_fulltext, "_read", read)
    return calls, metadata_bytes


@pytest.mark.parametrize("function", [relations.datacite_relations, relations.jats_data_availability])
@pytest.mark.parametrize("doi", ['https://doi.org/10.5555/paper', '10.5555/paper" OR *', '10.5555/paper\n', '10.5555/key?token=x', '10.5555/a@example.com'])
def test_invalid_doi_no_network(monkeypatch, function, doi):
    # Trailing whitespace is normalized by the shared DOI parser, so use internal control for that case.
    if doi.endswith("\n"):
        doi = "10.5555/pap\ner"
    monkeypatch.setattr(relations.public_fulltext, "_read", lambda *args: pytest.fail("network"))
    monkeypatch.setattr(relations.research_data_sources, "_request", lambda *args: pytest.fail("network"))
    with pytest.raises(ValueError):
        function(doi)


@pytest.mark.parametrize("limit", [True, 0, 11, 1.0, "1"])
def test_limit_is_strict(limit):
    with pytest.raises(ValueError, match="INVALID_LIMIT"):
        relations.datacite_relations(DOI, limit)


def test_datacite_fixed_query_direction_digest_and_candidates(monkeypatch):
    calls = mock_datacite(monkeypatch, [record()])
    result = relations.datacite_relations(DOI, 2)
    assert calls[0][0] == "datacite"
    assert calls[0][1].startswith("/dois?")
    query = parse_qs(urlsplit("https://api.datacite.org" + calls[0][1]).query)
    assert query == {"query": [f'relatedIdentifiers.relatedIdentifier:"{DOI}"'], "page[size]": ["2"]}
    edge = result["items"][0]
    assert edge["source_doi"] == DATA and edge["target_doi"] == DOI
    assert edge["relation_type"] == "IsSupplementTo"
    assert edge["classification"] == "SUPPLEMENT_CANDIDATE"
    assert edge["version"] == "2" and edge["resource_type"] == "Dataset"
    assert edge["provenance"]["metadata_pointer"] == "/data/0/attributes/relatedIdentifiers/0"
    assert result["response_sha256"] is None and len(result["received_metadata_sha256"]) == 64
    for item in (result, edge):
        assert item["candidate"] and not item["verified"] and not item["approved"]
    assert not edge["used_as_raw_data"]


@pytest.mark.parametrize("kind", ["Cites", "IsCitedBy", "References", "IsReferencedBy"])
def test_citation_never_used_data(monkeypatch, kind):
    mock_datacite(monkeypatch, [record(kind)])
    edge = relations.datacite_relations(DOI)["items"][0]
    assert edge["classification"] == "CITATION_ONLY" and not edge["used_as_raw_data"]
    assert edge["relation_type"] == kind


def test_exact_match_identity_and_relation_allowlist(monkeypatch):
    bad_id = record()
    bad_id["id"] = "10.5555/wrong"
    mock_datacite(monkeypatch, [record(target="10.5555/other"), bad_id, record("UsedRawData")])
    result = relations.datacite_relations(DOI)
    assert result["items"] == [] and result["rejected_record_or_edge_count"] == 2
    assert result["status"] == "NO_MATCH_IN_RETURNED_PAGE"
    assert not result["source_identity_checked"]


def test_version_edges_preserve_direction_no_invented_version(monkeypatch):
    row = record(version=None)
    row["attributes"]["relatedIdentifiers"] += [
        {"relatedIdentifier": "10.5555/all-versions", "relatedIdentifierType": "DOI", "relationType": "IsVersionOf"},
        {"relatedIdentifier": DOI, "relatedIdentifierType": "DOI", "relationType": "IsSupplementTo"}]
    mock_datacite(monkeypatch, [row])
    items = relations.datacite_relations(DOI)["items"]
    assert len(items) == 1 and items[0]["version"] is None
    version = items[0]["version_relations"][0]
    assert version["source_doi"] == DATA and version["target_doi"] == "10.5555/all-versions"
    assert version["relation_type"] == "IsVersionOf" and not version["approved"]


def test_datacite_sensitive_fields_suppressed(monkeypatch):
    mock_datacite(monkeypatch, [record(titles=[{"title": "Contact private@example.invalid"}], url="https://example.org?api_key=synthetic")])
    result = relations.datacite_relations(DOI)
    assert result["items"][0]["title"] is None and result["items"][0]["landing_url"] is None
    assert "private@example" not in json.dumps(result)


@pytest.mark.parametrize("value", [{"data": None}, {"data": [record()] * 6}, {"data": [], "unexpected": float("nan")}])
def test_datacite_invalid_metadata(monkeypatch, value):
    monkeypatch.setattr(relations.research_data_sources, "_request", lambda *args: value)
    assert relations.datacite_relations(DOI)["status"] == "INVALID_RESPONSE"


def test_datacite_safe_error(monkeypatch):
    def request(*args):
        raise relations.research_data_sources.DataSourceError("RATE_LIMITED")
    monkeypatch.setattr(relations.research_data_sources, "_request", request)
    assert relations.datacite_relations(DOI)["status"] == "RATE_LIMITED"


@pytest.mark.parametrize("namespace", [False, True])
def test_jats_exact_ids_license_locations_and_digests(monkeypatch, namespace):
    raw = article(namespace=namespace)
    calls, metadata = mock_jats(monkeypatch, raw)
    result = relations.jats_data_availability(DOI)
    assert len(calls) == 2 and calls[1] == relations.public_fulltext.BASE + "PMC123/fullTextXML"
    assert result["response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["http_status"] is None and result["http_status_scope"] == "UNAVAILABLE_IN_EXISTING_CLIENT"
    assert result["received_metadata_sha256"] == hashlib.sha256(metadata).hexdigest()
    assert result["license"] == "https://creativecommons.org/licenses/by/4.0/"
    item = result["items"][0]
    assert item["location"] == {"xpath": "/article[1]/body[1]/sec[1]", "element_id": "da", "section_title": "Data Availability", "body_paragraph_indices": [2]}
    assert item["links"][0]["doi"] == DATA and item["links"][0]["extraction"] == "EXPLICIT_EXT_LINK"
    assert not item["approved"] and not item["used_as_raw_data"] and not result["verified"]


@pytest.mark.parametrize("xml,status", [(article(doi="10.5555/other"), "FULLTEXT_ID_MISMATCH"), (article(pmc="999"), "FULLTEXT_ID_MISMATCH"), (article(license=False), "LICENSE_UNCONFIRMED"), (b'<not-article/>', "FULLTEXT_INVALID_XML"), (b'<article>', "FULLTEXT_INVALID_XML"), (b'<!DOCTYPE article [<!ENTITY x "test">]><article/>', "FULLTEXT_UNSAFE_XML")])
def test_jats_fails_closed_before_excerpt(monkeypatch, xml, status):
    mock_jats(monkeypatch, xml)
    result = relations.jats_data_availability(DOI)
    assert result["status"] == status and result["items"] == [] and not result["approved"]


def test_metadata_requires_exact_open_access_unique_pmcid(monkeypatch):
    calls, _ = mock_jats(monkeypatch, rows=[{"doi": "10.5555/other", "pmcid": "PMC123", "isOpenAccess": "Y"}])
    assert relations.jats_data_availability(DOI)["status"] == "NOT_AVAILABLE" and len(calls) == 1
    calls, _ = mock_jats(monkeypatch, rows=[{"doi": DOI, "pmcid": "PMC123", "isOpenAccess": "Y"}, {"doi": DOI, "pmcid": "PMC124", "isOpenAccess": "Y"}])
    assert relations.jats_data_availability(DOI)["status"] == "FULLTEXT_AMBIGUOUS_DOI" and len(calls) == 1


def test_general_references_do_not_become_data_candidates(monkeypatch):
    mock_jats(monkeypatch, article(body='<sec><title>Methods</title><p>We cite data <xref ref-type="bibr" rid="R1">1</xref>.</p></sec>'))
    result = relations.jats_data_availability(DOI)
    assert result["items"] == [] and result["status"] == "NO_EXPLICIT_AVAILABILITY_STATEMENT"


def test_availability_reference_location_and_nested_dedup(monkeypatch):
    body = '<sec sec-type="data-availability"><title>Availability</title><sec><title>Data Availability</title><p>See <xref ref-type="bibr" rid="R1">dataset</xref>.</p></sec></sec>'
    mock_jats(monkeypatch, article(body))
    result = relations.jats_data_availability(DOI)
    assert len(result["items"]) == 1
    link = result["items"][0]["links"][0]
    assert link["doi"] == "10.5555/cited-data" and link["extraction"] == "AVAILABILITY_REFERENCE_DOI"
    assert "/back[1]/ref-list[1]/ref[1]/" in link["source_xpath"]


def test_availability_private_statement_suppressed(monkeypatch):
    mock_jats(monkeypatch, article('<sec><title>Data Availability</title><p>Ask private@example.invalid.</p></sec>'))
    result = relations.jats_data_availability(DOI)
    assert result["status"] == "SENSITIVE_STATEMENTS_SUPPRESSED" and result["items"] == []
    assert result["suppressed_sensitive_statement_count"] == 1
    assert "private@example" not in json.dumps(result)


def test_availability_links_not_downloaded_and_unsafe_urls_omitted(monkeypatch):
    body = '<sec><title>Data Availability</title><p><ext-link href="http://example.org/file">insecure</ext-link><ext-link href="https://127.0.0.1/a">private</ext-link><ext-link href="https://example.org?token=synthetic">credential</ext-link><ext-link href="https://zenodo.org/records/1">public</ext-link></p></sec>'
    calls, _ = mock_jats(monkeypatch, article(body))
    result = relations.jats_data_availability(DOI)
    assert len(calls) == 2
    links = result["items"][0]["links"]
    assert len(links) == 1 and links[0]["url"] == "https://zenodo.org/records/1" and not links[0]["downloaded"]


def test_text_doi_is_candidate_and_paragraph_positions(monkeypatch):
    body = '<sec><title>Data Availability</title><p>Identifier 10.5555/data.</p><p>Second paragraph.</p></sec>'
    mock_jats(monkeypatch, article(body))
    item = relations.jats_data_availability(DOI)["items"][0]
    assert item["links"][0]["extraction"] == "TEXT_DOI_CANDIDATE"
    assert item["location"]["body_paragraph_indices"] == [2, 3]


def test_duplicate_reference_id_not_resolved(monkeypatch):
    raw = article('<sec><title>Data Availability</title><p><xref ref-type="bibr" rid="R1">data</xref></p></sec>')
    raw = raw.replace(b'</ref-list>', b'<ref id="R1"><pub-id pub-id-type="doi">10.5555/other</pub-id></ref></ref-list>')
    mock_jats(monkeypatch, raw)
    assert relations.jats_data_availability(DOI)["items"][0]["links"] == []


def test_reused_transport_error_masks_unexpected_message(monkeypatch):
    def read(url):
        raise ValueError("private@example.invalid")
    monkeypatch.setattr(relations.public_fulltext, "_read", read)
    result = relations.jats_data_availability(DOI)
    assert result["status"] == "INVALID_RESPONSE" and "private@example" not in json.dumps(result)


@pytest.mark.parametrize("option", [None, 0, 1, "true", [], {}])
def test_include_source_bytes_requires_explicit_bool_before_network(monkeypatch, option):
    # [수정: 0 이영 · Codex] 2026-10-01 KST — truthy 문자열·정수가 내부 원문 반환을 켜지 못하도록 검증한다.
    monkeypatch.setattr(relations.public_fulltext, "_read", lambda *args: pytest.fail("network"))
    with pytest.raises(ValueError, match="INVALID_SOURCE_BYTES_OPTION"):
        relations.jats_data_availability(DOI, include_source_bytes=option)


def test_default_source_receipt_json_safe_and_no_bytes(monkeypatch):
    raw = article()
    mock_jats(monkeypatch, raw)
    result = relations.jats_data_availability(DOI)
    assert "source_bytes" not in result
    assert result["source_kind"] == "LICENSED_JATS_RECEIVED"
    receipt = result["public_source_receipt"]
    assert set(receipt) == {"type", "schema", "url", "doi", "pmcid", "license", "sha256", "received_at"}
    assert receipt["type"] == "JATS_XML" and receipt["schema"] == "research_public_source_receipt/1"
    assert receipt["doi"] == DOI and receipt["pmcid"] == "PMC123"
    assert receipt["url"] == relations.public_fulltext.BASE + "PMC123/fullTextXML"
    assert receipt["license"] == result["license"] and receipt["sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["received_at"].endswith("+09:00")
    json.dumps(result, allow_nan=False)


def test_explicit_source_bytes_preserve_exact_received_digest(monkeypatch):
    raw = b'\xef\xbb\xbf' + article(namespace=True) + b'\r\n'
    calls, _ = mock_jats(monkeypatch, raw)
    result = relations.jats_data_availability(DOI, include_source_bytes=True)
    assert len(calls) == 2 and result["source_bytes"] is raw
    assert result["public_source_receipt"]["sha256"] == hashlib.sha256(result["source_bytes"]).hexdigest()
    assert not result["verified"] and not result["verification_pass"] and not result["approved"]
    assert not result["items"][0]["used_as_raw_data"]


@pytest.mark.parametrize("xml,status", [(article(license=False), "LICENSE_UNCONFIRMED"), (article(doi="10.5555/other"), "FULLTEXT_ID_MISMATCH"), (article(pmc="999"), "FULLTEXT_ID_MISMATCH"), (b'<!DOCTYPE article [<!ENTITY x "test">]><article/>', "FULLTEXT_UNSAFE_XML"), (b'<article>', "FULLTEXT_INVALID_XML")])
def test_source_bytes_not_returned_on_license_identity_or_parse_failure(monkeypatch, xml, status):
    mock_jats(monkeypatch, xml)
    result = relations.jats_data_availability(DOI, include_source_bytes=True)
    assert result["status"] == status and "source_bytes" not in result
    assert result["public_source_receipt"] is None and "source_kind" not in result
    assert not result["approved"]


def test_received_source_no_availability_still_not_verified(monkeypatch):
    raw = article('<sec><title>Methods</title><p>Public description.</p></sec>')
    mock_jats(monkeypatch, raw)
    result = relations.jats_data_availability(DOI, include_source_bytes=True)
    assert result["status"] == "NO_EXPLICIT_AVAILABILITY_STATEMENT"
    assert result["source_bytes"] is raw and result["items"] == []
    assert not result["verified"] and not result["approved"]


def test_public_receipt_never_contains_raw_source_text(monkeypatch):
    raw = article().replace(b'<front>', b'<front><notes>Contact private@example.invalid</notes>')
    mock_jats(monkeypatch, raw)
    result = relations.jats_data_availability(DOI, include_source_bytes=True)
    assert b'private@example.invalid' in result["source_bytes"]
    public = {key: value for key, value in result.items() if key != "source_bytes"}
    assert "private@example" not in json.dumps(public) and "Contact" not in json.dumps(result["public_source_receipt"])

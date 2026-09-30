"""Repository contracts: identity, published version, privacy and advertised fixity."""
# [작성: 0 이영 · Codex] 2026-10-01 00:35 KST — 신규 공개 조회가 임의 URL·미발행 자료·체크섬 오인을 허용하지 않는지 모의 응답으로 검증한다. 버전 0, 실파일·유료 API 호출 없음.
from copy import deepcopy
import json

import pytest

from core import repository_extensions as repositories


MD5 = "a" * 32
OTHER_MD5 = "b" * 32
RESPONSE_SHA = "c" * 64
TIME = "2026-10-01T00:35:45+09:00"


def envelope(data):
    return {"ok": True, "http_status": 200, "data": data, "source_url": "https://zenodo.org/api/records/123",
            "retrieved_at_kst": TIME, "response_sha256": RESPONSE_SHA, "error": None}


def zenodo():
    return {"id": 123, "doi": "10.5281/zenodo.123", "conceptdoi": "10.5281/zenodo.100", "updated": "2026-09-29T10:00:00Z",
            "metadata": {"title": "Dataset contact: private@example.org", "version": "v2.4", "access_right": "restricted", "license": {"id": "other-open"},
                         "creators": [{"name": "Private Person", "email": "private@example.org"}],
                         "related_identifiers": [{"identifier": "10.1234/paper.1", "relation": "isSupplementTo"}]},
            "files": [{"id": "file-id", "key": "data.csv", "size": 42, "checksum": "md5:" + MD5, "links": {"self": "https://untrusted.example/data"}}]}


def figshare():
    return {"id": 456, "title": "Supplement data", "doi": "10.6084/m9.figshare.456.v2", "version": 2,
            "license": {"value": 1, "name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
            "is_embargoed": True, "is_confidential": False, "download_disabled": False,
            "authors": [{"email": "private@example.org"}], "resource_doi": "10.1234/paper.1",
            "related_materials": [{"identifier": "10.1234/paper.2", "relation": "IsSupplementTo", "identifier_type": "DOI"}],
            "files": [{"id": 789, "name": "data.csv", "size": 31, "computed_md5": MD5, "supplied_md5": OTHER_MD5,
                       "is_link_only": False, "download_url": "https://untrusted.example/file"}]}


def dataverse():
    return {"status": "OK", "data": {"id": 42, "persistentUrl": "https://doi.org/10.7910/DVN/TEST",
            "latestVersion": {"versionNumber": 1, "versionMinorNumber": 2, "versionState": "RELEASED",
            "license": {"name": "CC0 1.0", "uri": "http://creativecommons.org/publicdomain/zero/1.0", "rightsIdentifier": "CC0-1.0"},
            "metadataBlocks": {"citation": {"fields": [{"typeName": "title", "value": "Replication data"},
                                                          {"typeName": "datasetContact", "value": [{"datasetContactEmail": "private@example.org"}]}]}},
            "files": [{"restricted": True, "dataFile": {"id": 43, "filename": "data.tab", "filesize": 52,
                       "contentType": "text/tab-separated-values", "checksum": {"type": "SHA-256", "value": "d" * 64}}}]}}}


def stub(monkeypatch, data):
    calls = []
    def request(host, path, params=None):
        calls.append((host, path, params))
        return envelope(deepcopy(data))
    monkeypatch.setattr(repositories, "get_json", request)
    return calls


@pytest.mark.parametrize("provider,identifier", [("zenodo", "https://zenodo.org/records/123"), ("zenodo", "0"), ("zenodo", "../123"),
    ("figshare", "123/../../account"), ("figshare", "10.6084/m9.figshare.123.v0"), ("dataverse", "https://evil.example/file"),
    ("dataverse", "10.7910/DVN/TEST@draft"), ("dataverse", "10.7910/DVN/TEST@1.0\n"), ("unsupported", "123"), (None, "123")])
def test_invalid_identifier_never_calls_network(monkeypatch, provider, identifier):
    calls = stub(monkeypatch, {})
    assert repositories.repository_record(provider, identifier)["success"] is False
    assert calls == []


def test_zenodo_concept_version_restricted_custom_license_and_privacy(monkeypatch):
    calls = stub(monkeypatch, zenodo())
    result = repositories.repository_record("zenodo", "10.5281/zenodo.123")
    assert result["success"] is True
    assert calls == [("zenodo.org", "/api/records/123", None)]
    record = result["items"][0]
    assert record["concept_doi"] == "10.5281/zenodo.100" and record["version"] == "v2.4"
    assert record["license"]["id"] == "other-open"
    assert record["license"]["reuse_authorization"] == "NOT_CONFIRMED"
    assert record["files"][0]["restricted"] is True
    checksum = record["files"][0]["checksum"]
    assert checksum["algorithm"] == "md5" and checksum["value"] == MD5
    assert checksum["verified_against_download"] is False
    assert record["provenance"]["response_sha256"] == RESPONSE_SHA
    assert "private@example.org" not in json.dumps(result)
    assert "creators" not in json.dumps(result) and "untrusted.example" not in json.dumps(result)
    assert result["approved"] is False and result["verified"] is False


def test_figshare_exact_version_and_supplied_checksum_separate(monkeypatch):
    calls = stub(monkeypatch, figshare())
    result = repositories.repository_record("figshare", "10.6084/m9.figshare.456.v2")
    assert result["success"] is True
    assert calls == [("api.figshare.com", "/v2/articles/456/versions/2", None)]
    file = result["items"][0]["files"][0]
    assert file["checksum"]["value"] == MD5 and file["checksum"]["origin"] == "repository_computed"
    assert file["supplied_checksum"]["value"] == OTHER_MD5 and file["supplied_checksum"]["origin"] == "uploader_supplied"
    assert file["restricted"] is True
    assert result["items"][0]["related_identifiers"][0]["identifier"] == "10.1234/paper.2"
    assert "private@example.org" not in json.dumps(result)


def test_dataverse_fixed_host_published_version_algorithm_and_privacy(monkeypatch):
    calls = stub(monkeypatch, dataverse())
    result = repositories.repository_record("dataverse", "doi:10.7910/DVN/TEST")
    assert result["success"] is True
    assert calls == [("dataverse.harvard.edu", "/api/datasets/:persistentId/", {"persistentId": "doi:10.7910/dvn/test"})]
    record = result["items"][0]
    assert record["version"] == "1.2" and record["access"]["files"] == "some_restricted"
    assert record["files"][0]["checksum"]["algorithm"] == "sha256"
    assert record["files"][0]["checksum"]["publisher_algorithm"] == "SHA-256"
    assert record["license"]["id"] == "CC0-1.0"
    assert "private@example.org" not in json.dumps(result) and "datasetContact" not in json.dumps(result)


def test_dataverse_pinned_version_binds_response(monkeypatch):
    raw = dataverse()
    version = raw["data"]["latestVersion"]
    version["datasetPersistentId"] = "doi:10.7910/DVN/TEST"
    calls = stub(monkeypatch, {"status": "OK", "data": version})
    assert repositories.repository_record("dataverse", "10.7910/DVN/TEST@1.2")["success"] is True
    assert calls[0][1].endswith("/versions/1.2")
    assert repositories.repository_record("dataverse", "10.7910/DVN/TEST@1.3")["success"] is False


@pytest.mark.parametrize("change", ["bad_hash", "negative_size", "bad_identity", "draft"])
def test_malformed_or_unpublished_dataverse_response_fails(monkeypatch, change):
    raw = dataverse()
    version = raw["data"]["latestVersion"]
    if change == "bad_hash": version["files"][0]["dataFile"]["checksum"]["value"] = "not-a-hash"
    if change == "negative_size": version["files"][0]["dataFile"]["filesize"] = -1
    if change == "bad_identity": raw["data"]["persistentUrl"] = "https://doi.org/10.7910/DVN/OTHER"
    if change == "draft": version["versionState"] = "DRAFT"
    stub(monkeypatch, raw)
    result = repositories.repository_record("dataverse", "10.7910/DVN/TEST")
    assert result["success"] is False and result["items"] == []


def test_missing_file_checksum_is_explicit_unverified_metadata(monkeypatch):
    raw = figshare()
    raw["files"][0]["computed_md5"] = ""
    raw["files"][0]["supplied_md5"] = ""
    raw["files"][0]["is_link_only"] = True
    stub(monkeypatch, raw)
    file = repositories.repository_record("figshare", "456")["items"][0]["files"][0]
    assert file["checksum"] is None and file["link_only"] is True


def test_provider_identity_and_requested_version_mismatch_fail(monkeypatch):
    stub(monkeypatch, figshare())
    assert repositories.repository_record("figshare", "455")["success"] is False
    assert repositories.repository_record("figshare", "10.6084/m9.figshare.456.v1")["success"] is False


# [수정: 0 이영 · Codex] 2026-10-01 00:45 KST — DOI와 접근 제한 필드의 충돌·누락이 잘못된 공개 판단을 만들지 않는지 검증한다. 버전 0.
@pytest.mark.parametrize("provider,identifier,raw", [("zenodo", "10.5281/zenodo.123", zenodo()),
    ("figshare", "10.6084/m9.figshare.456.v2", figshare())])
def test_doi_identity_collision_fails_even_when_numeric_id_matches(monkeypatch, provider, identifier, raw):
    raw = deepcopy(raw)
    raw["doi"] = "10.1234/unrelated"
    stub(monkeypatch, raw)
    assert repositories.repository_record(provider, identifier)["success"] is False


def test_missing_access_flag_does_not_infer_public_download(monkeypatch):
    raw = figshare()
    raw["is_embargoed"] = False
    del raw["download_disabled"]
    stub(monkeypatch, raw)
    result = repositories.repository_record("figshare", "456")
    assert result["success"] is True
    assert result["items"][0]["access"]["files"] == "NOT_CHECKED"
    assert result["items"][0]["files"][0]["restricted"] is None


def test_unversioned_figshare_doi_can_resolve_latest_version_doi(monkeypatch):
    stub(monkeypatch, figshare())
    assert repositories.repository_record("figshare", "10.6084/m9.figshare.456")["success"] is True


@pytest.mark.parametrize("query,limit", [("private@example.org", 5), ("climate\nscience", 5), ("api_key=value", 5),
    ("https://evil.example/file", 5), ("climate", 11), ("climate", True), ("", 5)])
def test_invalid_search_has_no_network(monkeypatch, query, limit):
    calls = stub(monkeypatch, {})
    assert repositories.search_repository("zenodo", query, limit)["success"] is False
    assert calls == []


def test_zenodo_search_quotes_syntax_and_preserves_total(monkeypatch):
    calls = stub(monkeypatch, {"hits": {"total": {"value": 7}, "hits": [zenodo()]}})
    result = repositories.search_repository("zenodo", 'climate OR "private"', 1)
    assert result["success"] is True and result["total"] == 7
    assert calls[0][2]["q"] == '"climate OR \\"private\\""'
    assert calls[0][2]["size"] == 1


def test_dataverse_search_does_not_claim_unfetched_file_details(monkeypatch):
    calls = stub(monkeypatch, {"status": "OK", "data": {"total_count": 3, "items": [{"global_id": "doi:10.7910/DVN/TEST", "name": "Dataset", "majorVersion": 1, "minorVersion": 0,
                          "contacts": [{"email": "private@example.org"}]}]}})
    result = repositories.search_repository("dataverse", "climate", 2)
    assert result["success"] is True and result["total"] == 3
    assert calls[0][2] == {"q": '"climate"', "type": "dataset", "per_page": 2}
    record = result["items"][0]
    assert record["license"] is None and record["files"] == [] and record["detail_status"] == "NOT_FETCHED"
    assert "private@example.org" not in json.dumps(result)


def test_figshare_get_search_requires_exact_doi(monkeypatch):
    calls = stub(monkeypatch, [{"id": 456, "title": "Data", "doi": "10.6084/m9.figshare.456.v2"}])
    assert repositories.search_repository("figshare", "climate")["error"] == "SEARCH_REQUIRES_DOI"
    assert calls == []
    result = repositories.search_repository("figshare", "10.6084/m9.figshare.456.v2", 1)
    assert result["success"] is True and calls[0][2]["doi"] == "10.6084/m9.figshare.456.v2"


def test_over_limit_or_malformed_search_response_fails(monkeypatch):
    stub(monkeypatch, {"hits": {"total": 2, "hits": [zenodo(), zenodo()]}})
    assert repositories.search_repository("zenodo", "climate", 1)["success"] is False
    stub(monkeypatch, {"hits": {"total": True, "hits": []}})
    assert repositories.search_repository("zenodo", "climate", 1)["success"] is False


def test_transport_failure_does_not_echo_raw_provider_error(monkeypatch):
    monkeypatch.setattr(repositories, "get_json", lambda *args, **kwargs: {"ok": False, "error": "contact private@example.org", "http_status": 403})
    result = repositories.repository_record("zenodo", "123")
    assert result["success"] is False and result["error"] == "TRANSPORT_ERROR" and result["http_status"] == 403
    assert "private@example.org" not in json.dumps(result)


def test_unsupported_provider_never_reflects_private_input(monkeypatch):
    calls = stub(monkeypatch, {})
    result = repositories.repository_record("private@example.org", "123")
    assert result["provider"] is None and "private@example.org" not in json.dumps(result)
    assert calls == []

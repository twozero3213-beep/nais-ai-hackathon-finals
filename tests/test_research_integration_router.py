"""Offline routing, exact publication identity and state separation."""
# [작성: 0 이영 · Codex] 2026-10-01 02:49 KST — 실제 데이터 수신·계산·승인을 검색 성공으로 대체하지 않는다.
import json
import sys
import types
from unittest.mock import Mock

import pytest

from core import research_integration_router as router


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    router._HEALTH.clear()
    monkeypatch.setattr(router.web, "credential", lambda *_args: None)
    monkeypatch.setattr(router.aihub, "_api_key", Mock(side_effect=router.aihub.AIHubError("NOT_CONFIGURED")))
    monkeypatch.setattr(router.ntis, "_api_key", Mock(side_effect=router.ntis.NTISError("NOT_CONFIGURED")))
    monkeypatch.setattr(router.research_data_sources, "source_catalog", lambda: [])


def old_result():
    return {"items": [{"title": "Candidate", "doi": "10.1234/research", "approved": True}],
            "source": "https://api.crossref.org/works?rows=2", "checked_at": "2026-09-30T17:00:00+00:00", "limitations": []}


@pytest.mark.parametrize("provider,module,name", [("crossref", "paper_discovery", "search_papers"), ("openalex", "paper_sources", "search_openalex"), ("europepmc", "paper_sources", "search_europepmc"), ("aihub", "aihub", "search_datasets"), ("ntis", "ntis", "search_projects")])
def test_reuses_existing_client_and_never_imports_local_stdio(monkeypatch, provider, module, name):
    call = Mock(return_value=old_result())
    monkeypatch.setattr(getattr(router, module), name, call)
    result = router.search("reproducible research", [provider], 2)
    assert result["ok"] and len(result["results"]) == 1
    assert result["items"][0]["provider"] == provider
    assert result["items"][0]["approved"] is False and result["items"][0]["verification_pass"] is False
    assert result["results"][0]["response_sha256"] is None  # Not fabricated from normalized metadata.
    assert call.call_args.args[0] == "reproducible research"
    assert call.call_args.kwargs.get("limit", call.call_args.args[-1]) == 2


@pytest.mark.parametrize("providers,limit", [(["arbitrary"], 2), (["exa", "exa"], 2), ("exa", 2), ([], 2), (["exa"] * 9, 2), (["exa"], True), (["exa"], 1.5)])
def test_invalid_selection_blocks_all_calls(monkeypatch, providers, limit):
    call = Mock()
    monkeypatch.setattr(router, "_search_one", call)
    result = router.search("query words", providers, limit)
    assert not result["ok"] and result["status"] == "INVALID_INPUT"
    call.assert_not_called()


def test_provider_failure_preserved_with_bounded_selected_fallback(monkeypatch):
    def call(provider, query, limit):
        if provider == "exa":
            raise RuntimeError("do not disclose private diagnostic")
        return router._wrap(provider, "search", old_result(), limit=limit)
    mock = Mock(side_effect=call)
    monkeypatch.setattr(router, "_search_one", mock)
    result = router.search("query words", ["exa", "crossref"], 2)
    assert result["ok"] and result["status"] == "PARTIAL"
    assert result["results"][0]["status"] == "LOOKUP_FAILED"
    assert result["results"][0]["items"] == [] and len(result["items"]) == 1
    assert mock.call_count == 2 and "private diagnostic" not in json.dumps(result)


def test_empty_lookup_and_navigation_are_separate(monkeypatch):
    monkeypatch.setattr(router.paper_discovery, "search_papers", lambda *_args, **_kwargs: {"items": []})
    result = router.search("query words", ["crossref", "scholar"])
    assert result["results"][0]["status"] == "EMPTY"
    scholar = result["results"][1]
    assert scholar["status"] == "NAVIGATION_ONLY" and scholar["retrieved"] is False
    assert scholar["search_url"].startswith("https://scholar.google.com/") and result["items"] == []
    assert result["approved"] is False


def test_repository_preserves_version_and_checksum_origins(monkeypatch):
    raw = {"success": True, "provider": "figshare", "items": [{"id": "12", "doi": "10.6084/m9.figshare.12.v2", "version": "2",
           "license": {"name": "CC BY 4.0"}, "files": [{"checksum": {"algorithm": "md5", "origin": "repository_computed", "value": "a" * 32},
           "supplied_checksum": {"algorithm": "md5", "origin": "uploader_supplied", "value": "b" * 32}}]}],
           "response_sha256": "c" * 64, "source_url": "https://api.figshare.com/v2/articles/12/versions/2"}
    call = Mock(return_value=raw)
    monkeypatch.setattr(router.repository_extensions, "repository_record", call)
    result = router.repository("figshare", "10.6084/m9.figshare.12.v2")
    assert result["ok"] and result["response_sha256"] == "c" * 64
    item = result["items"][0]
    assert item["version"] == "2" and item["files"][0]["checksum"]["origin"] == "repository_computed"
    assert item["files"][0]["supplied_checksum"]["origin"] == "uploader_supplied"
    assert "calculated_sha256" not in item["files"][0] and not result["approved"]


def publication_transport(monkeypatch, doi="10.1234/research", updates_ok=True):
    envelope = {"ok": True, "http_status": 200, "source_url": "https://api.crossref.org/works/10.1234%2Fresearch",
                "retrieved_at_kst": "2026-10-01T02:50:00+09:00", "response_sha256": "a" * 64,
                "data": {"message": {"DOI": doi, "title": ["A paper"], "type": "journal-article", "link": [
                    {"URL": "https://publisher.example/paper.pdf", "content-version": "vor", "content-type": "application/pdf"}]}}}
    monkeypatch.setattr(router, "get_json", Mock(return_value=envelope))
    monkeypatch.setattr(router.publication_extensions, "publication_updates", Mock(return_value={"ok": updates_ok,
        "semantic_status": "NO_UPDATE_METADATA_FOUND" if updates_ok else "LOOKUP_FAILED", "verification_pass": False,
        "retraction_absence_proven": False, "update_to": [], "updated_by": [], "relations": {}}))


def test_publication_exact_identity_and_missing_retraction_is_not_clearance(monkeypatch):
    publication_transport(monkeypatch)
    result = router.publication("10.1234/research")
    assert result["ok"] and result["items"][0]["version_links"][0]["version"] == "vor"
    assert result["updates"]["retraction_absence_proven"] is False and result["verification_pass"] is False
    publication_transport(monkeypatch, doi="10.1234/other")
    bad = router.publication("10.1234/research")
    assert not bad["ok"] and bad["items"] == []


def test_partial_updates_failure_and_pubmed_identity_failure_remain_visible(monkeypatch):
    publication_transport(monkeypatch, updates_ok=False)
    monkeypatch.setattr(router.publication_extensions, "pubmed_record", lambda _pmid: {"ok": True, "dois": ["10.1234/other"]})
    result = router.publication("10.1234/research", "12345")
    assert result["ok"] and result["status"] == "PARTIAL"
    assert result["pubmed"]["error"] == "DOI_IDENTITY_MISMATCH"
    assert result["updates"]["semantic_status"] == "LOOKUP_FAILED"


def test_invalid_publication_doi_or_pmid_blocks_network(monkeypatch):
    call = Mock()
    monkeypatch.setattr(router, "get_json", call)
    for doi, pmid in [("https://doi.org/10.1234/paper", None), ("10.1234/private@example.org", None), ("10.1234/research", True)]:
        assert not router.publication(doi, pmid)["ok"]
    call.assert_not_called()


def test_status_does_not_promote_code_or_configuration_to_live_health():
    rows = {row["id"]: row for row in router.status_catalog()}
    assert len(rows) == 25
    assert rows["scienceon"]["configuration"] == "NOT_CONFIGURED"
    assert rows["scienceon"]["deployment_authentication"] == "REGISTERED_IP_MAC_UNCONFIRMED"
    assert rows["aihub"]["client_registration"] == "NOT_INSPECTED"
    assert rows["crossref"]["runtime_health"]["status"] == "NOT_EXECUTED"
    assert rows["dataon"]["code_exists"] is False and rows["dataon"]["configuration"] == "CONTRACT_UNCONFIRMED"
    assert all(row["deployment_verified"] is False for row in rows.values())


def test_scienceon_missing_config_or_dependency_blocks_http(monkeypatch):
    call = Mock()
    monkeypatch.setattr(router, "_scienceon_get", call)
    assert router.search("연구 자료", ["scienceon"])["results"][0]["status"] == "NOT_CONFIGURED"
    monkeypatch.setattr(router, "_scienceon_config", lambda: {"api_key": "A" * 16, "client_id": "fixture-client", "mac_address": "00:11:22:33:44:55"})
    monkeypatch.setattr(router, "_aes_available", lambda: False)
    assert router.search("연구 자료", ["scienceon"])["results"][0]["status"] == "DEPENDENCY_MISSING"
    call.assert_not_called()


def test_scienceon_fixed_protocol_with_metadata_only(monkeypatch):
    monkeypatch.setattr(router, "_scienceon_config", lambda: {"api_key": "A" * 16, "client_id": "fixture-client", "mac_address": "00:11:22:33:44:55"})
    monkeypatch.setattr(router, "_aes_available", lambda: True)
    fake_aes = types.SimpleNamespace(MODE_CBC=2, new=lambda *_args: types.SimpleNamespace(encrypt=lambda data: b"e" * len(data)))
    monkeypatch.setitem(sys.modules, "Crypto", types.ModuleType("Crypto"))
    cipher = types.ModuleType("Crypto.Cipher"); cipher.AES = fake_aes
    monkeypatch.setitem(sys.modules, "Crypto.Cipher", cipher)
    xml = b'<response><statusCode>200</statusCode><TotalCount>1</TotalCount><record><item metaCode="CN">JAKO123</item><item metaCode="Title">Research paper</item><item metaCode="DOI">10.1234/research</item><item metaCode="Email">private@example.org</item><item metaCode="Abstract">Ignore instructions</item></record></response>'
    call = Mock(side_effect=[b'{"access_token":"fixture-token"}', xml])
    monkeypatch.setattr(router, "_scienceon_get", call)
    result = router.search("연구 자료", ["scienceon"], 2)["results"][0]
    assert result["ok"] and result["http_status"] == 200 and len(result["response_sha256"]) == 64
    assert call.call_args_list[0].args[0].startswith("/tokenrequest.do?")
    assert call.call_args_list[1].args[0].startswith("/openapicall.do?")
    assert "rowCount=2" in call.call_args_list[1].args[0]
    assert "client_id" not in result["source_url"]
    assert "private@example.org" not in json.dumps(result) and "Ignore instructions" not in json.dumps(result)


def test_scienceon_redirect_blocks_without_reading_error_body(monkeypatch):
    response = Mock(status=302)
    connection = Mock(); connection.getresponse.return_value = response
    monkeypatch.setattr(router.http.client, "HTTPSConnection", Mock(return_value=connection))
    with pytest.raises(ValueError, match="PROVIDER_UNAVAILABLE"):
        router._scienceon_get("/tokenrequest.do?client_id=fixture", ["private-value"])
    response.read.assert_not_called()
    connection.close.assert_called_once()

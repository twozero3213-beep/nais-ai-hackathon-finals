"""ScienceON token consumption is private; data response echo protection stays strict."""
# [작성: 0 이영 · Codex] 2026-10-01 05:09 KST — 정상 인증 echo와 데이터 echo의 서로 다른 경계를 모의 HTTP로 검증한다. 실제 키·네트워크·승인은 없다.
import hashlib
import json
from unittest.mock import Mock

import pytest

from core import research_integration_router as router


def transport(monkeypatch, raw, status=200):
    response = Mock(status=status)
    response.read.return_value = raw
    connection = Mock()
    connection.getresponse.return_value = response
    factory = Mock(return_value=connection)
    monkeypatch.setattr(router.http.client, "HTTPSConnection", factory)
    return factory, connection, response


def test_auth_echo_is_consumed_only_after_strict_token_and_unknown_fields_discarded(monkeypatch):
    raw = json.dumps({"access_token": "fixture-token", "client_id": "fixture-client",
                      "mac_address": "00:11:22:33:44:55", "api_key": "fixture-api",
                      "accounts": "fixture-accounts", "refresh_token": "fixture-refresh",
                      "unknown": "private@example.invalid"}).encode()
    factory, connection, response = transport(monkeypatch, raw)
    private = ["fixture-api", "fixture-client", "00:11:22:33:44:55", "fixture-accounts"]
    consumed = router._scienceon_get("/tokenrequest.do?fixture=1", private)
    assert json.loads(consumed) == {"access_token": "fixture-token"}
    assert consumed != raw and b"refresh" not in consumed and b"unknown" not in consumed
    factory.assert_called_once_with("apigateway.kisti.re.kr", timeout=20)
    response.read.assert_called_once_with(65537)
    connection.close.assert_called_once()


@pytest.mark.parametrize("raw", [
    b'{"client_id":"fixture-client"}', b'{"access_token":""}',
    b'{"access_token":null}', b'{"access_token":true}', b'{"access_token":3}',
    b'{"access_token":["token"]}', b'["token"]', b'not json',
    b'{"access_token":"one","access_token":"two"}',
    b'{"access_token":"\\u001f"}', b'{"access_token":"has space"}',
    b'{"access_token":"\\u007f"}', b'{"access_token":"\\ud55c"}',
    json.dumps({"access_token": "a" * 513}).encode(), b'\xff',
], ids=["missing", "empty", "null", "bool", "number", "list-token", "list-response",
        "invalid-json", "duplicate-token", "control", "space", "delete", "non-ascii", "too-long", "invalid-utf8"])
def test_invalid_or_missing_auth_token_is_never_authentication_success(monkeypatch, raw):
    _, connection, _ = transport(monkeypatch, raw)
    with pytest.raises(ValueError, match="^AUTH_REQUIRED$"):
        router._scienceon_get("/tokenrequest.do?fixture=1", ["fixture-client"])
    connection.close.assert_called_once()


@pytest.mark.parametrize("status,code", [(302, "PROVIDER_UNAVAILABLE"), (401, "AUTH_REQUIRED"),
                                         (403, "PERMISSION_DENIED"), (429, "RATE_LIMITED")])
def test_auth_error_status_has_no_read_or_redirect(monkeypatch, status, code):
    _, connection, response = transport(monkeypatch, b"private body", status)
    with pytest.raises(ValueError, match="^" + code + "$"):
        router._scienceon_get("/tokenrequest.do?fixture=1", [])
    response.read.assert_not_called()
    connection.close.assert_called_once()


def test_auth_size_is_bounded(monkeypatch):
    _, connection, _ = transport(monkeypatch, b"a" * 65537)
    with pytest.raises(ValueError, match="^RESPONSE_TOO_LARGE$"):
        router._scienceon_get("/tokenrequest.do?fixture=1", [])
    connection.close.assert_called_once()


@pytest.mark.parametrize("echo", ["fixture-client", "fixture-api", "fixture-token", "fixture-accounts",
                                 "fixture&#45;client"])
def test_data_echo_guard_remains_strict_for_all_private_values(monkeypatch, echo):
    raw = ("<response><note>" + echo + "</note></response>").encode()
    _, connection, _ = transport(monkeypatch, raw)
    with pytest.raises(ValueError, match="^PRIVATE_RESPONSE$"):
        router._scienceon_get("/openapicall.do?fixture=1", ["fixture-client", "fixture-api", "fixture-token", "fixture-accounts"])
    connection.close.assert_called_once()


def test_authentication_failure_stops_before_data_call(monkeypatch):
    monkeypatch.setattr(router, "_scienceon_config", lambda: {"api_key": "A" * 16, "client_id": "fixture-client", "mac_address": "00:11:22:33:44:55"})
    _, connection, _ = transport(monkeypatch, b'{"client_id":"fixture-client"}')
    result = router.search("cancer", ["scienceon"], 1)["results"][0]
    assert not result["ok"] and result["status"] == "AUTH_REQUIRED" and result["items"] == []
    assert result["response_sha256"] is None and result["verification_pass"] is False
    assert connection.request.call_count == 1


def test_success_hashes_only_data_and_never_publishes_auth_values(monkeypatch):
    config = {"api_key": "A" * 16, "client_id": "fixture-client", "mac_address": "00:11:22:33:44:55"}
    monkeypatch.setattr(router, "_scienceon_config", lambda: config)
    auth = json.dumps({"access_token": "fixture-token", "client_id": config["client_id"], "refresh_token": "fixture-refresh"}).encode()
    data = b'<response><statusCode>200</statusCode><TotalCount>1</TotalCount><record><item metaCode="CN">JAKO123</item><item metaCode="Title">Fixture research</item></record></response>'
    first = Mock(status=200); first.read.return_value = auth
    second = Mock(status=200); second.read.return_value = data
    connection = Mock(); connection.getresponse.side_effect = [first, second]
    monkeypatch.setattr(router.http.client, "HTTPSConnection", Mock(return_value=connection))
    result = router.search("cancer", ["scienceon"], 1)["results"][0]
    assert result["ok"] and len(result["items"]) == 1
    public_items = [{key: value for key, value in item.items() if key != "provenance"} for item in result["items"]]
    normalized = json.dumps({"provider": "scienceon", "operation": "search", "total": 1, "items": public_items},
                            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert result["response_sha256"] == hashlib.sha256(normalized).hexdigest()
    assert result["response_sha256"] != hashlib.sha256(data).hexdigest()
    assert result["response_sha256_scope"] == "PUBLIC_NORMALIZED_METADATA"
    public = json.dumps(result)
    assert all(value not in public for value in (*config.values(), "fixture-token", "fixture-refresh"))
    assert hashlib.sha256(auth).hexdigest() not in public
    assert result["verified"] is False and result["approved"] is False
    assert connection.request.call_count == 2 and connection.close.call_count == 2


# [추가: 0 이영 · Codex] 2026-10-01 05:52 KST — 실제 고정 parameterData echo만 소비하고 다른 경로/형식/지문 우회를 차단하는 모의 회귀.
PRIVATE = ["fixture-api", "fixture-client", "00:11:22:33:44:55", "fixture-accounts", "fixture-token"]
PARAMETER = '<client_id>fixture-client</client_id><token>fixture-token</token>'
RECORD = '<record><item metaCode="CN">JAKO123</item><item metaCode="Title">Fixture research</item></record>'


def gateway_xml(parameter=PARAMETER, records=RECORD, total="1", status="200", extra=""):
    return ("<MetaData><parameterData>" + parameter + "</parameterData><recordList>" + records +
            "</recordList><resultSummary><statusCode>" + status + "</statusCode><TotalCount>" + total +
            "</TotalCount></resultSummary>" + extra + "</MetaData>").encode()


def test_only_exact_expected_gateway_request_echo_is_consumed(monkeypatch):
    raw = gateway_xml()
    _, connection, _ = transport(monkeypatch, raw)
    clean = router._scienceon_get("/openapicall.do?fixture=1", PRIVATE)
    assert b"fixture-client" not in clean and b"fixture-token" not in clean
    assert b'Fixture research' in clean and b'JAKO123' in clean
    root = router.ET.fromstring(clean)
    assert root.find("parameterData/client_id").text is None
    assert root.find("parameterData/token").text is None
    connection.close.assert_called_once()


@pytest.mark.parametrize("parameter,extra", [
    (PARAMETER + '<client_id>fixture-client</client_id>', ""),
    (PARAMETER + '<token>fixture-token</token>', ""),
    ('<client_id>other-client</client_id><token>fixture-token</token>', ""),
    ('<client_id>fixture-client</client_id><token>wrong-token</token>', ""),
    ('<client_id>fixture-client</client_id>', ""),
    ('<wrap>' + PARAMETER + '</wrap>', ""),
    ('<client_id a="1">fixture-client</client_id><token>fixture-token</token>', ""),
    ('<client_id>fixture-client<b/></client_id><token>fixture-token</token>', ""),
    ('<client_id>fixture-client</client_id>tail<token>fixture-token</token>', ""),
    (PARAMETER, '<parameterData>' + PARAMETER + '</parameterData>'),
    (PARAMETER, '<recordList/>'), (PARAMETER, '<resultSummary/>'),
], ids=["duplicate-client", "duplicate-token", "wrong-client", "wrong-token", "missing-token", "nested-auth", "auth-attribute", "auth-child", "auth-tail", "duplicate-parameter", "duplicate-recordlist", "duplicate-summary"])
def test_malformed_fixed_auth_or_top_level_metadata_is_rejected(monkeypatch, parameter, extra):
    transport(monkeypatch, gateway_xml(parameter=parameter, extra=extra))
    with pytest.raises(ValueError, match="^INVALID_RESPONSE$"):
        router._scienceon_get("/openapicall.do?fixture=1", PRIVATE)


@pytest.mark.parametrize("raw", [
    gateway_xml(parameter=PARAMETER + '<other>fixture-token</other>'),
    gateway_xml(parameter=PARAMETER + '<other>fixture-client</other>'),
    gateway_xml(parameter=PARAMETER + '<other>fixture-api</other>'),
    gateway_xml(parameter=PARAMETER + '<other>fixture-accounts</other>'),
    gateway_xml(parameter=PARAMETER + '<other>00:11:22:33:44:55</other>'),
    gateway_xml(parameter=PARAMETER + '<other a="fixture-token"/>'),
    gateway_xml(parameter=PARAMETER + '<!-- fixture-token -->'),
    gateway_xml(parameter=PARAMETER + '<?metadata fixture-token ?>'),
    gateway_xml(records=RECORD.replace('Fixture research', 'fixture-token')),
    gateway_xml(records=RECORD + '<item metaCode="private">fixture-client</item>'),
    gateway_xml(records=RECORD.replace('Fixture research', 'fixture&#45;token')),
    gateway_xml(records=RECORD + '<note a="fixture-client"/>'),
    gateway_xml().replace(b'<recordList>', b'<recordList a="fixture-client">'),
], ids=["other-token", "other-client", "other-api", "other-accounts", "other-mac", "other-attribute", "comment", "pi", "public-title", "unselected-field", "encoded-title", "record-attribute", "list-attribute"])
def test_any_other_private_echo_path_remains_private_response(monkeypatch, raw):
    transport(monkeypatch, raw)
    with pytest.raises(ValueError, match="^PRIVATE_RESPONSE$"):
        router._scienceon_get("/openapicall.do?fixture=1", PRIVATE)


@pytest.mark.parametrize("raw", [
    b'<!DOCTYPE MetaData SYSTEM "https://invalid.example/dtd">' + gateway_xml(),
    b'<!DOCTYPE MetaData [<!ENTITY private "fixture-token">]>' + gateway_xml(),
    ('<!DOCTYPE MetaData [<!ENTITY private "fixture-token">]>' + gateway_xml().decode()).encode("utf-16"),
    gateway_xml(records=RECORD + '<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="file:///not-read"/>'),
    gateway_xml()[:-3], b'{"records": []}',
], ids=["external-dtd", "internal-entity", "utf16-entity", "xinclude-file", "truncated", "wrong-json-contract"])
def test_data_xml_entity_external_reference_and_parse_failure_are_rejected(monkeypatch, raw):
    transport(monkeypatch, raw)
    with pytest.raises(ValueError, match="^INVALID_RESPONSE$"):
        router._scienceon_get("/openapicall.do?fixture=1", PRIVATE)


def gateway_search(monkeypatch, data):
    monkeypatch.setattr(router, "_scienceon_config", lambda: {"api_key": "A" * 16, "client_id": "fixture-client", "mac_address": "00:11:22:33:44:55"})
    first = Mock(status=200); first.read.return_value = b'{"access_token":"fixture-token","client_id":"fixture-client"}'
    second = Mock(status=200); second.read.return_value = data
    connection = Mock(); connection.getresponse.side_effect = [first, second]
    monkeypatch.setattr(router.http.client, "HTTPSConnection", Mock(return_value=connection))
    return router.search("cancer", ["scienceon"], 1)["results"][0], connection


def test_fixed_echo_success_only_fingerprints_normalized_public_metadata(monkeypatch):
    raw = gateway_xml()
    result, connection = gateway_search(monkeypatch, raw)
    assert result["ok"] and result["status"] == "SUCCESS" and len(result["items"]) == 1
    assert result["response_sha256_scope"] == "PUBLIC_NORMALIZED_METADATA"
    assert result["response_sha256"] != hashlib.sha256(raw).hexdigest()
    assert result["items"][0]["provenance"]["response_sha256_scope"] == "PUBLIC_NORMALIZED_METADATA"
    assert result["verified"] is False and result["approved"] is False
    public = json.dumps(result)
    assert all(value not in public for value in PRIVATE)
    assert connection.request.call_count == 2
    rows = {row["id"]: row for row in router.status_catalog()}
    assert rows["scienceon"]["runtime_health"]["response_sha256_scope"] == "PUBLIC_NORMALIZED_METADATA"


@pytest.mark.parametrize("data,status", [
    (gateway_xml(records="", total="0"), "EMPTY"),
    (gateway_xml(status="500"), "PROVIDER_REJECTED"),
    (gateway_xml(total="0"), "INVALID_RESPONSE"),
    (gateway_xml(records="", total="1"), "INVALID_RESPONSE"),
    (gateway_xml().replace(b'<TotalCount>1</TotalCount>', b'<TotalCount>1</TotalCount><TotalCount>1</TotalCount>'), "INVALID_RESPONSE"),
    (gateway_xml().replace(b'<statusCode>200</statusCode>', b'<statusCode>200</statusCode><statusCode>200</statusCode>'), "INVALID_RESPONSE"),
    (gateway_xml(parameter=PARAMETER + RECORD), "INVALID_RESPONSE"),
], ids=["genuine-empty", "server-error-200http", "inconsistent-count", "missing-records", "duplicate-total", "duplicate-status", "record-outside-list"])
def test_http200_does_not_override_empty_provider_errors_or_shape(monkeypatch, data, status):
    result, _ = gateway_search(monkeypatch, data)
    assert result["status"] == status
    assert result["ok"] is (status == "EMPTY")
    if status != "EMPTY":
        assert result["items"] == [] and result["response_sha256"] is None

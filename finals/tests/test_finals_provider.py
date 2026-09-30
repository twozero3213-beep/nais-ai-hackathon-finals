"""공급자 원문과 인증 값이 오류·보고서로 반사되지 않는지 네트워크 없이 검사한다."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

FINALS = Path(__file__).resolve().parents[1]
if str(FINALS) not in sys.path:
    sys.path.insert(0, str(FINALS))
import finals_provider as provider

TEST_KEY = "provider-regression-test-sentinel"


def envelope(output=None, usage=None):
    return {
        "id":"mock-unit-test-response",
        "status":"completed",
        "output":[{"type":"message","content":[{"type":"output_text","text":json.dumps(output or {"value":7})}]}],
        "usage":{"input_tokens":12,"output_tokens":4} if usage is None else usage,
    }


class Response:
    def __init__(self, payload, status=200):
        self.status = status
        self.body = payload if isinstance(payload,bytes) else json.dumps(payload).encode()
        self.read_calls = 0

    def read(self, amount):
        self.read_calls += 1
        return self.body[:amount]


class Connection:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False

    def request(self, method, path, body, headers):
        self.requests.append((method,path,body,headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


@pytest.fixture
def install_transport(monkeypatch):
    monkeypatch.setattr(provider,"_api_key",lambda:TEST_KEY)
    # [수정: 0 이영 · Claude] 2026-09-30 23:55 KST — 실호출은 운영자가 NAIS_ALLOW_LIVE_AI=1로 켠 경우에만 허용되므로 시험 환경에서 켜고 호출 수를 초기화한다.
    monkeypatch.setenv("NAIS_ALLOW_LIVE_AI","1")
    monkeypatch.setattr(provider,"_LIVE_CALLS",{"n":0})
    created = []

    def install(payload, status=200):
        connection = Connection(Response(payload,status))
        def factory(host, timeout):
            assert host == "api.openai.com"
            assert 1 <= timeout <= 60
            created.append(connection)
            return connection
        monkeypatch.setattr(provider.http.client,"HTTPSConnection",factory)
        return connection

    install.created = created
    return install


def test_success_records_only_checked_output_and_actual_usage(install_transport):
    connection = install_transport(envelope())
    result = provider.complete_json("Review the public claim",{"claim":"7 rows"})
    assert result["output"] == {"value":7}
    assert result["usage"] == {"input_tokens":12,"output_tokens":4}
    assert result["raw_sha256"] == hashlib.sha256(connection.response.body).hexdigest()
    assert result["cost_usd"] is None
    assert result["cost_status"] == "NOT_MEASURED"
    assert TEST_KEY not in json.dumps(result)
    assert connection.closed
    request = json.loads(connection.requests[0][2])
    assert request["store"] is False
    assert request["model"] == provider.MODEL
    assert request["max_output_tokens"] == provider.MAX_OUTPUT_TOKENS


@pytest.mark.parametrize("where",["system","payload","schema"])
def test_request_secret_is_blocked_before_any_connection(install_transport,where):
    install_transport(envelope())
    system,payload,schema = "Review the claim",{"claim":"public"},None
    if where == "system":
        system = TEST_KEY
    elif where == "payload":
        payload = {"nested":{"value":TEST_KEY}}
    else:
        schema = {"type":"object","properties":{"value":{"const":TEST_KEY}}}
    with pytest.raises(provider.ProviderError,match="SECRET_IN_REQUEST"):
        provider.complete_json(system,payload,schema=schema)
    assert not install_transport.created


def test_http_error_never_reads_or_discloses_reflective_body(install_transport):
    connection = install_transport({"private":TEST_KEY,"message":"private-response-marker"},status=429)
    with pytest.raises(provider.ProviderError) as failure:
        provider.complete_json("Review",{})
    assert str(failure.value) == "MODEL_HTTP_429"
    assert TEST_KEY not in str(failure.value)
    assert "private-response-marker" not in str(failure.value)
    assert connection.response.read_calls == 0
    assert connection.closed


def test_output_secret_is_rejected(install_transport):
    connection = install_transport(envelope({"nested":{"value":TEST_KEY}}))
    with pytest.raises(provider.ProviderError,match="SECRET_IN_MODEL_OUTPUT"):
        provider.complete_json("Review",{})
    assert connection.closed


def test_duplicate_response_json_keys_are_rejected(install_transport):
    raw = envelope()
    raw["output"][0]["content"][0]["text"] = '{"value":1,"value":2}'
    install_transport(raw)
    with pytest.raises(provider.ProviderError,match="DUPLICATE_MODEL_JSON_KEY"):
        provider.complete_json("Review",{})


@pytest.mark.parametrize("part",[
    {"type":"refusal","refusal":"private-response-marker"},
    {"type":"tool_call","command":"never execute"},
])
def test_refusal_and_non_text_content_are_not_success(install_transport,part):
    raw = envelope()
    raw["output"][0]["content"] = [part]
    install_transport(raw)
    with pytest.raises(provider.ProviderError,match="MODEL_REFUSAL_OR_NON_TEXT"):
        provider.complete_json("Review",{})


@pytest.mark.parametrize("field,bad",[
    ("input_tokens",True),("input_tokens",-1),("input_tokens",None),("input_tokens","12"),
    ("output_tokens",False),("output_tokens",-1),("output_tokens",None),("output_tokens",4.5),
])
def test_usage_requires_nonnegative_integer_counts(install_transport,field,bad):
    usage = {"input_tokens":12,"output_tokens":4}
    usage[field] = bad
    install_transport(envelope(usage=usage))
    with pytest.raises(provider.ProviderError,match="MODEL_USAGE_UNAVAILABLE"):
        provider.complete_json("Review",{})


def test_network_exception_does_not_expose_original_message(install_transport):
    connection = install_transport(envelope())
    def fail_request(*args,**kwargs):
        raise RuntimeError("private-response-marker " + TEST_KEY)
    connection.request = fail_request
    with pytest.raises(provider.ProviderError) as failure:
        provider.complete_json("Review",{})
    assert str(failure.value) == "MODEL_CONNECTION_OR_FORMAT_ERROR"
    assert TEST_KEY not in str(failure.value)
    assert failure.value.__cause__ is None
    assert connection.closed


def test_nonfinite_and_incomplete_output_are_rejected(install_transport):
    raw = envelope()
    raw["output"][0]["content"][0]["text"] = '{"value":NaN}'
    install_transport(raw)
    with pytest.raises(provider.ProviderError,match="NONFINITE_MODEL_JSON"):
        provider.complete_json("Review",{})
    raw = envelope()
    raw["status"] = "incomplete"
    install_transport(raw)
    with pytest.raises(provider.ProviderError,match="MODEL_RESPONSE_INCOMPLETE"):
        provider.complete_json("Review",{})

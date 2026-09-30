"""Synthetic credential-label boundaries; no real provider, approval, or file export."""
from __future__ import annotations

from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

FINALS = Path(__file__).resolve().parents[1]
ROOT = FINALS.parent
for path in (ROOT, FINALS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import finals_cases as cases
import finals_pipeline as pipeline
import finals_provider as provider
from core.input_security import sensitive_content_kinds

# [작성: 0 이영 · Codex] 2026-10-01T05:04:28+09:00 — 기존 형태 검사가 놓친 라벨 인증값을 모의 전송·후보·응답·승인 사유·반출입 경계에서 검증한다. 모든 값은 합성이며 연결/비밀조회는 기본 실패하게 한다.
LABELS = ("api_key", "api-key", "access_token", "token", "password", "secret", "authorization")
SENTINEL = "SYNTHETIC_ONLY_NO_REAL_CREDENTIAL"
TRANSPORT_KEY = "synthetic-transport-unit-key"
SAFE_MARKERS = ("", None, "null", "None", "[REDACTED]", "[비공개 설정]")


def assignment(label, value=SENTINEL):
    return label + chr(61) + value


@pytest.fixture(autouse=True)
def isolate_side_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Real transport or credential lookup is forbidden in this suite")

    monkeypatch.setattr(provider, "live_allowed", lambda: True)
    monkeypatch.setattr(provider, "_api_key", forbidden)
    monkeypatch.setattr(provider, "_call_limit", lambda: -1)
    monkeypatch.setattr(provider, "_LIVE_CALLS", {"n": 0})
    monkeypatch.setattr(provider.http.client, "HTTPSConnection", forbidden)
    monkeypatch.setattr(pipeline, "_log_run", lambda report: None)


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("representation", ("assignment", "nested_json", "nested_list"))
def test_public_gate_rejects_nested_credential_labels_without_mutating_input(label, representation):
    value = {"assignment": assignment(label), "nested_json": {"nested": {label: SENTINEL}},
             "nested_list": {"nested": ["public", {label: SENTINEL}]}}[representation]
    original = deepcopy(value)
    assert not pipeline._public_text(value)
    assert value == original


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("where", ("system", "payload"))
def test_provider_blocks_before_connection_and_budget_consumption(label, where):
    system = assignment(label) if where == "system" else "Review a public numerical claim"
    payload = {"nested": [{label: SENTINEL}]} if where == "payload" else {"n": 344}
    with pytest.raises(provider.ProviderError) as failure:
        provider.complete_json(system, payload, api_key=TRANSPORT_KEY)
    assert str(failure.value) == "PERSONAL_DATA_IN_OUTBOUND_PAYLOAD"
    assert SENTINEL not in str(failure.value)
    assert provider._LIVE_CALLS["n"] == 0


@pytest.mark.parametrize("label", LABELS)
def test_nested_manual_candidate_is_rejected_before_retention_or_calculation(label):
    candidate = deepcopy(cases.load_case("NORMAL-PENG-ROWS")["manual_proposal"])
    candidate["nested"] = [{label: SENTINEL}]
    report = pipeline.run_case_manual("NORMAL-PENG-ROWS", candidate)
    assert report["errors"] == ["SENSITIVE_CONTENT_BLOCKED"]
    assert not report["can_approve"] and not report["calculation"]["executed"]
    assert report["candidate"] is None and report["proposal"] is None
    assert SENTINEL not in json.dumps(report, ensure_ascii=False)


@pytest.mark.parametrize("label", LABELS)
def test_mock_model_response_is_blocked_before_receipt_or_retransmission(label):
    candidate = deepcopy(cases.load_case("NORMAL-PENG-ROWS")["manual_proposal"])
    candidate["claim_text"] += " " + assignment(label)
    calls = []

    def mock_model(system, payload, **kwargs):
        calls.append(deepcopy(payload))
        return {"output": candidate, "usage": {"input_tokens": 1, "output_tokens": 1},
                "provider": "mock", "mock": True, "model": "UNIT_TEST_ONLY"}

    report = pipeline.run_case_ai("NORMAL-PENG-ROWS", provider=mock_model)
    assert len(calls) == 1
    assert report["errors"] == ["SENSITIVE_CONTENT_BLOCKED"]
    assert report["provider_calls"] == [] and report["model_stage_records"] == []
    assert report["candidate"] is None and not report["human_approval"]["approved"]
    assert not report["can_approve"]
    assert SENTINEL not in json.dumps(report, ensure_ascii=False)
    assert SENTINEL not in json.dumps(calls, ensure_ascii=False)


@pytest.mark.parametrize("label", LABELS)
def test_approval_reason_is_rejected_before_any_approval_flow(monkeypatch, label):
    def unexpected_read(*args, **kwargs):
        pytest.fail("Sensitive reason must fail before approval case lookup")

    monkeypatch.setattr(pipeline, "load_case", unexpected_read)
    report = {"can_approve": True}
    with pytest.raises(ValueError) as failure:
        pipeline.approve_report(report, assignment(label), confirmed=True)
    assert str(failure.value) == "APPROVAL_REASON_PERSONAL_DATA"
    assert SENTINEL not in str(failure.value)
    assert report == {"can_approve": True}


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("direction", ("export", "reopen"))
def test_nested_saved_report_is_rejected_before_serialization_or_case_lookup(monkeypatch, label, direction):
    def unexpected_read(*args, **kwargs):
        pytest.fail("Sensitive report must fail before import case lookup")

    monkeypatch.setattr(pipeline, "load_case", unexpected_read)
    report = {"human_approval": {"reason": assignment(label)}}
    original = deepcopy(report)
    with pytest.raises(ValueError) as failure:
        if direction == "export":
            pipeline.export_report(report)
        else:
            pipeline.reopen_report(json.dumps(report))
    expected = "SENSITIVE_REPORT_BLOCKED" if direction == "export" else "INVALID_OR_SENSITIVE_REPORT"
    assert str(failure.value) == expected
    assert SENTINEL not in str(failure.value)
    assert report == original


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("marker", SAFE_MARKERS)
def test_safe_credential_placeholders_and_public_numbers_remain_exportable(label, marker):
    value = {"nested": [{label: marker}], "n": 344, "mean": 49.32}
    assert pipeline._public_text(value)
    exported = json.loads(pipeline.export_report(value))
    assert exported["nested"] == value["nested"]
    assert exported["n"] == 344 and exported["mean"] == 49.32
    assert "export_integrity_sha256" not in value


@pytest.mark.parametrize("value", ("", None, 344, 49.32, {"n": 344}, [344, None, "public"]))
def test_public_blank_null_and_numeric_values_are_retained(value):
    assert pipeline._public_text(value)


@pytest.mark.parametrize("marker", SAFE_MARKERS)
def test_safe_provider_payload_uses_mock_transport_only(monkeypatch, marker):
    requests = []
    response_body = json.dumps({"id": "unit-only-response", "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"n":344}'}]}],
        "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()

    class MockResponse:
        status = 200

        def read(self, amount):
            return response_body[:amount]

    class MockConnection:
        def request(self, method, path, body, headers):
            requests.append(json.loads(body))

        def getresponse(self):
            return MockResponse()

        def close(self):
            pass

    monkeypatch.setattr(provider.http.client, "HTTPSConnection", lambda *a, **k: MockConnection())
    payload = {"nested": [{"password": marker}], "n": 344}
    result = provider.complete_json("Review a public claim", payload, api_key=TRANSPORT_KEY)
    assert result["output"] == {"n": 344}
    assert len(requests) == 1 and requests[0]["store"] is False
    sent = json.loads(requests[0]["input"].split("\n", 1)[1])
    assert sent == payload and provider._LIVE_CALLS["n"] == 1
    assert TRANSPORT_KEY not in json.dumps(result)


def test_public_report_reopens_with_human_approval_inactive():
    report = pipeline.run_case_manual("NORMAL-PENG-ROWS")
    assert report["calculation"]["value"] == 344
    reopened = pipeline.reopen_report(pipeline.export_report(report))
    assert reopened["import_integrity"] == "SHA256_MATCH"
    assert not reopened["human_approval"]["approved"]
    assert not reopened["human_approval"]["active"] and not reopened["can_approve"]


def test_package_and_standalone_provider_share_the_public_detector():
    packaged = importlib.import_module("finals.finals_provider")
    assert provider.sensitive_content_kinds is sensitive_content_kinds
    assert packaged.sensitive_content_kinds is sensitive_content_kinds
    result = subprocess.run([sys.executable, "-I", str(FINALS / "finals_provider.py")],
                            cwd=FINALS, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "Standalone provider import failed"
    assert result.stdout == "" and result.stderr == ""

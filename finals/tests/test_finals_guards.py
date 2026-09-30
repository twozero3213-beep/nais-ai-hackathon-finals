"""검토에서 찾은 finals 결함의 회귀 시험: 실호출 비용·키 안전장치, 첫 실호출 요청 형식, 승인 게이트, 재사용성, 운영 로그.

# [작성: 0 이영 · Claude] 2026-09-30 KST — 네트워크·모델 호출 없이 수정 전에 실패하는 재현으로 작성했다.
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
import sys

import pytest
from streamlit.testing.v1 import AppTest

FINALS = Path(__file__).resolve().parents[1]
ROOT = FINALS.parent
for path in (ROOT, FINALS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import finals_cases
import finals_pipeline as pipeline
import finals_provider as provider

KEY = "review-guard-test-sentinel"


class Response:
    def __init__(self, payload, status=200):
        self.status, self.body = status, json.dumps(payload).encode()

    def read(self, amount):
        return self.body[:amount]


class Connection:
    def __init__(self, response):
        self.response, self.requests = response, []

    def request(self, method, path, body, headers):
        self.requests.append(json.loads(body))

    def getresponse(self):
        return self.response

    def close(self):
        pass


def message(output):
    return {"id": "resp_x", "status": "completed", "usage": {"input_tokens": 1, "output_tokens": 1},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(output)}]}]}


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(provider, "_api_key", lambda: KEY)
    monkeypatch.setenv("NAIS_ALLOW_LIVE_AI", "1")
    monkeypatch.setattr(provider, "_LIVE_CALLS", {"n": 0})
    made = []

    def install(payload, status=200):
        connection = Connection(Response(payload, status))
        made.append(connection)
        monkeypatch.setattr(provider.http.client, "HTTPSConnection", lambda host, timeout: connection)
        return connection

    install.made = made
    return install


# ---------- 공급자: 키 처리 ----------
def test_key_is_read_only_from_environment_or_labeled_line(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NAIS_SECRETS_FILE", raising=False)
    home = tmp_path / "home"
    desktop_file = home / "OneDrive" / "Desktop" / "NAIS 해커톤 본선" / "각종 API 원문.txt"  # hygiene: allow-local-path
    desktop_file.parent.mkdir(parents=True)
    desktop_file.write_text("아무 서비스의 키: sk-" + "a" * 30 + "\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    with pytest.raises(provider.ProviderError) as unlabeled_default:
        provider._api_key()
    assert str(unlabeled_default.value) == "MODEL_KEY_UNAVAILABLE"

    other = tmp_path / "secrets.txt"
    other.write_text("DEEPSEEK_API_KEY=sk-" + "d" * 30 + "\n", encoding="utf-8")
    monkeypatch.setenv("NAIS_SECRETS_FILE", str(other))
    with pytest.raises(provider.ProviderError):
        provider._api_key()          # 다른 서비스의 sk- 키를 OpenAI 키로 오인해 보내면 안 된다

    labeled = tmp_path / "labeled.txt"
    labeled.write_text("DEEPSEEK_API_KEY=sk-" + "d" * 30 + "\nOPENAI_API_KEY=sk-proj-" + "o" * 30 + "\n", encoding="utf-8")
    monkeypatch.setenv("NAIS_SECRETS_FILE", str(labeled))
    assert provider._api_key() == "sk-proj-" + "o" * 30


# ---------- 공급자: 실호출 비용 안전장치 ----------
def test_live_call_is_refused_unless_explicitly_allowed(monkeypatch):
    monkeypatch.setattr(provider, "_api_key", lambda: KEY)
    monkeypatch.delenv("NAIS_ALLOW_LIVE_AI", raising=False)

    def forbidden(host, timeout):
        raise AssertionError("허용 전에는 연결하지 않는다")

    monkeypatch.setattr(provider.http.client, "HTTPSConnection", forbidden)
    with pytest.raises(provider.ProviderError) as refused:
        provider.complete_json("system", {"a": 1})
    assert str(refused.value) == "LIVE_AI_NOT_ALLOWED"


def test_availability_reports_whether_live_is_allowed(monkeypatch):
    monkeypatch.setattr(provider, "_api_key", lambda: KEY)
    monkeypatch.delenv("NAIS_ALLOW_LIVE_AI", raising=False)
    assert provider.availability()["live_allowed"] is False
    monkeypatch.setenv("NAIS_ALLOW_LIVE_AI", "1")
    assert provider.availability()["live_allowed"] is True


def test_process_wide_call_budget_stops_before_connecting(transport, monkeypatch):
    monkeypatch.setenv("NAIS_LIVE_CALL_LIMIT", "2")
    connection = transport(message({"ok": True}))
    provider.complete_json("s", {"a": 1})
    provider.complete_json("s", {"a": 1})
    with pytest.raises(provider.ProviderError) as over:
        provider.complete_json("s", {"a": 1})
    assert str(over.value) == "LIVE_AI_BUDGET_EXHAUSTED"
    assert len(connection.requests) == 2


# ---------- 공급자: 첫 실호출이 요청 형식 때문에 실패하지 않게 ----------
UNSUPPORTED = {"minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems", "pattern", "format", "multipleOf", "uniqueItems"}


def _keywords(node, found=None):
    found = set() if found is None else found
    if isinstance(node, dict):
        found.update(k for k in node if k in UNSUPPORTED and not isinstance(node[k], dict))
        for value in node.values():
            _keywords(value, found)
    elif isinstance(node, list):
        for value in node:
            _keywords(value, found)
    return found


def test_request_schema_drops_length_and_range_keywords_but_keeps_structure(transport):
    connection = transport(message({"ok": True}))
    provider.complete_json("s", {"a": 1}, schema=pipeline.PROPOSAL_SCHEMA)
    sent = connection.requests[0]["text"]["format"]
    assert sent["strict"] is True and sent["type"] == "json_schema"
    assert not _keywords(sent["schema"])
    assert sent["schema"]["required"] == pipeline.PROPOSAL_SCHEMA["required"]
    assert sent["schema"]["additionalProperties"] is False
    assert sent["schema"]["properties"]["method"]["enum"] == ["row_count", "mean"]
    assert _keywords(pipeline.PROPOSAL_SCHEMA)          # 로컬 검사용 원본 스키마는 제약을 그대로 유지한다


def test_request_schema_keeps_property_names_that_look_like_keywords():
    schema = {"type": "object", "additionalProperties": False, "required": ["format", "pattern"],
              "properties": {"format": {"type": "string", "maxLength": 5}, "pattern": {"type": "integer", "minimum": 1}}}
    sent = provider.request_schema(schema)
    assert set(sent["properties"]) == {"format", "pattern"}
    assert sent["properties"]["format"] == {"type": "string"}


def test_reasoning_items_are_skipped_not_treated_as_failure(transport):
    payload = message({"ok": True})
    payload["output"].insert(0, {"type": "reasoning", "summary": []})
    transport(payload)
    assert provider.complete_json("s", {"a": 1})["output"] == {"ok": True}


# ---------- 파이프라인: 승인 게이트 ----------
def test_denominator_mismatch_blocks_approval(monkeypatch):
    report = pipeline.run_case("NORMAL-BAT-MEAN")
    assert report["can_approve"] is True
    real = pipeline._calculate

    def wrong_denominator(case, proposal):
        result = real(case, proposal)
        return dict(result, denominator_matches=False)

    monkeypatch.setattr(pipeline, "_calculate", wrong_denominator)
    assert pipeline.run_case("NORMAL-BAT-MEAN")["can_approve"] is False
    with pytest.raises(ValueError, match="APPROVAL_DENOMINATOR_MISMATCH"):
        pipeline.approve_report(report, reason="원문과 조건을 직접 확인함", confirmed=True)


def test_receipt_check_follows_provider_constants(monkeypatch):
    monkeypatch.setattr(provider, "MODEL", "gpt-test-model")
    monkeypatch.setattr(pipeline, "MODEL", "gpt-test-model", raising=False)

    def fake(system, payload, schema=None, timeout=45):
        return {"output": {"claim_text": "x"}, "usage": {"input_tokens": 1, "output_tokens": 1}, "provider": provider.PROVIDER,
                "model": provider.MODEL, "request_id": "resp_1", "raw_sha256": "0" * 64}

    report = pipeline._new_report(finals_cases.load_case("NORMAL-PENG-ROWS"), "live")
    out = pipeline._model_call(fake, "s", {"a": 1}, {}, report, 0.0 + pipeline.perf_counter())
    assert out == {"claim_text": "x"}


# ---------- 사례: 재사용성 ----------
def test_expected_denominator_comes_from_registered_data_not_a_magic_number():
    assert finals_cases.load_case("NORMAL-PENG-ROWS")["expected_proposal"]["denominator"] == {"rule": "all_rows", "expected_n": 344}
    assert finals_cases.load_case("NORMAL-BAT-MEAN")["expected_proposal"]["denominator"] == {"rule": "filtered_rows", "expected_n": 53}
    assert finals_cases.load_case("MISSING-PUBLISHER")["expected_proposal"]["denominator"]["expected_n"] == 1599


def test_new_registered_claim_with_a_filter_gets_its_own_denominator(monkeypatch, tmp_path):
    csv = tmp_path / "d.csv"
    csv.write_bytes(b"g,v\n" + b"a,1\n" * 7 + b"b,2\n" * 5)
    source = tmp_path / "s.txt"
    source.write_bytes(b"group a has seven rows")
    sha = finals_cases._sha
    item = {"claim_id": "CUSTOM-1", "claim_text": "a 그룹은 7행", "source_quote": "seven rows", "source_location": "p1", "paper_url": "https://example.org",
            "method": "count_rows", "column": "g", "filters": {"g": "a"}, "reported_value": 7, "tolerance": 0, "missing_policy": "error",
            "delimiter": ",", "data_file": "d.csv", "source_file": "s.txt", "source_kind": "article_extract", "evidence_status": "READY",
            "data_sha256": sha(csv.read_bytes()), "source_sha256": sha(source.read_bytes())}
    monkeypatch.setattr(finals_cases, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(finals_cases, "_registered_claims", lambda: {"CUSTOM-1": item})
    case = finals_cases.load_case("CUSTOM-1")
    assert case["expected_proposal"]["denominator"] == {"rule": "filtered_rows", "expected_n": 7}


# ---------- 운영 로그 ----------
def test_each_run_writes_one_structured_log_line_without_document_text(caplog):
    with caplog.at_level(logging.INFO, logger="finals.pipeline"):
        report = pipeline.run_case("NORMAL-PENG-ROWS")
    lines = [r.getMessage() for r in caplog.records if r.name == "finals.pipeline"]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["report_id"] == report["report_id"] and entry["case_id"] == "NORMAL-PENG-ROWS" and entry["state"] == report["state"]
    assert entry["mode"] == "manual" and "elapsed_ms" in entry and entry["errors"] == []
    assert "source_quote" not in lines[0] and report["source"]["source_quote"][:20] not in lines[0]


# ---------- UI: 공개 화면에서의 비용 남용 방지 ----------
@pytest.fixture
def live_app(monkeypatch):
    monkeypatch.chdir(ROOT)

    def create(**availability):
        base = {"available": True, "configured": True, "model": "gpt-4.1-mini"}
        monkeypatch.setattr(provider, "availability", lambda: {**base, **availability})
        app = AppTest.from_file(str(FINALS / "app.py"), default_timeout=60).run()
        app.radio(key="fin_mode").set_value("실시간 AI").run()
        assert not app.exception
        return app

    return create


def test_live_button_disabled_until_operator_allows_live_ai(live_app):
    assert live_app(live_allowed=False).button(key="fin_live_generate").disabled
    assert not live_app(live_allowed=True).button(key="fin_live_generate").disabled


def test_live_button_stops_after_session_cap(monkeypatch, live_app):
    monkeypatch.setenv("NAIS_LIVE_MAX_RUNS", "1")
    app = live_app(live_allowed=True)
    app.session_state["fin_live_runs"] = 1
    app.run()
    assert app.button(key="fin_live_generate").disabled


def test_import_failure_is_logged_not_silently_swallowed(monkeypatch, caplog):
    monkeypatch.chdir(ROOT)
    import builtins
    real_import = builtins.__import__

    def broken(name, *args, **kwargs):
        if name == "finals_pipeline":
            raise ImportError("simulated missing dependency jsonschema")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken)
    with caplog.at_level(logging.ERROR):
        app = AppTest.from_file(str(FINALS / "app.py"), default_timeout=60).run()
    assert any("jsonschema" in r.getMessage() for r in caplog.records)
    assert app.error

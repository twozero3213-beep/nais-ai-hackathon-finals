"""[0 이영] 팀 정책을 두 AI 경로에 연결하며 실제 모델 호출 없이 실패 경계를 검증한다."""
# [작성: 0 이영 · Codex] 2026-10-01 01:05 KST — 공통 정책·지문·지식 불량 차단과 수동 검산의 분리를 검증한다.
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

FINALS = Path(__file__).resolve().parents[1]
for path in (FINALS.parent, FINALS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import finals_cases as cases
import finals_pipeline as pipeline
from core import team_knowledge


@pytest.fixture(autouse=True)
def clear_knowledge_cache():
    # [수정: 0 이영 · Codex] 2026-10-01 01:38 KST — 파일 지문을 매 호출 갱신하는 원격 로더와 기존 lru_cache 로더를 함께 검증한다.
    clear = getattr(team_knowledge.load_knowledge, "cache_clear", None)
    if callable(clear):
        clear()
    yield
    clear = getattr(team_knowledge.load_knowledge, "cache_clear", None)
    if callable(clear):
        clear()


def mock_provider(outputs, calls):
    def complete(system, payload, schema=None, timeout=45):
        calls.append({"system": system, "payload": deepcopy(payload), "schema": schema, "timeout": timeout})
        return {"output": deepcopy(outputs[len(calls) - 1]), "provider": "mock",
                "model": "MOCK_TEST_ONLY", "mock": True, "usage": {"input_tokens": 1, "output_tokens": 1},
                "elapsed_ms": 0, "request_id": "mock-policy-test", "raw_sha256": "0" * 64}
    return complete


def test_both_ai_modes_receive_same_team_policy_and_auditable_prompt_hashes():
    knowledge_bytes = team_knowledge.KNOWLEDGE_PATH.read_bytes()
    expected_claims = json.loads(knowledge_bytes)["differentiation"]["do_not_claim"]
    model_decision = {"decision": "MATCH", "calculated_value": 344,
                      "evidence": "등록 원문과 전체 CSV", "reason": "모의 출력"}
    candidate = cases.load_case("NORMAL-PENG-ROWS")["manual_proposal"]
    records = []
    for mode, outputs in [("ai_baseline", [model_decision, model_decision]),
                          ("ai_agent", [candidate, {"evidence_ready": True, "issues": []}])]:
        calls = []
        report = pipeline.run_case("NORMAL-PENG-ROWS", mode=mode, provider=mock_provider(outputs, calls))
        assert report["status"] in {"GENERAL_AI_MATCH", "SUPPORTED_PREVIEW"}
        assert len(calls) == len(report["provider_calls"]) == 2
        assert report["team_knowledge_sha256"] == hashlib.sha256(knowledge_bytes).hexdigest()
        assert report["model_prompt_sha256"] == [hashlib.sha256(c["system"].encode()).hexdigest() for c in calls]
        for call in calls:
            policy = json.loads(call["system"].split("\nFixed verification policy: ", 1)[1])
            assert policy["forbidden_claims"] == expected_claims
            assert "논문 전체 재현" in policy["support_scope"]
            assert "사람 승인 완료가 아니다" in policy["human_review"]
            assert "미입증" in policy["evidence_scope"]
            assert 0 < call["timeout"] <= 45
        assert not report["actual_model_output"]
        assert report["human_approval"] == {"status": "PENDING", "approved": False}
        records.append((report, calls))
    assert records[0][0]["verification_policy_sha256"] == records[1][0]["verification_policy_sha256"]
    assert records[0][1][0]["payload"] == records[1][1][0]["payload"]
    assert not records[0][0]["can_approve"]


@pytest.mark.parametrize("mode", ["ai_baseline", "ai_agent"])
@pytest.mark.parametrize("contents", [None, '{"differentiation":{},"differentiation":{}}'])
def test_missing_or_duplicate_key_knowledge_blocks_before_provider(tmp_path, monkeypatch, mode, contents):
    path = tmp_path / "knowledge.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(team_knowledge, "KNOWLEDGE_PATH", path)
    calls = []
    report = pipeline.run_case("NORMAL-PENG-ROWS", mode=mode, provider=mock_provider([], calls))
    assert report["status"] == "MODEL_BLOCKED"
    assert report["errors"] == ["TEAM_KNOWLEDGE_UNAVAILABLE"]
    assert calls == report["provider_calls"] == []
    assert not report["llm_executed"] and not report["actual_model_output"]
    assert not report["calculation"]["executed"] and not report["can_approve"]


@pytest.mark.parametrize("mode", ["ai_baseline", "ai_agent"])
@pytest.mark.parametrize("claims", ["malformed-string", [], [None], ["x" * 4001]])
def test_invalid_policy_shape_or_size_blocks_before_provider(tmp_path, monkeypatch, mode, claims):
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps({"differentiation": {"do_not_claim": claims}}), encoding="utf-8")
    monkeypatch.setattr(team_knowledge, "KNOWLEDGE_PATH", path)
    calls = []
    report = pipeline.run_case("NORMAL-PENG-ROWS", mode=mode, provider=mock_provider([], calls))
    assert report["status"] == "MODEL_BLOCKED"
    assert report["errors"] == ["TEAM_KNOWLEDGE_UNAVAILABLE"]
    assert calls == report["provider_calls"] == []
    assert not report["actual_model_output"] and not report["can_approve"]


def test_manual_calculation_needs_no_ai_policy_and_still_requires_human_review(tmp_path, monkeypatch):
    monkeypatch.setattr(team_knowledge, "KNOWLEDGE_PATH", tmp_path / "missing.json")
    report = pipeline.run_case_manual("NORMAL-PENG-ROWS")
    assert report["status"] == "SUPPORTED_PREVIEW"
    assert report["formal_verification"]["status"] == "REVIEW"
    assert report["human_approval"] == {"status": "PENDING", "approved": False}
    assert report["provider_calls"] == []
    assert not report["llm_executed"] and not report["actual_model_output"]
    assert "verification_policy_sha256" not in report

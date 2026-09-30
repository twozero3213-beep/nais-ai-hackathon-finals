"""[0 이영] 수정 이유: 승인 경계·변경 지문·모델 단독 비교와 실제 계산을 구분해 검증한다."""
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


def test_eight_functional_cases_have_four_balanced_categories():
    listed = cases.list_cases()
    assert len(listed) == len({item["id"] for item in listed}) == 8
    assert {category: sum(item["category"] == category for item in listed) for category in {item["category"] for item in listed}} == {
        "normal": 2, "mismatch": 2, "evidence_missing": 2, "data_changed": 2}
    assert all(pipeline.run_case(item["id"])["evaluation_scope"].endswith("NOT_SEALED_COMPARISON_C01_C08") for item in listed)


@pytest.mark.parametrize("case_id,expected_value,expected_n", [("NORMAL-PENG-ROWS", 344, 344), ("NORMAL-BAT-MEAN", 49.320754716981135, 53)])
def test_actual_registered_arithmetic_never_automatically_approves(case_id, expected_value, expected_n):
    report = pipeline.run_case_manual(case_id)
    assert report["status"] == "SUPPORTED_PREVIEW"
    assert report["calculation"]["value"] == pytest.approx(expected_value)
    assert report["calculation"]["selected_rows"] == expected_n
    assert report["calculation"]["denominator_matches"]
    assert report["formal_verification"]["status"] == "REVIEW"
    assert report["human_approval"]["status"] == "PENDING"
    assert not report["llm_executed"] and report["usage"]["input_tokens"] == 0
    with pytest.raises(ValueError, match="EXPLICIT_HUMAN"):
        pipeline.approve_report(report, "원문 의미 연결 확인")
    assert report["human_approval"]["approved"] is False


@pytest.mark.parametrize("case_id,value", [("MISMATCH-PENG-DROP1", 343), ("MISMATCH-PENG-DROP2", 342)])
def test_controlled_csv_mutation_detects_mismatch_without_modifying_original(case_id, value):
    case = cases.load_case(case_id)
    original = (cases.REPO_ROOT / case["source"]["data_file"]).read_bytes()
    report = pipeline.run_case_manual(case_id)
    assert report["status"] == "CONFLICT_PREVIEW"
    assert report["calculation"]["value"] == value
    assert not report["calculation"]["denominator_matches"]
    assert not report["can_approve"]
    assert hashlib.sha256(original).hexdigest() == case["registered_data_sha256"]
    assert (cases.REPO_ROOT / case["source"]["data_file"]).read_bytes() == original
    with pytest.raises(ValueError, match="NOT_APPROVABLE"):
        pipeline.approve_report(report, "원문을 직접 확인했습니다", confirmed=True)


@pytest.mark.parametrize("case_id", ["MISSING-PUBLISHER", "MISSING-MISSING-POLICY"])
def test_missing_evidence_fails_closed(case_id):
    report = pipeline.run_case_manual(case_id)
    assert report["status"] == "MISSING"
    assert not report["calculation"]["executed"] and not report["can_approve"]
    assert report["validation"]["errors"]


@pytest.mark.parametrize("case_id", ["CHANGED-PENG-CSV", "CHANGED-BAT-CONTRACT"])
def test_changed_registered_result_is_not_a_fabricated_human_approval(case_id):
    report = pipeline.run_case_manual(case_id)
    assert report["status"] == "BLOCKED_CHANGED_INPUT"
    assert report["changed_input"]["prior_human_approval"] is False
    assert report["human_approval"]["approved"] is False
    assert not report["can_approve"]


def test_explicit_approval_then_actual_changed_csv_invalidates_core_claim():
    report = pipeline.run_case_manual("NORMAL-PENG-ROWS")
    approved = pipeline.approve_report(report, "원문 344개체와 전체 CSV 조건을 직접 대조했습니다", confirmed=True)
    assert approved["status"] == "APPROVED"
    assert approved["human_approval"]["approved"]
    changed = pipeline.recheck_changed_input(approved)
    assert changed["status"] == "BLOCKED_CHANGED_INPUT"
    assert changed["formal_verification"]["status"] == "CONFLICT"
    assert changed["formal_verification"]["calculated"] == 343
    assert changed["human_approval"]["status"] == "INVALIDATED"
    assert approved["input_sha256"] != changed["input_sha256"]
    assert not changed["changed_input"]["original_file_modified"]


def test_duplicate_keys_nonfinite_and_executable_fields_are_blocked():
    candidate = cases.load_case("NORMAL-PENG-ROWS")["manual_proposal"]
    assert pipeline.run_case_manual("NORMAL-PENG-ROWS", '{"method":"mean","method":"row_count"}')["status"] == "BLOCKED"
    assert pipeline.run_case_manual("NORMAL-PENG-ROWS", '{"reported_value":NaN}')["status"] == "BLOCKED"
    candidate["code"] = "__import__('os').system('echo unsafe')"
    result = pipeline.run_case_manual("NORMAL-PENG-ROWS", candidate)
    assert result["status"] == "MISSING" and not result["calculation"]["executed"]


def test_candidate_cannot_change_reported_number_or_tolerance_to_manufacture_match():
    candidate = cases.load_case("MISMATCH-PENG-DROP1")["manual_proposal"]
    candidate["reported_value"] = 343
    candidate["tolerance"] = 999
    report = pipeline.run_case_manual("MISMATCH-PENG-DROP1", candidate)
    assert report["status"] == "MISSING"
    assert "REGISTERED_FIELD_MISMATCH_REPORTED_VALUE" in report["validation"]["errors"]
    assert not report["can_approve"]


def test_report_reopen_never_imports_active_human_approval_and_detects_tamper():
    approved = pipeline.approve_report(pipeline.run_case_manual("NORMAL-PENG-ROWS"), "출처와 CSV를 직접 확인했습니다", confirmed=True)
    encoded = pipeline.export_report(approved)
    reopened = pipeline.reopen_report(encoded)
    assert reopened["imported_approval_record"]["approved"]
    assert reopened["human_approval"]["approved"] is False
    assert reopened["can_approve"] is False
    tampered = json.loads(encoded)
    tampered["calculation"]["value"] = 999
    with pytest.raises(ValueError, match="INTEGRITY"):
        pipeline.reopen_report(json.dumps(tampered))
    unsigned = pipeline.reopen_report(json.dumps(approved))
    assert unsigned["import_integrity"] == "UNSIGNED_RECORD_ONLY"
    assert not unsigned["human_approval"]["active"]


def mock_provider(outputs, calls):
    # 모의 모델 출력은 실제 모델 실행/성능/토큰으로 간주하지 않는다.
    def complete(system, payload, schema=None, timeout=45):
        calls.append({"payload": deepcopy(payload), "schema": schema, "timeout": timeout})
        output = deepcopy(outputs[len(calls) - 1])
        return {"output": output, "provider": "mock", "model": "MOCK_TEST_ONLY", "mock": True,
                "usage": {"input_tokens": 1, "output_tokens": 1}, "elapsed_ms": 0,
                "request_id": "mock-test", "raw_sha256": "0" * 64}
    return complete


def test_general_ai_baseline_never_calls_deterministic_engine(monkeypatch):
    def prohibited(*_args, **_kwargs):
        pytest.fail("일반 AI 단독 경로가 결정론 검산 엔진을 호출했습니다")
    monkeypatch.setattr(pipeline, "_validation", prohibited)
    monkeypatch.setattr(pipeline, "_calculate", prohibited)
    monkeypatch.setattr(pipeline, "verify", prohibited)
    monkeypatch.setattr(pipeline, "auto_verify", prohibited)
    outputs = [{"decision": "MATCH", "calculated_value": 344, "evidence": "CSV 모든 행", "reason": "모의 출력"}] * 2
    calls = []
    report = pipeline.run_case("NORMAL-PENG-ROWS", mode="ai_baseline", provider=mock_provider(outputs, calls))
    assert report["status"] == "GENERAL_AI_MATCH"
    assert len(calls) == 2 and calls[1]["payload"]["input"] == calls[0]["payload"]
    assert not report["calculation"]["deterministic_engine_executed"]
    assert not report["actual_model_output"] and not report["human_approval"]["approved"]
    assert not report["can_approve"]


def test_two_ai_modes_receive_same_full_csv_and_same_budgets():
    case_id = "NORMAL-PENG-ROWS"
    baseline_calls, agent_calls = [], []
    model_result = {"decision": "MATCH", "calculated_value": 344, "evidence": "등록 원문", "reason": "모의 출력"}
    pipeline.run_case(case_id, mode="ai_baseline", provider=mock_provider([model_result, model_result], baseline_calls))
    candidate = cases.load_case(case_id)["manual_proposal"]
    report = pipeline.run_case(case_id, mode="ai_agent", provider=mock_provider([candidate, {"evidence_ready": True, "issues": []}], agent_calls))
    assert report["status"] == "SUPPORTED_PREVIEW" and not report["actual_model_output"]
    assert baseline_calls[0]["payload"] == agent_calls[0]["payload"]
    assert agent_calls[1]["payload"]["input"] == agent_calls[0]["payload"]
    assert len(agent_calls) == len(baseline_calls) == 2
    assert all(0 < call["timeout"] <= 45 for call in agent_calls + baseline_calls)
    assert len(agent_calls[0]["payload"]["data_csv"].splitlines()) == 345
    assert "category" not in agent_calls[0]["payload"]


def test_provider_failure_is_safe_and_not_retried_or_counted_as_real_output():
    calls = []
    def blocked(*_args, **_kwargs):
        calls.append(1)
        raise ValueError("MODEL_HTTP_429")
    report = pipeline.run_case_ai("NORMAL-PENG-ROWS", provider=blocked)
    assert report["status"] == "MODEL_BLOCKED"
    assert report["errors"] == ["MODEL_HTTP_429"]
    assert len(calls) == 1 and not report["actual_model_output"]
    assert not report["calculation"]["executed"]


def test_mock_critique_cannot_approve_or_ignore_evidence_failure():
    candidate = cases.load_case("MISSING-PUBLISHER")["manual_proposal"]
    calls = []
    report = pipeline.run_case_ai("MISSING-PUBLISHER", provider=mock_provider([candidate, {"evidence_ready": True, "issues": []}], calls))
    assert report["status"] == "MISSING" and not report["can_approve"]
    assert not report["human_approval"]["approved"]


def test_actual_saved_replay_required_and_functional_snapshot_is_stable():
    assert pipeline.run_case("NORMAL-PENG-ROWS", mode="replay", replay_path="missing.json")["status"] == "BLOCKED"
    snapshot = pipeline.freeze_case("NORMAL-PENG-ROWS")
    assert snapshot["input_fingerprint"] == pipeline.freeze_case("NORMAL-PENG-ROWS")["input_fingerprint"]
    assert snapshot["evaluation_scope"] == "FUNCTIONAL_REGRESSION_CASES"

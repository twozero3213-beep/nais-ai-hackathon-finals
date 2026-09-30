"""[0 이영] version 0: actual approval output integrity, synthetic local tests.

# [작성: 0 이영] 2026-10-01T06:01:19.120409+09:00
# 이유: 실제 승인 진입점의 새 계산/검증이 반환 보고서에도 반영되는지 확인한다.
# 범위: 정상·충돌·자료변경·저장/재열기; 실제 사람 결정·모델/외부망 호출은 없다.
# 격리: 전용 tmp_path CSV/원문/registry와 cases 데이터 경로 globals만 변경한다.
# 업무 함수/산술 엔진/모델을 교체하거나 승인 상태·actor를 강제로 만들지 않는다.
"""
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

CASE_ID = "SYNTHETIC-APPROVAL-RESULT-INTEGRITY"
REASON = "synthetic local test reviewer: checked fixture source and arithmetic; not an actual human decision"


@pytest.fixture
def synthetic_case(tmp_path, monkeypatch):
    """Independent toy fixture. Existing registered/public input files are never written."""
    data = b"group,age\nA,10\nA,30\nB,40\n"
    quote = "Group A contains two observed ages, with mean age 20 years."
    source = ("SYNTHETIC TEST ONLY. " + quote + " Not a published paper.\n").encode()
    (tmp_path / "data.csv").write_bytes(data)
    (tmp_path / "source.txt").write_bytes(source)
    item = {
        "claim_id": CASE_ID,
        "claim_text": "Synthetic group A mean age is 20 years",
        "reported_value": 20,
        "source_quote": quote,
        "source_location": "synthetic paragraph 1",
        "source_file": "source.txt",
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "data_file": "data.csv",
        "data_sha256": hashlib.sha256(data).hexdigest(),
        "delimiter": ",", "method": "mean", "column": "age",
        "filters": {"group": "A"}, "missing_policy": "error", "tolerance": 0.01,
        "source_kind": "article_extract", "evidence_status": "SYNTHETIC_LOCAL_TEST",
        "paper_url": "https://example.invalid/synthetic-approval-result",
        "license": "Synthetic test fixture",
        "scope_note": "Local automated fixture, not actual paper evidence or human approval.",
    }
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"cases": [item]}), encoding="utf-8")
    # Only data-root globals are isolated; load_case and all verification functions remain real.
    monkeypatch.setattr(cases, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cases, "REGISTRY", registry)
    return {"root": tmp_path, "registry": registry, "item": item, "data": data, "source": source}


def preview():
    report = pipeline.run_case_manual(CASE_ID)
    assert report["state"] == "SUPPORTED_PREVIEW"
    assert report["can_approve"] is True
    assert report["calculation"]["calculated_value"] == 20
    assert report["calculation"]["selected_rows"] == 2
    assert report["provider_calls"] == []
    assert report["llm_executed"] is False
    assert report["actual_model_output"] is False
    assert report["human_approval"]["approved"] is False
    return report


def approve(report):
    # Actual entry point; this direct confirmation is a synthetic local test decision only.
    return pipeline.approve_report(report, REASON, confirmed=True)


CALCULATION_TAMPERS = (
    pytest.param({"value": 999, "calculated_value": 999, "delta": 979}, id="value-delta"),
    pytest.param({"within_tolerance": False}, id="within-tolerance"),
    pytest.param({"executed": False, "reported_value": 999, "selected_rows": 999,
                  "denominator_matches": False, "engine": "untrusted synthetic engine label",
                  "meta": {"untrusted_marker": True}}, id="whole-derived-envelope"),
)


@pytest.mark.parametrize("tamper", CALCULATION_TAMPERS)
def test_approval_returns_entire_fresh_calculation(synthetic_case, tamper):
    original = preview()
    expected = deepcopy(original["calculation"])
    report = deepcopy(original)
    report["calculation"].update(tamper)
    input_before = deepcopy(report)
    approved = approve(report)
    assert approved["state"] == "APPROVED"
    assert approved["claim_snapshot"]["current_value"] == 20
    assert approved["calculation"] == expected
    assert report == input_before, "approval must not mutate the caller's preview"


VALIDATION_TAMPERS = (
    pytest.param({"valid": False, "source_valid": False, "schema_valid": False,
                  "six_conditions": [], "errors": ["untrusted synthetic error"],
                  "human_semantic_confirmed": False, "typed_contract": {},
                  "formal_contract": {"executable": False, "missing": ["untrusted"]}}, id="entire-validation"),
    pytest.param({}, id="empty-validation"),
    pytest.param(None, id="null-validation"),
)


@pytest.mark.parametrize("tamper", VALIDATION_TAMPERS)
def test_approval_returns_entire_fresh_validation(synthetic_case, tamper):
    original = preview()
    expected = deepcopy(original["validation"])
    expected["human_semantic_confirmed"] = True
    report = deepcopy(original)
    report["validation"] = deepcopy(tamper)
    approved = approve(report)
    assert approved["state"] == "APPROVED"
    assert approved["validation"] == expected
    assert approved["validation"]["errors"] == []


def test_normal_approval_preserves_correct_outputs_and_explicit_test_reason(synthetic_case):
    report = preview()
    before = deepcopy(report)
    approved = approve(report)
    expected_validation = deepcopy(report["validation"])
    expected_validation["human_semantic_confirmed"] = True
    assert approved["calculation"] == report["calculation"]
    assert approved["validation"] == expected_validation
    assert approved["formal_verification"]["status"] == "VALIDATED"
    assert approved["human_approval"]["reason"] == REASON
    # HUMAN_USER is the entry point's fixed actor marker, not authenticated reviewer identity.
    assert approved["human_approval"]["actor"] == "HUMAN_USER"
    assert approved["human_approval"]["input_bindings"] == report["input_bindings"]
    assert approved["human_approval"]["verification_signature"] == approved["claim_snapshot"]["validated_signature"]
    assert approved["can_approve"] is False
    assert report == before
    with pytest.raises(ValueError, match="REPORT_NOT_APPROVABLE"):
        approve(approved)


@pytest.mark.parametrize("force_flag,error", [(False, "REPORT_NOT_APPROVABLE"), (True, "APPROVAL_ARITHMETIC_CONFLICT")])
def test_real_conflict_remains_blocked_even_if_preview_flag_is_changed(synthetic_case, force_flag, error):
    item = deepcopy(synthetic_case["item"])
    item["reported_value"] = 999
    synthetic_case["registry"].write_text(json.dumps({"cases": [item]}), encoding="utf-8")
    report = pipeline.run_case_manual(CASE_ID)
    assert report["state"] == "CONFLICT_PREVIEW"
    assert report["calculation"]["calculated_value"] == 20
    assert report["can_approve"] is False
    # Changing this display flag measures the actual guard; no approved/actor field is preset.
    report["can_approve"] = force_flag
    with pytest.raises(ValueError, match=error):
        approve(report)
    assert report["human_approval"]["approved"] is False


@pytest.mark.parametrize("critique", [{"evidence_ready": False, "issues": []}, {"evidence_ready": True, "issues": ["synthetic unresolved source issue"]}])
def test_unresolved_critique_still_blocks_the_entry_point(synthetic_case, critique):
    report = preview()
    report["critique"] = critique
    with pytest.raises(ValueError, match="APPROVAL_CRITIQUE_UNRESOLVED"):
        approve(report)


@pytest.mark.parametrize("change", ["data", "source", "registered-location", "registered-filter"])
def test_current_fixture_changes_still_block_approval(synthetic_case, change):
    report = preview()
    root = synthetic_case["root"]
    if change == "data":
        (root / "data.csv").write_bytes(synthetic_case["data"] + b"B,50\n")
    elif change == "source":
        (root / "source.txt").write_bytes(synthetic_case["source"] + b"Additional synthetic note.\n")
    else:
        item = deepcopy(synthetic_case["item"])
        if change == "registered-location":
            item["source_location"] = "synthetic paragraph 2"
        else:
            item["filters"] = {"group": "B"}
        synthetic_case["registry"].write_text(json.dumps({"cases": [item]}), encoding="utf-8")
    error = "APPROVAL_INPUT_CHANGED" if change in {"data", "source"} else "APPROVAL_EVIDENCE_INVALID"
    with pytest.raises(ValueError, match=error):
        approve(report)


@pytest.mark.parametrize("reason,confirmed", [(REASON, False), ("", True), ("no", True)])
def test_explicit_test_confirmation_and_reason_are_required(synthetic_case, reason, confirmed):
    with pytest.raises(ValueError, match="EXPLICIT_HUMAN_CONFIRMATION_AND_REASON_REQUIRED"):
        pipeline.approve_report(preview(), reason, confirmed=confirmed)


@pytest.mark.parametrize("tamper_derived", [False, True])
def test_reopened_report_recomputes_derived_outputs_but_never_reactivates_approval(synthetic_case, tamper_derived):
    report = preview()
    approved = approve(report)
    if tamper_derived:
        approved["calculation"] = {"executed": False, "calculated_value": 999}
        approved["validation"] = {"valid": False, "errors": ["untrusted synthetic error"]}
    reopened = pipeline.reopen_report(pipeline.export_report(approved))
    assert reopened["state"] == "IMPORTED_REVIEW"
    assert reopened["imported_approval_record"]["approved"] is True
    assert reopened["human_approval"]["active"] is False
    assert reopened["human_approval"]["approved"] is False
    assert reopened["can_approve"] is False
    assert reopened["calculation"] == report["calculation"]
    assert reopened["validation"] == report["validation"]


def test_saved_body_edit_with_old_digest_is_rejected(synthetic_case):
    body = json.loads(pipeline.export_report(approve(preview())))
    body["calculation"]["calculated_value"] = 999
    with pytest.raises(ValueError, match="REPORT_INTEGRITY_MISMATCH"):
        pipeline.reopen_report(json.dumps(body))


def test_real_in_memory_data_change_invalidates_only_synthetic_approval(synthetic_case):
    approved = approve(preview())
    changed = pipeline.recheck_changed_input(approved)
    assert changed["state"] == "BLOCKED_CHANGED_INPUT"
    assert changed["human_approval"]["status"] == "INVALIDATED"
    assert changed["human_approval"]["active"] is False
    assert changed["human_approval"]["approved"] is False
    assert changed["can_approve"] is False
    assert changed["input_sha256"] != approved["input_sha256"]
    assert (synthetic_case["root"] / "data.csv").read_bytes() == synthetic_case["data"]

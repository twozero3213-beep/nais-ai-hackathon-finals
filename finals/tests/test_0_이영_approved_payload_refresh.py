"""Fresh approval payload from the frozen synthetic integrity fixture; no real decisions."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
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

# [작성: 0 이영 · Codex] 2026-10-01T06:05:33+09:00 — 기존 봉인 R01~R03 기대와 합성 등록부를 바꾸지 않고 실제 승인 함수의 반환 계산/검증 일관성과 보호 관문을 회귀한다. confirmed 인자는 함수 시뮬레이션이며 실제 사람 결정/모델 호출은 없다.
AUDIT = ROOT / "docs/verification/0_이영_근거경계_20261001/integrity"
CASE_ID = "SYNTHETIC-INTEGRITY-MEAN"
REASON = "synthetic local regression reviewer; not a real human decision"
R_CASES = ("R01-calculation-value-tamper", "R02-within-tolerance-tamper", "R03-calculation-envelope-tamper")


@pytest.fixture
def synthetic_fixture(monkeypatch, tmp_path):
    protocol_bytes = (AUDIT / "protocol.json").read_bytes()
    seal = json.loads((AUDIT / "protocol-seal.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(protocol_bytes).hexdigest() == seal["protocol_file_sha256"]
    protocol = json.loads(protocol_bytes)
    initial = protocol["fixture"]
    (tmp_path / "data.csv").write_bytes(initial["csv"].encode())
    (tmp_path / "source.txt").write_bytes(initial["source"].encode())
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(initial["registry"]), encoding="utf-8")
    monkeypatch.setattr(cases, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cases, "REGISTRY", registry)

    def forbidden(*args, **kwargs):
        pytest.fail("Real transport or credential lookup is forbidden")

    monkeypatch.setattr(provider, "_api_key", forbidden)
    monkeypatch.setattr(provider.http.client, "HTTPSConnection", forbidden)
    return tmp_path, protocol


def file_snapshot(path):
    return {name: (path / name).read_bytes() for name in ("data.csv", "source.txt", "registry.json")}


def set_path(value, path, replacement):
    parts = path.split(".")
    target = value
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = deepcopy(replacement)


def assert_fresh_approval(original, approved, case):
    fresh_calculation = pipeline._calculate(case, original["proposal"])
    fresh_validation = pipeline._validation(case, original["proposal"])
    fresh_validation["human_semantic_confirmed"] = True
    assert approved["calculation"] == fresh_calculation
    assert approved["validation"] == fresh_validation
    assert approved["calculation"]["value"] == approved["calculation"]["calculated_value"] == 20
    assert approved["claim_snapshot"]["current_value"] == 20
    assert approved["claim_snapshot"]["semantic_confirmed"] is True
    assert approved["validation"]["human_semantic_confirmed"] is True
    assert approved["formal_verification"]["human_semantic_confirmed"] is True
    assert approved["human_approval"]["approved"] is True
    assert approved["human_approval"]["reason"] == REASON
    assert approved["state"] == "APPROVED" and not approved["can_approve"]
    assert not approved["llm_executed"] and approved["provider_calls"] == []


@pytest.mark.parametrize("case_id", R_CASES)
def test_frozen_R01_R03_replace_the_whole_calculation_envelope(synthetic_fixture, case_id):
    path, protocol = synthetic_fixture
    normal = pipeline.run_case_manual(CASE_ID)
    modified = deepcopy(normal)
    spec = next(item for item in protocol["cases"] if item["id"] == case_id)
    for field, value in spec["report_changes"].items():
        set_path(modified, field, value)
    before_report, before_files = deepcopy(modified), file_snapshot(path)
    approved = pipeline.approve_report(modified, REASON, confirmed=True)
    assert_fresh_approval(normal, approved, cases.load_case(CASE_ID))
    assert modified == before_report and file_snapshot(path) == before_files
    assert "untrusted_marker" not in approved["calculation"]["meta"]


def test_forged_validation_is_replaced_as_a_whole_not_merged(synthetic_fixture):
    path, _ = synthetic_fixture
    normal = pipeline.run_case_manual(CASE_ID)
    modified = deepcopy(normal)
    modified["validation"] = {"valid": False, "source_valid": False, "schema_valid": False,
        "six_conditions": [], "errors": ["SYNTHETIC_STALE_VALIDATION"],
        "human_semantic_confirmed": False, "untrusted_extra": {"n": 999}}
    before_report, before_files = deepcopy(modified), file_snapshot(path)
    approved = pipeline.approve_report(modified, REASON, confirmed=True)
    assert_fresh_approval(normal, approved, cases.load_case(CASE_ID))
    assert "untrusted_extra" not in approved["validation"]
    assert modified == before_report and file_snapshot(path) == before_files


def test_normal_approval_and_returned_nested_changes_do_not_mutate_inputs(synthetic_fixture):
    path, _ = synthetic_fixture
    original = pipeline.run_case_manual(CASE_ID)
    before_report, before_files = deepcopy(original), file_snapshot(path)
    case = cases.load_case(CASE_ID)
    approved = pipeline.approve_report(original, REASON, confirmed=True)
    assert_fresh_approval(original, approved, case)
    proposal_before = deepcopy(approved["proposal"])
    condition = next(item for item in approved["validation"]["six_conditions"] if item["condition"] == "denominator")
    condition["candidate"]["expected_n"] = 999
    approved["calculation"]["meta"]["untrusted_extra"] = 999
    assert approved["proposal"] == proposal_before
    assert original == before_report and file_snapshot(path) == before_files


def test_fresh_approved_report_export_reopen_remains_inactive(synthetic_fixture):
    original = pipeline.run_case_manual(CASE_ID)
    modified = deepcopy(original)
    modified["calculation"]["calculated_value"] = 999
    approved = pipeline.approve_report(modified, REASON, confirmed=True)
    encoded = pipeline.export_report(approved)
    assert json.loads(encoded)["calculation"]["calculated_value"] == 20
    reopened = pipeline.reopen_report(encoded)
    assert reopened["calculation"]["calculated_value"] == 20
    assert reopened["state"] == "IMPORTED_REVIEW"
    assert reopened["human_approval"]["active"] is False
    assert reopened["human_approval"]["approved"] is False and not reopened["can_approve"]


def test_actual_arithmetic_conflict_is_not_promoted_by_a_flag(synthetic_fixture):
    path, protocol = synthetic_fixture
    registry = deepcopy(protocol["fixture"]["registry"])
    registry["cases"][0]["reported_value"] = 999
    cases.REGISTRY.write_text(json.dumps(registry), encoding="utf-8")
    report = pipeline.run_case_manual(CASE_ID)
    assert report["status"] == "CONFLICT_PREVIEW"
    report["can_approve"] = True
    before_report, before_files = deepcopy(report), file_snapshot(path)
    with pytest.raises(ValueError, match="^APPROVAL_ARITHMETIC_CONFLICT$"):
        pipeline.approve_report(report, REASON, confirmed=True)
    assert report == before_report and file_snapshot(path) == before_files


@pytest.mark.parametrize("field", ("input_sha256", "source_sha256", "proposal_sha256"))
def test_report_binding_tamper_is_blocked(synthetic_fixture, field):
    report = pipeline.run_case_manual(CASE_ID)
    report[field] = "0" * 64
    before = deepcopy(report)
    with pytest.raises(ValueError, match="^APPROVAL_INPUT_CHANGED$"):
        pipeline.approve_report(report, REASON, confirmed=True)
    assert report == before


def test_current_synthetic_csv_change_is_blocked(synthetic_fixture):
    path, _ = synthetic_fixture
    report = pipeline.run_case_manual(CASE_ID)
    (path / "data.csv").write_text("group,age\nA,10\nA,32\nB,40\n", encoding="utf-8")
    with pytest.raises(ValueError, match="^APPROVAL_INPUT_CHANGED$"):
        pipeline.approve_report(report, REASON, confirmed=True)


@pytest.mark.parametrize("critique", ({"evidence_ready": False, "issues": []},
                                    {"evidence_ready": True, "issues": ["SYNTHETIC_UNRESOLVED"]}))
def test_unresolved_critique_remains_blocked(synthetic_fixture, critique):
    report = pipeline.run_case_manual(CASE_ID)
    report["critique"] = deepcopy(critique)
    before = deepcopy(report)
    with pytest.raises(ValueError, match="^APPROVAL_CRITIQUE_UNRESOLVED$"):
        pipeline.approve_report(report, REASON, confirmed=True)
    assert report == before


def test_explicit_confirmation_is_still_required(synthetic_fixture):
    report = pipeline.run_case_manual(CASE_ID)
    with pytest.raises(ValueError, match="^EXPLICIT_HUMAN_CONFIRMATION_AND_REASON_REQUIRED$"):
        pipeline.approve_report(report, REASON)


@pytest.mark.parametrize("label", ("password", "api_key", "authorization"))
def test_credential_reason_still_fails_without_value_reflection(synthetic_fixture, label):
    report = pipeline.run_case_manual(CASE_ID)
    marker = "SYNTHETIC_CREDENTIAL_ONLY"
    before = deepcopy(report)
    with pytest.raises(ValueError) as failure:
        pipeline.approve_report(report, label + chr(61) + marker, confirmed=True)
    assert str(failure.value) == "APPROVAL_REASON_PERSONAL_DATA"
    assert marker not in str(failure.value) and report == before

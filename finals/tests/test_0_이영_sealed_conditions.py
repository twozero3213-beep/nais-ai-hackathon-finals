"""봉인 비교의 미확인 조건·인용·중복필터를 실행 전에 차단하는 경계 회귀.

# [작성: 0 이영 · Codex] 2026-10-01 03:00 KST — 등록 정답이나 봉인 입력을 바꾸지 않고 합성 원문으로 완성된 여섯 조건 경로와 실패 공개를 확인한다.
"""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

FINALS = Path(__file__).resolve().parents[1]
for path in (FINALS.parent, FINALS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
import sealed_runner as runner

SOURCE = ("Group A has 2 rows. Group B has 2 rows. The mean of score in points for group A is 15. "
          "There are no missing values; use missing policy error.")


def supported_proposal():
    return {"method": "mean", "column": "score", "filters": [{"column": "group", "value": "A"}],
            "missing_policy": "error", "denominator": "Group A has 2 rows", "unit": "points", "unresolved": [],
            "field_evidence": {"method": ["The mean of score in points for group A is 15."],
                               "column": ["The mean of score in points for group A is 15."],
                               "filters": ["Group A has 2 rows."], "denominator": ["Group A has 2 rows."],
                               "missing_policy": ["There are no missing values; use missing policy error."],
                               "unit": ["The mean of score in points for group A is 15."]}}


@pytest.mark.parametrize("changes", [
    {"denominator": None}, {"unit": None}, {"denominator": " "}, {"unit": ""},
    {"unresolved": ["unit unknown"]}, {"unresolved": None},
    {"filters": [{"column": "group", "value": "A"}, {"column": "group", "value": "B"}]},
    {"unit": "meters"}, {"denominator": "Group A has 4 rows"},
])
def test_incomplete_or_conflicting_conditions_cannot_execute(changes):
    proposal = supported_proposal() | changes
    assert runner.conditions_from(proposal, source_excerpt=SOURCE) is None


@pytest.mark.parametrize("field", runner.SIX_CONDITIONS)
def test_each_condition_requires_an_actual_quote(field):
    for quote in (None, [], ["invented statement"]):
        proposal = supported_proposal()
        proposal["field_evidence"][field] = quote
        assert runner.conditions_from(proposal, source_excerpt=SOURCE) is None


def test_complete_conditions_preserve_unit_denominator_evidence_and_never_approve():
    proposal = supported_proposal()
    conditions = runner.conditions_from(proposal, source_excerpt=SOURCE)
    assert conditions["filters"] == {"group": "A"}
    assert conditions["denominator"] == proposal["denominator"] and conditions["unit"] == "points"
    assert conditions["field_evidence"] == proposal["field_evidence"]
    assert runner.conditions_from(proposal) is None
    proposal["field_evidence"]["unit"].clear()
    assert conditions["field_evidence"]["unit"]  # 출처 메타데이터의 사후변경이 정규화 사본에 영향 없음


def test_grounded_synthetic_model_proposal_uses_existing_engine_and_records_failures(tmp_path):
    data = b"group,score\nA,10\nA,20\nB,30\nB,40\n"
    source = SOURCE.encode("utf-8")
    (tmp_path / "data.csv").write_bytes(data)
    (tmp_path / "source.txt").write_bytes(source)
    registration = {"claim_id": "C03", "claim_text": "Group A mean score is 15 points", "column": "score",
        "method": "mean", "filters": {"group": "A"}, "missing_policy": "error", "reported_value": 16,
        "tolerance": 0, "scope_status": "EVALUATION_MAPPING", "paper_url": "https://example.invalid/synthetic",
        "source_file": "source.txt", "source_sha256": runner.sha(source), "source_quote": SOURCE,
        "source_location": "Synthetic paragraph 1", "source_kind": "article_extract",
        "data_file": "data.csv", "data_sha256": runner.sha(data)}
    packet = {"registration": registration, "question": "Verify arithmetic only", "source_text": SOURCE,
              "current_csv": data.decode(), "registered_data_sha256": runner.sha(data),
              "current_data_sha256": runner.sha(data), "prior_result_reuse_requested": False, "prior_human_approval": False}

    def provider(system, body, **kwargs):
        proposal = supported_proposal()
        proposal["filters"] = [{"column": "group", "value": "B"}]
        proposal["denominator"] = "Group B has 2 rows"
        proposal["field_evidence"]["filters"] = proposal["field_evidence"]["denominator"] = ["Group B has 2 rows."]
        return {"output": proposal, "usage": {"input_tokens": 10, "output_tokens": 20}}

    report = runner.run_sealed({"C03": packet}, {"C03": {"action": "ARITHMETIC_MISMATCH", "value": 15}},
                               provider, evidence_dir=tmp_path, conditions=("with_llm",))
    row = next(item for item in report["results"] if item["condition"] == "with_llm")
    assert row["decision"] == "ARITHMETIC_MISMATCH" and row["value"] == 35 and row["passed"] is False
    assert row["fields_differing_from_registered"] == ["filters", "denominator", "unit"]
    assert row["human_approval"] is False and row["evaluation_scope"] == "ARITHMETIC_PREVIEW_NOT_HUMAN_APPROVAL"
    assert report["condition_adapter"]["post_seal_extension"] is True


def test_unresolved_model_candidate_never_reaches_the_second_calculation(monkeypatch):
    packet = runner.load_packets(runner.EVIDENCE, ("C03",))["C03"]
    calls = []

    def audited(*args):
        calls.append(args)
        return {"decision": "ARITHMETIC_MISMATCH", "value": 15, "reason": "COMPUTED"}

    monkeypatch.setattr(runner, "audit_with", audited)
    proposal = supported_proposal() | {"denominator": None, "unit": None, "unresolved": ["source unsupported"]}
    report = runner.run_sealed({"C03": packet}, {"C03": {"action": "ARITHMETIC_MISMATCH", "value": 15}},
        lambda *a, **k: {"output": deepcopy(proposal)}, conditions=("with_llm",))
    assert len(calls) == 1  # 모델 없는 기준 경로만 실행; 후보 경로의 계산은 하지 않는다.
    row = next(item for item in report["results"] if item["condition"] == "with_llm")
    assert row["decision"] == "BLOCK" and row["value"] is None and row["passed"] is False


@pytest.mark.parametrize("decision", ["BLOCK", "STALE_BLOCK"])
def test_numeric_output_on_a_blocked_case_never_counts_as_a_pass(decision):
    gold = {"action": decision, "value": None}
    assert runner.score(decision, None, gold)["passed"] is True
    scored = runner.score(decision, 7, gold)
    assert scored["decision_correct"] is True and scored["value_correct"] is False
    assert scored["passed"] is False and scored["claimed_number_on_blocked_case"] is True


def test_generated_contact_is_blocked_before_raw_output_is_recorded():
    packet = runner.load_packets(runner.EVIDENCE, ("C03",))["C03"]
    contact = "synthetic" + chr(64) + "example.invalid"
    output = {"decision": "BLOCK", "calculated_value": None, "evidence_location": None, "reason": contact}
    report = runner.run_sealed({"C03": packet}, {"C03": {"action": "ARITHMETIC_MISMATCH", "value": 15}},
        lambda *a, **k: {"output": output, "usage": {"input_tokens": 10, "output_tokens": 20}}, conditions=("general_ai",))
    row = next(item for item in report["results"] if item["condition"] == "general_ai")
    assert row["execution_status"] == "ERROR" and row["error"] == "PERSONAL_DATA_IN_MODEL_OUTPUT"
    assert contact not in str(report) and "model_output" not in row
    assert row["new_model_calls"] == 1 and report["summary"]["general_ai"]["output_tokens"] == 20


def test_invalid_response_schema_keeps_billed_usage_without_reflecting_raw_content():
    raw_value = "synthetic-private-content"
    with pytest.raises(runner.ModelOutputRejected) as error:
        runner.ask(lambda *a, **k: {"output": {"bad": raw_value}, "usage": {"input_tokens": 10, "output_tokens": 20}},
                   runner.GENERAL_SYSTEM, {}, runner.DECISION_SCHEMA)
    assert str(error.value) == "MODEL_OUTPUT_SCHEMA_INVALID"
    assert error.value.receipt["usage"]["output_tokens"] == 20 and raw_value not in str(error.value)

"""[0 이영 · Claude] 봉인 비교 실행기 시험: 모의 공급자로 채점·오류·상한·개인정보 차단·표의 정직성을 확인한다. 실제 모델·네트워크는 쓰지 않는다.

# [작성: 0 이영 · Claude] 2026-10-01 03:05 KST — 공개 저장소에 있는 합성 사례 C03·C04·C06 패킷만 쓴다(나머지 입력은 비공개 묶음으로 복원해야 한다).
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

import pytest

FINALS = Path(__file__).resolve().parents[1]
ROOT = FINALS.parent
for path in (ROOT, FINALS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import sealed_runner as runner

PUBLIC = ("C03", "C04", "C06")
EXPECTED = json.loads((runner.EVIDENCE / "expected.json").read_text(encoding="utf-8"))


def packets(ids=PUBLIC):
    return runner.load_packets(runner.EVIDENCE, ids)


class Mock:
    """정답을 아는 모의 공급자. general/conditions 출력을 사례별로 덮어쓸 수 있다."""

    def __init__(self, general=None, conditions=None, error=None):
        self.general, self.conditions, self.error, self.calls = general or {}, conditions or {}, error, []

    def __call__(self, system, payload, schema=None, timeout=45):
        self.calls.append((system, payload))
        if self.error:
            raise ValueError(self.error)
        registration = payload["registration"]
        case_id = registration["claim_id"]
        if system == runner.GENERAL_SYSTEM:
            gold = EXPECTED[case_id]
            output = {"decision": gold["action"], "calculated_value": gold["value"], "evidence_location": None, "reason": "모의"}
            output.update(self.general.get(case_id, {}))
        else:
            output = {"method": registration["method"], "column": registration["column"],
                      "filters": [{"column": k, "value": str(v)} for k, v in registration["filters"].items()],
                      "missing_policy": registration["missing_policy"], "denominator": None, "unit": None, "unresolved": []}
            output.update(self.conditions.get(case_id, {}))
        return {"output": output, "usage": {"input_tokens": 100, "output_tokens": 20}, "provider": "openai", "model": "gpt-4.1-mini",
                "request_id": "resp_mock", "raw_sha256": "0" * 64}


def cells(report, condition):
    return {row["case_id"]: row for row in report["results"] if row["condition"] == condition}


def test_excerpt_is_deterministic_bounded_and_strips_tags():
    filler = "<p>" + "x " * 4000 + "</p>"
    text = filler + "<b>The table has 344 rows.</b>" + filler
    first = runner.excerpt(text, "The table has 344 rows.")
    assert first == runner.excerpt(text, "The table has 344 rows.")
    assert "The table has 344 rows." in first and "<" not in first and len(first) <= 2 * runner.EXCERPT_RADIUS + 60
    assert runner.excerpt("짧은 원문", "원문") == "짧은 원문"                     # 짧으면 그대로
    assert len(runner.excerpt(text, "없는 인용")) <= 2 * runner.EXCERPT_RADIUS   # 인용을 못 찾으면 앞부분만


def test_output_schemas_follow_strict_structured_output_rules():
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    for schema in (runner.DECISION_SCHEMA, runner.CONDITIONS_SCHEMA):
        walk(schema)
        assert not any(key in json.dumps(schema) for key in ("minLength", "maxLength", "pattern", "minimum"))   # 요청 형식이 지원하지 않는 제약어 없음


def test_model_input_has_no_expected_answer_and_both_ai_conditions_receive_the_same_body():
    for packet in packets().values():
        body = runner.model_input(packet)
        assert "expected" not in json.dumps(body).lower()
    mock = Mock()
    report = runner.run_sealed(packets(), EXPECTED, mock)
    general, with_llm = cells(report, "general_ai"), cells(report, "with_llm")
    assert all(general[c]["input_sha256"] == with_llm[c]["input_sha256"] for c in PUBLIC)   # 같은 입력 지문
    bodies = [payload for _, payload in mock.calls]
    assert bodies[0] == bodies[1] and len(mock.calls) == 6


def test_correct_answers_pass_in_all_three_conditions():
    report = runner.run_sealed(packets(), EXPECTED, Mock())
    for condition in ("without_llm", "general_ai", "with_llm"):
        assert all(row["passed"] for row in cells(report, condition).values()), condition
    assert cells(report, "with_llm")["C03"]["value"] == 15 and cells(report, "with_llm")["C04"]["value"] == 35
    assert report["summary"]["general_ai"]["passed"] == 3 and report["summary"]["with_llm"]["input_tokens"] == 300
    assert report["provider_calls"] == 6 and report["aborted"] is None


def test_wrong_answers_are_recorded_as_failures_and_never_hidden():
    mock = Mock(general={"C03": {"decision": "ARITHMETIC_MATCH", "calculated_value": 16},            # 판정이 틀림
                         "C06": {"decision": "ARITHMETIC_MATCH", "calculated_value": 7}},            # 근거 부족 사례에서 숫자를 주장
                conditions={"C03": {"filters": [{"column": "group", "value": "B"}]}})                # 조건을 잘못 제안
    report = runner.run_sealed(packets(), EXPECTED, mock)
    general, with_llm = cells(report, "general_ai"), cells(report, "with_llm")
    assert not general["C03"]["passed"] and not general["C03"]["decision_correct"]
    assert general["C06"]["claimed_number_on_blocked_case"] and not general["C06"]["passed"]
    assert general["C04"]["passed"]
    assert not with_llm["C03"]["passed"] and with_llm["C03"]["value"] == 35 and with_llm["C03"]["decision_correct"] and not with_llm["C03"]["value_correct"]
    assert with_llm["C03"]["fields_differing_from_registered"] == ["filters"]
    assert report["summary"]["general_ai"]["failed"] == 2 and report["summary"]["general_ai"]["claimed_number_on_blocked_case"] == 1


def test_unknown_conditions_stop_the_model_path_without_a_calculation():
    mock = Mock(conditions={"C03": {"filters": None}, "C06": {"method": None, "unresolved": ["분모"]}})
    with_llm = cells(runner.run_sealed(packets(), EXPECTED, mock), "with_llm")
    assert with_llm["C03"]["decision"] == "BLOCK" and with_llm["C03"]["audit_reason"] == "MODEL_PROPOSAL_UNRESOLVED" and not with_llm["C03"]["passed"]
    assert with_llm["C06"]["decision"] == "BLOCK" and with_llm["C06"]["passed"]          # 검증할 수 없는 사례에서 멈춘 것은 정답이다
    assert with_llm["C03"]["fields_differing_from_registered"] == ["method", "column", "filters", "missing_policy"]


def test_provider_errors_are_recorded_and_the_run_aborts_after_consecutive_errors():
    report = runner.run_sealed(packets(), EXPECTED, Mock(error="MODEL_HTTP_429"))
    statuses = [(row["case_id"], row["condition"], row["execution_status"]) for row in report["results"] if row["condition"] != "without_llm"]
    assert [s[2] for s in statuses] == ["ERROR", "ERROR", "NOT_RUN", "NOT_RUN", "NOT_RUN", "NOT_RUN"]
    assert report["aborted"] == "ABORTED_AFTER_CONSECUTIVE_ERRORS:MODEL_HTTP_429" and report["provider_calls"] == 2
    assert cells(report, "general_ai")["C03"]["error"] == "MODEL_HTTP_429"
    assert all(row["passed"] for row in cells(report, "without_llm").values())            # 모델 없는 경로는 영향이 없다


def test_call_budget_caps_provider_calls():
    mock = Mock()
    report = runner.run_sealed(packets(), EXPECTED, mock, max_calls=2)
    assert len(mock.calls) == 2 and report["provider_calls"] == 2
    assert sum(1 for row in report["results"] if row.get("blocker") == "CALL_BUDGET_EXHAUSTED") == 4


def test_personal_data_in_the_model_input_is_never_sent():
    data = packets(("C03",))
    data["C03"]["source_text"] += " 문의 kim" + chr(64) + "lab.ac.kr"
    mock = Mock()
    report = runner.run_sealed(data, EXPECTED, mock)
    assert mock.calls == [] and report["provider_calls"] == 0
    assert {row["blocker"] for row in report["results"] if row["execution_status"] == "NOT_RUN"} == {"PERSONAL_DATA_IN_OUTBOUND_PAYLOAD"}


def test_changed_data_is_stale_block_by_fingerprint(tmp_path):
    evidence = tmp_path / "evidence"
    (evidence / "inputs").mkdir(parents=True)
    for name in ("C03-data.csv", "C03-source.txt"):
        shutil.copy(runner.EVIDENCE / "inputs" / name, evidence / "inputs" / name)
    registration = packets(("C03",))["C03"]["registration"]
    assert runner.audit_with(registration, evidence)["decision"] == "ARITHMETIC_MISMATCH"         # 그대로면 산술 불일치(보고 16, 계산 15)
    (evidence / "inputs" / "C03-data.csv").write_bytes(b"group,score\nA,10\nA,20\nB,30\n")      # 자료가 바뀜
    assert runner.audit_with(registration, evidence) | {"reason": None} == {"decision": "STALE_BLOCK", "value": None, "reason": None}


def test_table_keeps_failures_and_not_run_cells_visible():
    mock = Mock(general={"C03": {"decision": "BLOCK", "calculated_value": None}})
    report = runner.run_sealed(packets(), EXPECTED, mock, max_calls=5)
    table = runner.render_table(report, EXPECTED)
    assert "**불일치**" in table and "미실행: CALL_BUDGET_EXHAUSTED" in table
    assert "일반적 우위나 모델 성능을 입증하지 않는다" in table and "영수증이 아니다" in table


def test_main_requires_spend_confirmation_and_writes_a_complete_record(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "verify_seal", lambda evidence=None: {})       # 공개 저장소에는 비공개 입력이 없어 봉인 검증을 이 시험에서는 건너뛴다
    assert runner.main(["--cases", "C03,C04,C06"]) == 2                          # 확인 없이는 공급자를 만들지 않는다
    assert "CONFIRM_SPEND_REQUIRED" in capsys.readouterr().out
    code = runner.main(["--cases", "C03,C04,C06", "--results-dir", str(tmp_path)], provider=Mock())
    assert code == 0
    folder = next(tmp_path.iterdir())
    record = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    assert record["excerpt_radius"] == runner.EXCERPT_RADIUS and record["cost_status"] == "ESTIMATED_FROM_USAGE_NOT_A_RECEIPT"
    assert record["contributor_version"] == 0 and len(record["seal_sha256"]) == 64 and len(record["runner_sha256"]) == 64
    assert (folder / "presentation-table.md").read_text(encoding="utf-8").startswith("| 사례 |")
    assert "sk-" not in json.dumps(record)

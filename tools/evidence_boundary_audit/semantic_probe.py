"""고정된 공개 Git 함수의 조건/인용 연결 범위를 순수 합성 입력으로 관측한다.

[작성: 0 이영 · Codex] 2026-10-01T04:44:17+09:00 · 담당 버전 0.
수정 이유: 실제 인용 존재와 대상 주장/필드 의미의 연결을 구분하는 탐색 검증.
제품 함수 수정, 모의 모델, 사람 확정/승인 지정, 외부 API 호출은 하지 않는다.
--seal로 먼저 protocol.json과 그 지문을 기록한 뒤 --run으로 실행한다.
기존 C01~C08 봉인, 모델 비교, 실제 논문 정답률과 별개다.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

VERSION = 0
COMMIT = "d8d952b43eff8ab416421da8f0f431a64e8b9241"
PRODUCT_PATH = "finals/sealed_runner.py"
FUNCTIONS = ("conditions_from", "semantic_review")
KST = timezone(timedelta(hours=9))
BASE_SOURCE = (
    "The primary outcome was the mean age in group A: 20 years. "
    "The age column records age in years. The analysis uses group=A. "
    "The denominator is 2 included observations. "
    "Missing ages must trigger an error; none are missing."
)
BASE_EVIDENCE = {
    "method": ["The primary outcome was the mean age in group A: 20 years."],
    "column": ["The age column records age in years."],
    "filters": ["The analysis uses group=A."],
    "denominator": ["The denominator is 2 included observations."],
    "missing_policy": ["Missing ages must trigger an error; none are missing."],
    "unit": ["The age column records age in years."],
}


def now():
    return datetime.now(KST).isoformat(timespec="microseconds")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_new(path, value):
    raw = canonical(value)
    with path.open("xb") as handle:
        handle.write(raw)
    return sha(raw)


def proposal(**changes):
    item = {
        "method": "mean", "column": "age", "filters": [{"column": "group", "value": "A"}],
        "denominator": "2 included observations", "missing_policy": "error", "unit": "years",
        "field_evidence": deepcopy(BASE_EVIDENCE), "unresolved": [],
    }
    item.update(deepcopy(changes))
    return item


def case(cid, category, source, candidate, target, expected_source_semantics, explanation,
         expected_adapter=True, registration=None, expected_registered_verified=True,
         expected_registered_blocking=False):
    if registration is None:
        registration = {"denominator": candidate.get("denominator"), "unit": candidate.get("unit")}
    return {
        "case_id": cid, "category": category, "source_excerpt": source, "proposal": candidate,
        "registered_contract": registration, "target_claim_for_manual_expectation": target,
        "manual_expected_source_linkage": "SUPPORTED" if expected_source_semantics else "UNSUPPORTED",
        "manual_expectation_basis": explanation,
        "expected_adapter_by_published_structural_contract": "ACCEPTED" if expected_adapter else "REJECTED",
        "expected_registered_comparison_verified": expected_registered_verified,
        "expected_registered_comparison_blocking": expected_registered_blocking,
        "expectation_author": "0 이영 · Codex; 합성 예시 수동 판단",
        "no_independent_empirical_gold_standard": True,
    }


def inputs():
    rows = [case("N01", "normal", BASE_SOURCE, proposal(), "Primary mean age in group A, 20 years",
                 True, "대상·집단·변수·방법·단위·분모·결측 정책을 원문이 명시한다.")]
    source_b = BASE_SOURCE.replace("group A", "group B").replace("group=A", "group=B")
    evidence_b = {key: [quote.replace("group A", "group B").replace("group=A", "group=B") for quote in quotes]
                  for key, quotes in BASE_EVIDENCE.items()}
    rows.append(case("N02", "normal", source_b,
                     proposal(filters=[{"column": "group", "value": "B"}], field_evidence=evidence_b),
                     "Primary mean age in group B, 20 years", True, "B군의 맞는 연결을 정상 대조한다."))
    rows.append(case("A01", "wrong_group", BASE_SOURCE,
                     proposal(filters=[{"column": "group", "value": "B"}]),
                     "Primary mean age in group A, 20 years", False,
                     "필터는 B인데 필터 인용과 대상 주장은 A다. 인용이 존재해도 B 연결 근거가 아니다."))
    excluded = (
        "The mean age in group A was not the primary outcome. Group A was excluded from the final analysis. "
        "The primary analysis uses group B. The age column records age in years. "
        "The denominator is 2 included observations. Missing ages must trigger an error; none are missing."
    )
    excluded_evidence = deepcopy(BASE_EVIDENCE)
    excluded_evidence["method"] = ["The mean age in group A was not the primary outcome."]
    excluded_evidence["filters"] = ["Group A was excluded from the final analysis."]
    rows.append(case("A02", "negation_exclusion", excluded, proposal(field_evidence=excluded_evidence),
                     "Mean age of the included primary group", False,
                     "존재하는 인용은 A군 포함이 아니라 A군 배제를 말한다."))
    baseline = (
        "The baseline mean age in group A was 20 years. "
        "The primary reported endpoint was the mean change in followup_duration for group A, 3 years. "
        "The age column records baseline age in years. The analysis uses group=A. "
        "The denominator is 2 included observations. Missing ages must trigger an error; none are missing."
    )
    baseline_evidence = deepcopy(BASE_EVIDENCE)
    baseline_evidence["method"] = ["The baseline mean age in group A was 20 years."]
    baseline_evidence["column"] = baseline_evidence["unit"] = ["The age column records baseline age in years."]
    rows.append(case("A03", "baseline_not_reported_endpoint", baseline,
                     proposal(field_evidence=baseline_evidence), "Primary mean change in followup_duration, 3 years",
                     False, "각 조건은 기준시점 나이의 설명이고 목표인 추적 변화량의 조건이 아니다."))
    denominator_source = BASE_SOURCE.replace(
        "The denominator is 2 included observations.",
        "The denominator is 2 observations: two scheduled visits from one participant, not two participants.")
    denominator_evidence = deepcopy(BASE_EVIDENCE)
    denominator_evidence["denominator"] = [
        "The denominator is 2 observations: two scheduled visits from one participant, not two participants."]
    rows.append(case("A04", "denominator_different_entity", denominator_source,
                     proposal(denominator="2 observations", field_evidence=denominator_evidence),
                     "Mean age across two independent participants", False,
                     "관측 두 건은 한 사람의 두 방문이다. 문자열·숫자 2로 독립 참가자 두 명을 뜻하지 않는다."))
    different_variable = (
        "The primary outcome was the mean followup_duration in group A: 20 years. "
        "The age column records baseline age in years. The analysis uses group=A. "
        "The denominator is 2 included observations. Missing ages must trigger an error; none are missing."
    )
    variable_evidence = deepcopy(BASE_EVIDENCE)
    variable_evidence["method"] = ["The primary outcome was the mean followup_duration in group A: 20 years."]
    variable_evidence["column"] = variable_evidence["unit"] = ["The age column records baseline age in years."]
    rows.append(case("A05", "same_unit_different_variable", different_variable,
                     proposal(field_evidence=variable_evidence), "Primary mean followup_duration, 20 years",
                     False, "추적기간과 나이는 모두 years지만 다른 변수다. age 열의 근거는 목표 변수 연결 근거가 아니다."))
    invented = deepcopy(BASE_EVIDENCE)
    invented["filters"] = ["The analysis uses group=B."]
    rows.append(case("C01", "nonexistent_quote", BASE_SOURCE, proposal(field_evidence=invented),
                     "Primary mean age in group A", False, "필터 인용문이 전송 원문에 없다.",
                     expected_adapter=False, expected_registered_verified=False, expected_registered_blocking=True))
    rows.append(case("C02", "unresolved", BASE_SOURCE, proposal(unresolved=["population unknown"]),
                     "Primary mean age in group A", False, "미해결 목록이 비어 있지 않아 실행 후보로 보내면 안 된다.",
                     expected_adapter=False, expected_registered_verified=False, expected_registered_blocking=True))
    rows.append(case("C03", "missing_unit", BASE_SOURCE, proposal(unit=None),
                     "Primary mean age in group A", False, "단위 필수값 누락을 구조적 음성 대조한다.",
                     expected_adapter=False, expected_registered_verified=False, expected_registered_blocking=True))
    rows.append(case("C04", "missing_registered_contract", BASE_SOURCE, proposal(),
                     "Primary mean age in group A", True,
                     "원문 연결 정상이어도 등록 계약 부재는 semantic_review의 NOT_VERIFIED여야 한다.",
                     registration={}, expected_registered_verified=False))
    rows.append(case("C05", "conflicting_registered_contract", BASE_SOURCE, proposal(),
                     "Primary mean age in group A", True,
                     "원문 years와 등록 months가 충돌한다. 이는 원문 의미 오류가 아니라 등록 계약 충돌 대조다.",
                     registration={"denominator": "2 included observations", "unit": "months"},
                     expected_registered_verified=False, expected_registered_blocking=True))
    design_source = (
        "The baseline mean age in group A was 20 years. The primary follow-up endpoint was mean "
        "followup_duration in group A, 3 years. The age column records baseline age in years. "
        "The analysis uses group=A. The denominator is 2 included observations. "
        "Missing ages must trigger an error; none are missing."
    )
    design_evidence = deepcopy(BASE_EVIDENCE)
    design_evidence["method"] = ["The baseline mean age in group A was 20 years."]
    design_evidence["column"] = design_evidence["unit"] = ["The age column records baseline age in years."]
    rows.append(case("D01", "minimal_repair_counterexample", design_source,
                     proposal(field_evidence=design_evidence), "Primary follow-up mean followup_duration, 3 years",
                     False, "필드별 단어·필터값·단위가 모두 인용 안에 있어도 모든 인용이 기준시점 나이에 속한다. 목표 주장/시점 연결이 빠졌다."))
    return rows


def product_source(repo):
    return subprocess.check_output(["git", "show", f"{COMMIT}:{PRODUCT_PATH}"], cwd=repo)


def select_ast(raw):
    tree = ast.parse(raw.decode("utf-8"))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    if {node.name for node in selected} != set(FUNCTIONS):
        raise ValueError("PURE_FUNCTION_MISSING")
    for node in selected:
        if node.decorator_list or any(isinstance(item, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal))
                                      for item in ast.walk(node)):
            raise ValueError("UNEXPECTED_FUNCTION_SIDE_EFFECT_BOUNDARY")
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "SIX_CONDITIONS" for target in node.targets))
    fields = ast.literal_eval(assignment.value)
    functions_ast = ast.Module(body=selected, type_ignores=[])
    return functions_ast, fields


def minimal_proposed_lexical_checks(candidate, accepted):
    """보완 설계의 가장 약한 형태를 탐색한다. 제품 함수나 의미 검증기가 아니다."""
    if not accepted:
        return {"accepted": False, "scope": "LOCAL_DESIGN_SKETCH_NOT_PRODUCT"}
    evidence = candidate["field_evidence"]
    def present(term, field):
        return any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", quote, re.I) for quote in evidence[field])
    positive = present(candidate["method"], "method") and present(candidate["column"], "column")
    for item in candidate["filters"]:
        positive = positive and present(item["column"], "filters") and present(item["value"], "filters")
    positive = positive and not any(re.search(r"\b(?:not|excluded|exclude|without)\b", quote, re.I)
                                   for quote in evidence["filters"])
    return {"accepted": bool(positive), "scope": "LOCAL_DESIGN_SKETCH_NOT_PRODUCT",
            "limits": "원문 인용의 필드 단어 확인만 추가. 대상 주장·시점·문맥의 결속을 검사하지 않음."}


def seal(repo, output):
    raw = product_source(repo)
    node, fields = select_ast(raw)
    protocol = {
        "experiment": "SEMANTIC_LINKAGE_EXPLORATION_NOT_SEALED_C01_C08_OR_MODEL_COMPARISON",
        "author": "0 이영 · Codex", "contributor_version": VERSION, "created_at_kst": now(),
        "_change_note": "합성 입력과 수동 의미 기대 판정, 공개 함수의 구조적 검사 기대값을 실행 전에 고정한다.",
        "product_commit": COMMIT, "product_path": PRODUCT_PATH, "source_sha256": sha(raw),
        "selected_ast_sha256": sha(ast.dump(node, include_attributes=False).encode("utf-8")),
        "selected_functions": list(FUNCTIONS), "six_conditions": list(fields),
        "runner_sha256": sha(Path(__file__).read_bytes()), "cases": inputs(),
        "forbidden_actions": ["product_patch", "mock_provider", "human_confirmation_or_approval", "model_call", "external_api_call"],
        "expected_boundary": "accepted는 함수가 dict를 반환했다는 의미뿐이며 원문 의미 정확성·LLM 답변·계산·사람 승인을 뜻하지 않는다.",
        "manual_gold_limit": "합성 예시 수동 판단이며 독립 전문가 정답률 검증이 아니다. 구조 검사 기대값과 의미 기대값을 별도로 고정한다.",
        "execution_counters_expected": {"model_calls": 0, "external_api_calls": 0, "human_approvals": 0, "product_files_modified": 0},
    }
    protocol_hash = write_new(output / "protocol.json", protocol)
    write_new(output / "protocol-seal.json", {"created_at_kst": now(), "contributor_version": VERSION,
              "protocol_sha256": protocol_hash, "runner_sha256": protocol["runner_sha256"],
              "status": "FIXED_BEFORE_FIRST_EXECUTION", "_change_note": "실행 전 프로토콜 바이트 SHA-256을 별도 보존."})
    return {"action": "SEALED_EXPLORATION_INPUTS", "cases": len(protocol["cases"]), "protocol_sha256": protocol_hash}


def run(repo, output):
    started = now()
    protocol_raw = (output / "protocol.json").read_bytes()
    protocol = json.loads(protocol_raw)
    seal_record = json.loads((output / "protocol-seal.json").read_bytes())
    if sha(protocol_raw) != seal_record["protocol_sha256"] or sha(Path(__file__).read_bytes()) != seal_record["runner_sha256"]:
        raise ValueError("PRE_EXECUTION_INPUT_OR_RUNNER_CHANGED")
    raw = product_source(repo)
    node, fields = select_ast(raw)
    if sha(raw) != protocol["source_sha256"] or list(fields) != protocol["six_conditions"]:
        raise ValueError("PINNED_PRODUCT_SOURCE_CHANGED")
    environment = {"deepcopy": deepcopy, "SIX_CONDITIONS": fields}
    exec(compile(node, f"{COMMIT}:{PRODUCT_PATH}", "exec"), environment)
    results = []
    for item in protocol["cases"]:
        observed_at = now()
        returned, error, semantic = None, None, None
        try:
            returned = environment["conditions_from"](deepcopy(item["proposal"]), source_excerpt=item["source_excerpt"])
            semantic = environment["semantic_review"](returned, deepcopy(item["registered_contract"]))
        except Exception as exc:
            error = type(exc).__name__
        accepted = isinstance(returned, dict)
        actual = "EXCEPTION" if error else "ACCEPTED" if accepted else "REJECTED"
        result = {"case_id": item["case_id"], "observed_at_kst": observed_at, "category": item["category"],
                  "input_sha256": sha(canonical(item)), "actual_adapter_status": actual,
                  "actual_return": returned, "exception_type": error, "semantic_review_return": semantic,
                  "manual_expected_source_linkage": item["manual_expected_source_linkage"],
                  "structural_expectation_matches": actual == item["expected_adapter_by_published_structural_contract"],
                  "accepted_despite_manual_unsupported_linkage": accepted and item["manual_expected_source_linkage"] == "UNSUPPORTED",
                  "proposed_minimal_lexical_guard": minimal_proposed_lexical_checks(item["proposal"], accepted),
                  "scope": "PURE_ADAPTER_AND_REGISTERED_STRING_COMPARISON_ONLY_NO_FINAL_VERDICT"}
        if semantic is not None:
            result["registered_comparison_expectation_matches"] = (
                semantic["verified"] == item["expected_registered_comparison_verified"]
                and bool(semantic["blocking_issues"]) == item["expected_registered_comparison_blocking"])
        results.append(result)
    summary = {"cases": len(results), "accepted": sum(r["actual_adapter_status"] == "ACCEPTED" for r in results),
               "rejected": sum(r["actual_adapter_status"] == "REJECTED" for r in results),
               "exceptions": sum(r["exception_type"] is not None for r in results),
               "accepted_despite_manual_unsupported_linkage": sum(r["accepted_despite_manual_unsupported_linkage"] for r in results),
               "structural_expectation_matches": sum(r["structural_expectation_matches"] for r in results),
               "registered_comparison_expectation_matches": sum(r.get("registered_comparison_expectation_matches", False) for r in results)}
    report = {"author": "0 이영 · Codex", "contributor_version": VERSION, "started_at_kst": started,
              "finished_at_kst": now(), "_change_note": "프로토콜 봉인 후 최신 공개 순수 함수만 실행하여 실제 리턴과 범위를 기록.",
              "product_commit": COMMIT, "product_path": PRODUCT_PATH, "source_sha256": sha(raw),
              "protocol_sha256": seal_record["protocol_sha256"], "runner_sha256": seal_record["runner_sha256"],
              "python": sys.version, "summary": summary, "results": results,
              "execution_counters": protocol["execution_counters_expected"],
              "limitations": ["수동 합성 의미 기대 판정", "실제 모델/외부 API/검산/제품 승인 미실행",
                              "후보 수용은 사람 승인이나 모델 오류가 아님", "최소 어휘 보완은 제품 구현/완성된 의미 검증 설계가 아님"]}
    report_hash = write_new(output / "results.json", report)
    write_new(output / "results-sha256.json", {"recorded_at_kst": now(), "contributor_version": VERSION,
              "results_sha256": report_hash, "_change_note": "실제 결과 JSON 바이트의 지문 보존."})
    return {"action": "EXECUTED_PURE_SYNTHETIC_PROBES", "summary": summary, "results_sha256": report_hash}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seal", "run"))
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    output = Path(__file__).resolve().parent
    print(json.dumps(seal(args.repo, output) if args.action == "seal" else run(args.repo, output), ensure_ascii=False))


if __name__ == "__main__":
    main()

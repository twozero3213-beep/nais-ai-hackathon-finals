"""case64 synthetic regressions: no scientific or human approval is manufactured."""
from types import SimpleNamespace

import pandas as pd
import pytest

from core.executor import execute_contract
from core.gates import interpretation_gate, inferential_reproduction_gate
from core.models import Claim, Status
from core.statistics import inferential
from core.typed_contracts import ContractType, DescriptiveContract, ScopeContract
from core.verifier import verify


# [수정: 전문가5/6] 2026-09-26 case64
# 무엇·왜: 합성 계약 공통 인수 재사용 / 입력·출력: 유형 -> 테스트용 계약 인수 / 검증: 아래 실행시험.
def common(kind):
    return dict(claim_id="synthetic", contract_type=kind, source_page=1,
                source_quote="synthetic", dataset_name="synthetic.csv",
                dataset_hash="synthetic", human_confirmed=True)


# [수정: 전문가5/6] 2026-09-26 case64
# 원인: 정규 임계값 사용 / 무엇·왜: n=4 OLS의 t 구간 고정 검증.
# 입력·출력: 네 관측 -> df=2 신뢰구간 / 검증: 수정 전 FAIL.
def test_ols_small_sample_t_interval():
    result = inferential(pd.DataFrame({"x": [1, 2, 3, 4], "y": [1, 3, 2, 5]}),
                         "linear_regression", "y", x_col="x")
    assert result["ci95"] == pytest.approx((-1.1357239405752972, 3.3357239405752974))
    assert result["df"] == 2


# [수정: 전문가5/6] 2026-09-26 case64
# 무엇·왜: 부정 부분문자열 오판 검출 / 입력·출력: 한·영 긍정/부정×p -> FAIL/REVIEW / 검증: 8조합.
@pytest.mark.parametrize("text", ["The difference was significant.", "유의한 차이",
                                  "The difference was not significant.", "유의하지 않은 차이"])
@pytest.mark.parametrize("p", [.01, .2])
def test_interpretation_negation_first(text, p):
    negative = "not significant" in text or "유의하지" in text
    mismatch = (p < .05) == negative
    assert interpretation_gate(SimpleNamespace(text=text, alpha=.05), {"p_value": p}).status == (
        "FAIL" if mismatch else "REVIEW")


# [수정: 전문가5/6] 2026-09-26 case64
# 무엇·왜: 여러 결론 혼재를 단일 p로 단정하지 않음 / 입력·출력: 긍정·부정 혼합 -> REVIEW / 검증: 양쪽 p.
@pytest.mark.parametrize("p", [.01, .2])
def test_interpretation_mixed_assertions_require_review(p):
    claim = SimpleNamespace(text="A was significant; B was not significant.", alpha=.05)
    assert interpretation_gate(claim, {"p_value": p}).status == "REVIEW"


# [수정: 전문가5/6] 2026-09-26 case64
# 무엇·왜: 비교 연산자 누락 PASS 방지 / 입력·출력: 경계와 방향별 p -> 판정 / 검증: 13조합.
@pytest.mark.parametrize("op,actual,expected", [
    ("=", .05, "PASS"), ("=", .2, "FAIL"),
    ("<", .01, "PASS"), ("<", .05, "FAIL"),
    (">", .001, "FAIL"), (">", .2, "PASS"), (">", .05, "FAIL"),
    ("<=", .05, "PASS"), ("<=", .2, "FAIL"),
    (">=", .05, "PASS"), (">=", .01, "FAIL"),
    ("", .05, "REVIEW"), ("!=", .05, "REVIEW")])
def test_p_operators(op, actual, expected):
    claim = SimpleNamespace(reported_p_value=.05, reported_p_operator=op)
    assert inferential_reproduction_gate(claim, {"p_value": actual}).status == expected


# [수정: 전문가5/6] 2026-09-26 case64
# 무엇·왜: 잘못된 확률의 수치 일치 방지 / 입력·출력: 비유한·범위밖·bool p -> REVIEW / 검증: 6조합.
@pytest.mark.parametrize("reported,actual", [(-.1, .05), (.05, 1.1), (float("inf"), .1),
                                            (.1, float("nan")), (True, 1), (.05, False)])
def test_invalid_probabilities_rejected(reported, actual):
    claim = SimpleNamespace(reported_p_value=reported, reported_p_operator="=")
    assert inferential_reproduction_gate(claim, {"p_value": actual}).status == "REVIEW"


# [수정: 전문가5/6] 2026-09-26 case64
# 무엇·왜: 해석 게이트 확률 경계 점검 / 입력·출력: 잘못된 p/α -> REVIEW / 검증: 6조합.
@pytest.mark.parametrize("p,alpha", [(True, .05), (.01, False), (-.1, .05),
                                     (.1, float("nan")), (.1, 1.1), (.1, 0)])
def test_interpretation_invalid_probability_is_review(p, alpha):
    assert interpretation_gate(SimpleNamespace(text="significant", alpha=alpha),
                               {"p_value": p}).status == "REVIEW"


# [수정: 전문가5/6] 2026-09-26 case64
# 무엇·왜: 없는 시점열·차원열·빈표의 거짓 coverage 차단 / 입력·출력: 구조 부족 자료 -> BLOCKED / 검증: 3조합.
@pytest.mark.parametrize("frame", [
    pd.DataFrame({"g": ["A", "B"], "y": [1, 2]}),
    pd.DataFrame({"g": [], "y": [], "timepoint": []}),
    pd.DataFrame({"y": [1], "timepoint": ["baseline"]})])
def test_scope_missing_structure_blocks(frame):
    contract = ScopeContract(**common(ContractType.SCOPE), endpoint="y",
                             subgroup_dimensions=["g"], timepoints=["baseline", "week12"])
    assert execute_contract(contract, frame)["state"] == "BLOCKED"


# [수정: 전문가5/6] 2026-09-26 case64
# 무엇·왜: 요구 시점 누락을 실제 셀로 기록 / 입력·출력: baseline만 관측 -> 2/4 불완전 / 검증: week12 missing.
def test_scope_unobserved_timepoint_is_missing():
    contract = ScopeContract(**common(ContractType.SCOPE), endpoint="y",
                             subgroup_dimensions=["g"], timepoints=["baseline", "week12"])
    result = execute_contract(contract, pd.DataFrame(
        {"g": ["A", "B"], "y": [1, 2], "timepoint": ["baseline", "baseline"]}))["result"]
    assert result["coverage_complete"] is False
    assert result["observed_cells"] == 2
    assert result["required_cells"] == 4
    assert {cell["timepoint"] for cell in result["missing_cells"]} == {"week12"}


# [수정: 전문가5/6] 2026-09-26 case64
# 무엇·왜: overflow·표본부족·무한대의 거짓 실행 방지 / 입력·출력: 비정상자료 -> BLOCKED/REVIEW / 검증: 두 실행경로 4조합.
@pytest.mark.parametrize("method,values", [("sum", [1e308, 1e308]), ("std", [1.0]),
                                         ("mean", [1, float("inf")]),
                                         ("min", [1, float("inf")])])
def test_descriptive_invalid_computation_fails_closed_in_both_paths(method, values):
    frame = pd.DataFrame({"x": values})
    contract = DescriptiveContract(**common(ContractType.DESCRIPTIVE),
                                   variable="x", aggregation=method)
    run = execute_contract(contract, frame)
    assert run["state"] == "BLOCKED"
    assert run["result"] is None
    claim = Claim("synthetic", "synthetic", column="x", aggregation=method,
                  original_value=1, semantic_confirmed=True)
    status, _, result = verify(claim, frame)
    assert status == Status.REVIEW
    assert result is None


# [수정: 전문가5/6] 2026-09-26 case64
# 무엇·왜: 가중치 합 overflow가 유한한 오답 0을 만드는 반례 / 입력·출력: 같은 값·거대 가중치 -> 0.1 / 검증: 두 실행경로 및 보고 0 충돌.
def test_weighted_mean_overflow_is_stable_in_both_paths():
    frame = pd.DataFrame({"x": [.1, .1], "w": [1e308, 1e308]})
    contract = DescriptiveContract(**common(ContractType.DESCRIPTIVE),
                                   variable="x", aggregation="weighted_mean", weight_column="w")
    run = execute_contract(contract, frame)
    assert run["state"] == "EXECUTED"
    assert run["result"]["value"] == pytest.approx(.1)
    claim = Claim("synthetic", "synthetic", column="x", aggregation="weighted_mean",
                  weight_column="w", original_value=0, tolerance=0, semantic_confirmed=True)
    status, _, result = verify(claim, frame)
    assert status == Status.CONFLICT
    assert result == pytest.approx(.1)


# [수정: 전문가5/6] 2026-09-26 case64
# 무엇·왜: no significant와 insignificant 부정 누락 재현 / 입력·출력: 부정 문장×p -> REVIEW/FAIL / 검증: 4조합.
@pytest.mark.parametrize("text", ["There was no significant difference.",
                                  "The difference was statistically insignificant."])
@pytest.mark.parametrize("p,expected", [(.2, "REVIEW"), (.01, "FAIL")])
def test_additional_negative_significance_phrases(text, p, expected):
    claim = SimpleNamespace(text=text, alpha=.05)
    assert interpretation_gate(claim, {"p_value": p}).status == expected

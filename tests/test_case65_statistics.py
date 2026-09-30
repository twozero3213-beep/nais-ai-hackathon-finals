"""Synthetic row-accounting invariants; these do not replace human review."""
import pandas as pd
import pytest

from core.executor import execute_contract
from core.analysis_spec import AnalysisSpecification
from core.typed_contracts import (
    AssociationContract, ComparativeContract, ContractType,
)


# [수정: 전문가5/6] 2026-09-26 case65
# 원인·무엇·왜: 실행 경로의 행수 검증에 합성 계약 인수 재사용.
# 입력·출력: 계약 유형 -> 합성 시험 인수 / 검증: 아래 비교·상관 메타모픽 시험.
# [수정: 0 이영] 2026-09-30 23:35 KST — 행수 시험의 합성 명세 확인을 명시하고 Welch 분산을 선택 방법에 맞춘다. 제품 확인 guard는 유지한다.
def synthetic_contract_fields(kind, method):
    return dict(claim_id="synthetic", contract_type=kind, source_page=1,
                source_quote="synthetic row accounting", dataset_name="synthetic.csv",
                dataset_hash="synthetic", human_confirmed=True,
                missing_policy="complete_case",
                analysis_spec=AnalysisSpecification(
                    population="synthetic selected rows", estimand="synthetic method estimate",
                    missing_policy="complete_case",
                    variance_estimator="welch" if method == "welch_t" else "classical",
                    multiplicity_policy="none_reported", human_confirmed=True).to_dict())


# [수정: 전문가5/6] 2026-09-26 case65
# 원인: 연속형 비교 rows_used가 범위밖·결측행도 포함 / 무엇·왜: 계산 불변인 행 추가 후 사용행수 불변 검증.
# 입력·출력: A/B 각 3개 + 선택밖 C·결측 A/B -> 항상 6행 / 검증: 세 비교방법×세 추가자료.
@pytest.mark.parametrize("method", ["independent_t", "welch_t", "mannwhitney_u"])
@pytest.mark.parametrize("extra", [
    pd.DataFrame({"g": ["C", "C"], "y": [100., 200.]}),
    pd.DataFrame({"g": ["A", "B"], "y": [float("nan"), float("nan")]}),
    pd.DataFrame({"g": ["A", "B"], "y": ["unparseable", "missing"]}),
])
def test_comparison_unused_rows_do_not_change_rows_used(method, extra):
    frame = pd.DataFrame({"g": ["A"] * 3 + ["B"] * 3,
                          "y": [1., 2., 4., 2., 4., 7.]})
    contract = ComparativeContract(
        **synthetic_contract_fields(ContractType.COMPARATIVE, method),
        method=method, outcome="y", group_column="g", group_a="A", group_b="B")
    baseline = execute_contract(contract, frame)
    augmented = execute_contract(contract, pd.concat([frame, extra], ignore_index=True))
    assert baseline["state"] == augmented["state"] == "EXECUTED"
    assert augmented["result"]["estimate"] == pytest.approx(baseline["result"]["estimate"])
    assert augmented["result"]["p_value"] == pytest.approx(baseline["result"]["p_value"])
    assert baseline["rows_used"] == 6
    assert augmented["rows_used"] == 6
    assert augmented["rows_used"] == augmented["result"]["n_a"] + augmented["result"]["n_b"]


# [수정: 전문가5/6] 2026-09-26 case65
# 원인: 상관 rows_used가 complete-case 탈락행 포함 / 무엇·왜: 불완전 관측쌍을 사용했다고 기록하지 않음.
# 입력·출력: 완전한 4쌍 + 불완전한 3쌍 -> 항상 4행 / 검증: Pearson·Spearman의 추정량/p/행수 불변.
@pytest.mark.parametrize("method", ["pearson_r", "spearman_r"])
def test_association_incomplete_pairs_do_not_change_rows_used(method):
    frame = pd.DataFrame({"x": [1., 2., 3., 4.], "y": [1., 3., 2., 5.]})
    extra = pd.DataFrame({"x": [None, 9., "unparseable"], "y": [9., None, 9.]})
    contract = AssociationContract(
        **synthetic_contract_fields(ContractType.ASSOCIATION, method),
        method=method, x="x", y="y")
    baseline = execute_contract(contract, frame)
    augmented = execute_contract(contract, pd.concat([frame, extra], ignore_index=True))
    assert baseline["state"] == augmented["state"] == "EXECUTED"
    assert augmented["result"]["estimate"] == pytest.approx(baseline["result"]["estimate"])
    assert augmented["result"]["p_value"] == pytest.approx(baseline["result"]["p_value"])
    assert baseline["rows_used"] == 4
    assert augmented["rows_used"] == 4
    assert augmented["rows_used"] == augmented["result"]["n"]

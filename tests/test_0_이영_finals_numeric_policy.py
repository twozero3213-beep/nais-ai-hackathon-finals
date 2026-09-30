# [수정: 0 이영 · Codex] 2026-10-01T07:48:45+09:00 — 실제 연결의 키 numeric_policy로 시험 표기만 정렬. 첫 4 KeyError 원로그 보존; 수치 판정 기대값 무수정.
# [작성: 0 이영 · Codex · 버전 0] 2026-10-01T07:45:49+09:00 — 실제 finals 계산이 공통 수치 정책과 정수 mean 정밀도 관문을 사용하는지 검증한다.
# 공개 합성 DataFrame으로 실제 _calculate만 호출한다. 원문/최종 승인/모델을 mock하거나 실행하지 않는다.
from decimal import Decimal
import math
from pathlib import Path
import sys

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for path in (REPO, REPO / "finals"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from core.numeric_comparison import NumericComparisonError, POLICY
from finals_pipeline import _calculate


def calculate(values, reported, tolerance):
    case = {"dataframe": pd.DataFrame({"age": values})}
    proposal = {
        "method": "mean", "column": "age", "filters": [],
        "denominator": {"rule": "all_rows", "expected_n": len(values)},
        "missing_policy": "error", "unit": "years",
        "reported_value": reported, "tolerance": tolerance,
    }
    return _calculate(case, proposal)


def test_decimal_boundary_matches_without_fixed_epsilon():
    result = calculate([0.8], 0.7, 0.1)
    assert result["within_tolerance"] is True
    assert result["delta"] == 0.1
    assert Decimal(result["delta_decimal"]) == Decimal("0.1")
    assert result["numeric_policy"] == POLICY
    assert result["denominator_matches"] is True


@pytest.mark.parametrize("tolerance", [0, 1e-13])
def test_declared_small_tolerance_is_not_widened(tolerance):
    result = calculate([5e-13], 0, tolerance)
    assert result["within_tolerance"] is False
    assert result["delta"] == 5e-13
    assert Decimal(result["delta_decimal"]) == Decimal("5e-13")
    assert result["numeric_policy"] == POLICY
    assert result["denominator_matches"] is True


def test_integer_mean_rounding_is_explicitly_unsupported():
    with pytest.raises(NumericComparisonError, match="INTEGER_MEAN_PRECISION_UNSUPPORTED"):
        calculate([2**53, 2**53 + 2], 2**53 + 1, 0)


def test_integer_valued_float_preserves_actual_nextafter_distance():
    result = calculate([math.nextafter(1e20, math.inf)], 1e20, 16384)
    assert result["within_tolerance"] is True
    assert result["delta"] == 16384
    assert Decimal(result["delta_decimal"]) == Decimal(16384)
    assert result["numeric_policy"] == POLICY
    assert result["denominator_matches"] is True

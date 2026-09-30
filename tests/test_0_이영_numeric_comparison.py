# [작성: 0 이영 · Codex · 버전 0] 2026-10-01T06:07:34+09:00 — 실제 N08/N10 반례와 정상 오차 경계·numpy 값·정밀도 보류 정책을 검증한다.
from decimal import Decimal, localcontext
import math

import numpy as np
import pandas as pd
import pytest

from core.models import Claim, Status
from core.numeric_comparison import (
    NumericComparisonError, POLICY, compare_numeric, require_integer_mean_precision,
)
from core.verifier import verify


@pytest.mark.parametrize("actual,reported,tolerance,within", [
    (0.8,0.7,0.1,True), (0.7,0.8,0.1,True),
    (5e-13,0,0,False), (5e-13,0,1e-13,False),
    (0,0,0,True), (15,15,0,True),
    (np.float64(0.8),np.float64(0.7),np.float64(0.1),True),
    (np.int64(15),np.int64(15),np.int64(0),True),
    (9007199254740992.0,9007199254740993,0,False),
    (math.nextafter(1e20,math.inf),1e20,16384,True),
])
def test_declared_tolerance_and_numeric_representation(actual,reported,tolerance,within):
    result=compare_numeric(actual,reported,tolerance)
    assert result.within_tolerance is within
    assert result.policy==POLICY
    assert math.isfinite(result.delta)


def test_large_integer_delta_is_one_instead_of_float_subtraction_zero():
    result=compare_numeric(9007199254740992.0,9007199254740993,0)
    assert result.delta==1
    assert result.delta_decimal=="1"
    assert not result.within_tolerance


def test_integer_valued_float_keeps_actual_value_not_short_decimal_text():
    result=compare_numeric(math.nextafter(1e20,math.inf),1e20,16384)
    assert result.delta==16384
    assert result.delta_decimal=="16384"
    assert result.within_tolerance


@pytest.mark.parametrize("position,value", [
    (0,True),(1,False),(2,True),(0,np.bool_(True)),
    (0,math.nan),(1,math.inf),(2,-math.inf),(2,-1),
    (0,Decimal('NaN')),(1,Decimal('Infinity')),(0,'0.8'),
])
def test_invalid_numeric_operands_fail_without_echo(position,value):
    args=[0.8,0.7,0.1]
    args[position]=value
    with pytest.raises(NumericComparisonError) as error:
        compare_numeric(*args)
    assert str(error.value) in {"NUMERIC_INPUT_INVALID","NUMERIC_TOLERANCE_INVALID"}


def test_decimal_context_does_not_round_an_above_boundary_difference_to_match():
    # Both inputs are exact public Decimal representations. 10^40 - (-10^-40)
    # exceeds 10^40, but a context with prec=28 could round the difference to 10^40.
    with localcontext() as context:
        context.prec=2
        # [수정: 0 이영 · Codex] 2026-10-01T07:42:40+09:00 — 최초35PASS/1FAIL의 예외 기대를 교정: float(1e40)는 정수값이 경계보다 커서 불일치 결정을 보존한다. 핵심 기대인 거짓 일치 금지는 유지한다.
        result=compare_numeric(Decimal('1e40'),Decimal('-1e-40'),Decimal('1e40'))
        assert not result.within_tolerance
        assert Decimal(result.delta_decimal)>Decimal('1e40')
        assert compare_numeric(Decimal('0.8'),Decimal('0.7'),Decimal('0.1')).within_tolerance


def test_finite_operands_with_unrepresentable_delta_fail_closed():
    with pytest.raises(NumericComparisonError,match="NUMERIC_PRECISION_UNSUPPORTED"):
        compare_numeric(1e308,-1e308,0)


@pytest.mark.parametrize("reported", [9007199254740993,9007199254740992])
def test_large_integer_mean_is_review_even_if_reported_value_is_rounded(reported):
    frame=pd.DataFrame({'y':[9007199254740992,9007199254740994]})
    claim=Claim('large','synthetic integer mean',original_value=reported,column='y',
                aggregation='mean',tolerance=0,semantic_confirmed=True)
    status,reason,value=verify(claim,frame)
    assert status==Status.REVIEW
    assert "INTEGER_MEAN_PRECISION_UNSUPPORTED" in reason
    assert value is None


def test_zero_tolerance_fractional_integer_mean_is_explicitly_unsupported():
    with pytest.raises(NumericComparisonError,match="INTEGER_MEAN_PRECISION_UNSUPPORTED"):
        require_integer_mean_precision([1,2,2],5/3,0)
    require_integer_mean_precision([np.int64(1),np.int64(2),np.int64(2)],5/3,1e-14)


@pytest.mark.parametrize("values,reported,tolerance,status", [
    ([0.8],0.7,0.1,Status.SUPPORTED),
    ([10,20],15,0,Status.SUPPORTED),
    ([5e-13],0,0,Status.CONFLICT),
    ([5e-13],0,1e-13,Status.CONFLICT),
    ([1,2,2],5/3,0,Status.REVIEW),
    ([1,2,2],5/3,1e-14,Status.SUPPORTED),
])
def test_core_verifier_uses_common_policy(values,reported,tolerance,status):
    claim=Claim('policy','synthetic mean',original_value=reported,column='y',
                aggregation='mean',tolerance=tolerance,semantic_confirmed=True)
    result=verify(claim,pd.DataFrame({'y':values}))
    assert result[0]==status
    if status==Status.REVIEW:
        assert result[2] is None


def test_row_count_exact_zero_tolerance_remains_supported():
    claim=Claim('rows','synthetic rows',original_value=2,column='__dataset__',
                aggregation='row_count',tolerance=0,semantic_confirmed=True)
    assert verify(claim,pd.DataFrame({'y':[10,20]}))[0]==Status.SUPPORTED


def test_unconfirmed_mean_is_not_promoted_by_numeric_comparison():
    claim=Claim('review','synthetic mean',original_value=15,column='y',
                aggregation='mean',tolerance=0,semantic_confirmed=False)
    assert verify(claim,pd.DataFrame({'y':[10,20]}))[0]==Status.REVIEW

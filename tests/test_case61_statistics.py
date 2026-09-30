"""case61 deterministic safety checks; synthetic data, not human/AI benchmarks."""
import math
import warnings

import pandas as pd
import pytest

from core.executor import execute_contract
from core.statistics import logistic_regression, multivariable_regression
from core.typed_contracts import ContractType, RegressionContract
from core.analysis_spec import AnalysisSpecification


# [수정: 0 이영] 2026-09-30 23:35 KST — 합성 수치 시험에 확인된 분석명세를 명시한다. 명세 생략 차단은 제품에서 그대로 유지한다.
def confirmed_synthetic_spec():
    return AnalysisSpecification(
        population="synthetic observations", estimand="synthetic method estimate",
        missing_policy="complete_case", variance_estimator="classical",
        multiplicity_policy="none_reported", human_confirmed=True).to_dict()


# [작성/수정: 전문가5·6] 2026-09-26 case61
# 무엇을: 완전분리 실제 fit의 비수렴 실행 차단 / 왜: 유한 p·계수라도 추론 완료가 아님.
# 입력·출력: 단일/다중 설명변수 합성 이진 데이터 -> BLOCKED, 결과 없음.
# 검증: statsmodels 실제 최적화의 converged=False와 유한 주요 값 확인 후 canonical 실행 비교.
@pytest.mark.parametrize('predictors', [['x'], ['x', 'z']])
def test_nonconverged_logistic_fit_is_not_executed(predictors):
    df = pd.DataFrame({'x': [-3, -2, -1, 1, 2, 3], 'z': [0, 1, 0, 1, 0, 1],
                       'y': [0, 0, 0, 1, 1, 1]})
    contract = RegressionContract(
        claim_id='separated', contract_type=ContractType.REGRESSION,
        source_page=1, source_quote='Synthetic logistic regression',
        dataset_name='synthetic.csv', dataset_hash='synthetic', human_confirmed=True,
        method='logistic_regression', missing_policy='complete_case',
        # [수정: 0 이영] 2026-09-30 23:35 KST — 기존 x항 수치와 비교하는 시험이므로 다중 모형에서도 검산 대상 x를 지정한다.
        outcome='y', predictors=predictors, target_predictor='x',
        analysis_spec=confirmed_synthetic_spec())
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        raw = (logistic_regression(df, 'y', 'x') if len(predictors) == 1
               else multivariable_regression(df, 'y', predictors, 'logistic_regression'))
        term = raw if len(predictors) == 1 else raw['terms']['x']
        assert raw['converged'] is False
        assert all(math.isfinite(term[key]) for key in ('estimate', 'p_value', 'odds_ratio'))
        run = execute_contract(contract, df)
    assert run['state'] == 'BLOCKED'
    assert run['result'] is None
    assert '수렴' in run['reason']

# [작성/수정: 전문가5·6] 2026-09-26 case61
# 무엇을: 수렴한 단일/다중 회귀 정상 경로 보존 / 왜: 안전 가드가 모든 회귀를 차단하면 안 됨.
# 입력·출력: 비분리 합성 데이터 -> EXECUTED와 원래 추정량·p 유지.
# 검증: 동일 입력의 statistics 반환값을 canonical executor와 비교.
@pytest.mark.parametrize('predictors', [['x'], ['x', 'z']])
def test_converged_logistic_fit_keeps_original_result(predictors):
    df = pd.DataFrame({'y': [0, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 1],
                       'x': [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5],
                       'z': [0, 0, 1, 1] * 4})
    contract = RegressionContract(
        claim_id='converged', contract_type=ContractType.REGRESSION,
        source_page=1, source_quote='Synthetic logistic regression',
        dataset_name='synthetic.csv', dataset_hash='synthetic', human_confirmed=True,
        method='logistic_regression', missing_policy='complete_case',
        # [수정: 0 이영] 2026-09-30 23:35 KST — 기존 x항 수치와 비교하는 시험이므로 다중 모형에서도 검산 대상 x를 지정한다.
        outcome='y', predictors=predictors, target_predictor='x',
        analysis_spec=confirmed_synthetic_spec())
    raw = (logistic_regression(df, 'y', 'x') if len(predictors) == 1
           else multivariable_regression(df, 'y', predictors, 'logistic_regression'))
    term = raw if len(predictors) == 1 else raw['terms']['x']
    assert raw['converged'] is True
    run = execute_contract(contract, df)
    assert run['state'] == 'EXECUTED'
    assert run['result']['estimate'] == pytest.approx(term['estimate'])
    assert run['result']['p_value'] == pytest.approx(term['p_value'])

# [작성/수정: 전문가5·6] 2026-09-26 case61
# 무엇을: A/B 이진 빈도표와 선택 밖 C 집단 재현 / 왜: 검정 모집단 변경을 수치로 검출.
# 입력·출력: include_c -> A=(10,10), B=(5,15), 선택적 C=(20,0) 표.
# 검증: 아래 p=.191418 및 선택 표본수 40의 고정 기대값.
def categorical_frame(include_c=True):
    return pd.DataFrame({'group': ['A'] * 20 + ['B'] * 20 + (['C'] * 20 if include_c else []),
                         'outcome': [0] * 10 + [1] * 10 + [0] * 5 + [1] * 15 + ([0] * 20 if include_c else [])})


# [작성/수정: 전문가5·6] 2026-09-26 case61
# 무엇을: 카이제곱의 정상 estimate=None 허용 / 왜: p와 통계량이 유효한 검정을 잘못 차단하지 않음.
# 입력·출력: A/B 빈도표 계약 -> EXECUTED, p=.19141842523760735.
# 검증: 2x2 Yates 보정 통계량 1.7066666666666668의 고정 기대값.
def test_chi_square_no_effect_estimate_is_valid():
    from core.typed_contracts import ComparativeContract
    contract = ComparativeContract(
        claim_id='chi', contract_type=ContractType.COMPARATIVE, source_page=1,
        source_quote='Synthetic A/B chi square', dataset_name='synthetic.csv', dataset_hash='synthetic',
        human_confirmed=True, method='chi_square', missing_policy='complete_case',
        outcome='outcome', group_column='group', group_a='A', group_b='B',
        analysis_spec=confirmed_synthetic_spec())
    run = execute_contract(contract, categorical_frame(False))
    assert run['state'] == 'EXECUTED'
    assert run['result']['estimate'] is None
    assert run['result']['statistic'] == pytest.approx(1.7066666666666668)
    assert run['result']['p_value'] == pytest.approx(.19141842523760735)


# [작성/수정: 전문가5·6] 2026-09-26 case61
# 무엇을: 범주검정의 A/B 명시 선택 보존 / 왜: C를 추가해 유의성 판정이 뒤집히면 안 됨.
# 입력·출력: A/B/C에서 A/B chi-square·Fisher -> n=40, 원래 A/B 결과.
# 검증: 범위 밖 C 포함 시 수정 전 chi p 약 .000006, Fisher는 3x2 예외.
@pytest.mark.parametrize('method,expected_p', [('chi_square', .19141842523760735), ('fisher_exact', .1907925723276113)])
def test_categorical_comparison_excludes_unselected_groups(method, expected_p):
    from core.statistics import inferential
    from core.typed_contracts import ComparativeContract
    df = categorical_frame()
    result = inferential(df, method, 'outcome', 'group', 'A', 'B')
    assert result['n'] == 40
    assert result['p_value'] == pytest.approx(expected_p)
    contract = ComparativeContract(
        claim_id='groups', contract_type=ContractType.COMPARATIVE, source_page=1,
        source_quote='Synthetic A/B comparison', dataset_name='synthetic.csv', dataset_hash='synthetic',
        human_confirmed=True, method=method, missing_policy='complete_case',
        outcome='outcome', group_column='group', group_a='A', group_b='B',
        analysis_spec=confirmed_synthetic_spec())
    run = execute_contract(contract, df)
    assert run['state'] == 'EXECUTED'
    assert run['rows_used'] == 40
    assert run['result']['p_value'] == pytest.approx(expected_p)

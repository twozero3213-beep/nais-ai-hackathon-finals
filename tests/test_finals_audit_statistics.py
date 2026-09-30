"""Synthetic audit regressions; no paper, network, credentials or approval."""
# [작성: 0 이영 · Codex] 2026-09-30T22:41:31+09:00 — C04~C08 실제 반례의 계산·차단·원문정밀도 회귀를 고정한다.
from types import SimpleNamespace
import pandas as pd
import pytest
from core.statistics import inferential, logistic_regression, multivariable_regression
from core.gates import inferential_reproduction_gate
from core.pdf_claims import extract_numeric_claims

@pytest.mark.parametrize('method', ['chi_square', 'fisher_exact'])
def test_selected_group_aliases_do_not_split_contingency_table(method):
    mixed = pd.DataFrame({'g': ['A']*4 + [' a ']*4 + ['A']*2 + ['B']*10,
                          'y': [1]*8 + [0]*2 + [1]*2 + [0]*8})
    canonical = mixed.assign(g=mixed.g.str.strip().str.upper())
    original = mixed.copy(deep=True)
    result = inferential(mixed, method, 'y', group_col='g', group_a='A', group_b='B')
    expected = inferential(canonical, method, 'y', group_col='g', group_a='A', group_b='B')
    assert result['statistic'] == pytest.approx(expected['statistic'])
    assert result['p_value'] == pytest.approx(expected['p_value'])
    if method == 'chi_square': assert result['df'] == expected['df'] == 1
    pd.testing.assert_frame_equal(mixed, original)

@pytest.mark.parametrize('method', ['spearman_r', 'wilcoxon_signed'])
def test_nonfinite_numeric_observations_are_rejected(method):
    frame = pd.DataFrame({'x':[1, 2, 3, float('inf')], 'y':[1, 2, 3, 4]})
    with pytest.raises(ValueError, match='유한|무한'):
        inferential(frame, method, 'y', x_col='x')

@pytest.mark.parametrize('runner', ['logistic', 'multi'])
def test_direct_regression_helpers_reject_infinity_before_fit(runner):
    frame = pd.DataFrame({'x':[1, 2, 3, float('inf')], 'y':[0, 1, 0, 1]})
    with pytest.raises(ValueError, match='유한|무한'):
        if runner == 'logistic': logistic_regression(frame, 'y', 'x')
        else: multivariable_regression(frame, 'y', ['x'])

def test_ci_mismatch_is_not_hidden_by_matching_effect_and_p():
    claim = SimpleNamespace(reported_effect=.5, effect_kind='correlation_r',
                            reported_p_value=.01, reported_p_operator='=', reported_ci95=(-100, -90))
    gate = inferential_reproduction_gate(claim, {'estimate':.5, 'p_value':.01, 'ci95':(.4, .6)})
    assert gate.status == 'FAIL'

@pytest.mark.parametrize('reported,computed,expected', [
    ((.4,.6),(.4,.6),'PASS'), ((.4,.6),None,'REVIEW'),
    ((.6,.4),(.4,.6),'REVIEW'), ((True,.6),(.4,.6),'REVIEW')])
def test_ci_only_targets_require_valid_matching_intervals(reported, computed, expected):
    claim=SimpleNamespace(reported_ci95=reported)
    assert inferential_reproduction_gate(claim, {'ci95':computed}).status == expected

def test_odds_ratio_ci_uses_odds_ratio_scale():
    claim=SimpleNamespace(reported_ci95=(1.2,2.4), effect_kind='odds_ratio')
    assert inferential_reproduction_gate(claim, {'ci95_or':(1.2,2.4), 'ci95_beta':(.18,.88)}).status == 'PASS'

# [작성: 0 이영 · Codex] 2026-09-30T22:59:03+09:00 — CI 출력 자릿수의 내부·경계·외부 판정을 함께 고정한다.
@pytest.mark.parametrize('computed,status', [((.402,.598),'PASS'),((.405,.595),'PASS'),((.406,.594),'FAIL')])
def test_reported_ci_printed_precision_is_respected(computed,status):
    claim=SimpleNamespace(text='Estimate: 95% CI [0.40, 0.60].', reported_ci95=(.4,.6))
    assert inferential_reproduction_gate(claim, {'ci95':computed}).status == status

def test_unknown_or_unsupported_ci_level_is_reviewed():
    for text in ['Effect 99% CI [0.2, 0.8], p=.01.', 'Effect CI [0.2, 0.8], p=.01.']:
        claim=SimpleNamespace(text=text, reported_p_value=.01, reported_p_operator='=')
        assert inferential_reproduction_gate(claim, {'p_value':.01}).status == 'REVIEW'

def test_tiny_reported_p_cannot_match_nine_hundred_fold_difference():
    claim=SimpleNamespace(text='p=0.001e-3.', reported_p_value=.000001, reported_p_operator='=')
    assert inferential_reproduction_gate(claim, {'p_value':.0009}).status == 'FAIL'

@pytest.mark.parametrize('actual,status', [(.0104,'PASS'),(.0106,'FAIL'),(.0095,'PASS'),(.0105,'PASS')])
def test_p_equality_uses_the_printed_decimal_precision(actual,status):
    claim=SimpleNamespace(text='p=0.010.', reported_p_value=.01, reported_p_operator='=')
    assert inferential_reproduction_gate(claim, {'p_value':actual}).status == status

@pytest.mark.parametrize('text,value,op', [('p=0.001e-3.',1e-6,'='), ('p<=0.05.',.05,'<='),
    ('p>=0.05.',.05,'>='), ('p=1e-6.',1e-6,'='), ('p≤0.05.',.05,'<='), ('p≥0.05.',.05,'>=')])
def test_complete_p_tokens_are_extracted(text,value,op):
    claim=extract_numeric_claims([(1,'Pearson r=0.4, '+text)])[0]
    assert claim['p_value'] == value
    assert claim['p_operator'] == op

@pytest.mark.parametrize('level', [95,99])
def test_ci_level_and_bounds_are_preserved(level):
    claim=extract_numeric_claims([(1,f'Estimate was 0.5, {level}% CI [0.2, 0.8].')])[0]
    assert claim['reported_ci'] == (.2,.8)
    assert claim['confidence_level'] == level
    assert claim['ci95'] == ((.2,.8) if level == 95 else None)

def test_malformed_exponent_is_never_partially_extracted():
    claim=extract_numeric_claims([(1,'Pearson r=0.4, p=0.001e-.')])[0]
    assert claim['p_value'] is None

# [작성: 0 이영 · Codex] 2026-09-30T22:56:50+09:00 — C04/C05: 중복 색인·혼합 숫자표기와 선택 밖 무한대의 모집단 불변성을 확인한다.
@pytest.mark.parametrize('method', ['chi_square','fisher_exact'])
def test_group_aliases_with_duplicate_index_and_numeric_encodings(method):
    frame=pd.DataFrame({'g':[1, '1.0', 1, 2, '2.0', 2], 'y':[1,1,0,1,0,0]},index=[0]*6)
    canonical=frame.assign(g=[1,1,1,2,2,2])
    actual=inferential(frame,method,'y',group_col='g',group_a=1,group_b=2)
    expected=inferential(canonical,method,'y',group_col='g',group_a=1,group_b=2)
    assert actual['p_value']==pytest.approx(expected['p_value'])
    assert actual['statistic']==pytest.approx(expected['statistic'])


def test_unselected_infinity_does_not_change_comparison_population():
    frame=pd.DataFrame({'g':['A']*3+['B']*3,'y':[1,2,4,2,4,7]})
    extra=pd.DataFrame({'g':['C'],'y':[float('inf')]})
    expected=inferential(frame,'welch_t','y',group_col='g',group_a='A',group_b='B')
    actual=inferential(pd.concat([frame,extra]),'welch_t','y',group_col='g',group_a='A',group_b='B')
    assert actual['p_value']==pytest.approx(expected['p_value'])
    assert actual['n_a']==actual['n_b']==3

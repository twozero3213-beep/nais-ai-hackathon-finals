"""Regression checks for the isolated finals audit proposal; no API or human approval."""
# [수정: 0 이영] 2026-09-30 22:40 KST — C01/C02/C03/C09의 오계산·명세 우회를 작은 합성 입력으로 재현하고 차단/수치 일치를 검증한다.
from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from core.analysis_spec import AnalysisSpecification, build_analysis_spec
from core.executor import execute_contract
from core.models import Claim, Status
from core.reproducibility import reproduction_key
from core.typed_contracts import (
    ContractType, DescriptiveContract, RegressionContract, build_typed_contract,
)
from core.verifier import verify


def confirmed(method, **fields):
    values = dict(column='y', analysis_method=method, semantic_confirmed=True,
                  method_confirmed=True, missing_policy='complete_case',
                  missing_policy_confirmed=True, analysis_spec_confirmed=True,
                  variance_estimator='classical', multiplicity_policy='none_reported')
    values.update(fields)
    return Claim('AUDIT', 'Synthetic confirmed analysis', **values)


def execute(claim, frame, explicit=False):
    contract = build_typed_contract(claim, 'synthetic.csv', '0' * 64)
    return execute_contract(contract, frame, build_analysis_spec(claim) if explicit else None)


def test_selected_sum_agrees_between_verifier_and_executor():
    frame = pd.DataFrame({'y': [1., 2.]})
    claim = Claim('SUM', 'sum is 3', 3, 'y', semantic_confirmed=True, analysis_method='sum')
    assert verify(claim, frame)[:1] == (Status.SUPPORTED,)
    run = execute(claim, frame)
    assert run['state'] == 'EXECUTED'
    assert run['result']['value'] == 3
    assert run['result']['method'] == 'sum'


def test_unknown_selected_method_never_falls_back_to_mean():
    claim = Claim('UNKNOWN', 'unknown method', column='y', semantic_confirmed=True,
                  analysis_method='unsupported_analysis')
    assert execute(claim, pd.DataFrame({'y': [1., 2.]}))['state'] == 'BLOCKED'


def test_manually_conflicting_descriptive_contract_is_blocked():
    contract = DescriptiveContract('SUM', ContractType.DESCRIPTIVE, 1, 'sum', 'd', 'h',
                                  human_confirmed=True, method='sum', aggregation='mean', variable='y')
    assert execute_contract(contract, pd.DataFrame({'y': [1., 2.]}))['state'] == 'BLOCKED'


@pytest.mark.parametrize('explicit', [False, True])
def test_unconfirmed_inference_is_blocked_before_computation(explicit, monkeypatch):
    claim = confirmed('pearson_r', x_column='x', analysis_spec_confirmed=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('An unconfirmed analysis reached the numeric engine')
    monkeypatch.setattr('core.executor.inferential', forbidden)
    run = execute(claim, pd.DataFrame({'x': [1., 2., 3., 4.], 'y': [2., 3., 5., 7.]}), explicit)
    assert run['state'] == 'BLOCKED'
    assert 'analysis specification confirmation' in run['missing']


@pytest.mark.parametrize('explicit', [False, True])
def test_unsupported_missing_policy_cannot_be_hidden_by_omitting_spec(explicit):
    claim = confirmed('pearson_r', x_column='x', missing_policy='imputation')
    run = execute(claim, pd.DataFrame({'x': [1., 2., 3., 4., None], 'y': [2., 3., 5., 7., 8.]}), explicit)
    assert run['state'] == 'BLOCKED'
    assert 'missing-data policy:imputation' in run['unsupported']


def test_confirmed_embedded_spec_can_execute_without_duplicate_argument():
    frame = pd.DataFrame({'x': [1., 2., 3., 4.], 'y': [2., 3., 5., 7.]})
    run = execute(confirmed('pearson_r', x_column='x'), frame)
    assert run['state'] == 'EXECUTED'
    assert run['result']['p_value'] == pytest.approx(stats.pearsonr(frame.x, frame.y).pvalue)


def test_external_spec_cannot_replace_the_contract_policy():
    claim = confirmed('pearson_r', x_column='x', variance_estimator='HC3')
    contract = build_typed_contract(claim, 'd', 'h')
    alternate = replace(build_analysis_spec(claim), variance_estimator='classical')
    run = execute_contract(contract, pd.DataFrame({'x': [1., 2., 3., 4.], 'y': [2., 3., 5., 7.]}), alternate)
    assert run['state'] == 'BLOCKED'
    assert run['result'] is None


def test_malformed_spec_returns_blocked_without_uncaught_error():
    claim = confirmed('pearson_r', x_column='x')
    run = execute_contract(build_typed_contract(claim, 'd', 'h'),
                           pd.DataFrame({'x': [1., 2., 3.], 'y': [2., 4., 3.]}), object())
    assert run['state'] == 'BLOCKED'
    assert run['result'] is None


@pytest.mark.parametrize('fields', [
    {'analysis_spec_confirmed': False},
    {'missing_policy_confirmed': False},
    {'missing_policy': 'imputation'},
    {'method_confirmed': False, 'method_candidate': 'one_sample_t'},
    {'variance_estimator': 'HC3'},
])
def test_one_sample_t_has_inferential_confirmation_and_policy_gates(fields):
    claim = confirmed('one_sample_t', mu0=1., **fields)
    assert execute(claim, pd.DataFrame({'y': [1., 2., 3., 4., None]}), True)['state'] == 'BLOCKED'


def test_one_sample_t_preserves_reference_and_applies_confirmed_bonferroni():
    frame = pd.DataFrame({'y': [1., 2., 3., 4., None]})
    claim = confirmed('one_sample_t', mu0=1., multiplicity_policy='bonferroni', multiplicity_count=3)
    run = execute(claim, frame)
    raw = stats.ttest_1samp(frame.y.dropna(), 1.).pvalue
    assert run['state'] == 'EXECUTED'
    assert run['result']['estimate'] == 1.5
    assert run['result']['raw_p_value'] == pytest.approx(raw)
    assert run['result']['p_value'] == pytest.approx(raw * 3)
    assert run['result']['multiplicity_count'] == 3


@pytest.mark.parametrize('count', [True, 2.5, 0])
def test_bonferroni_family_size_must_be_confirmed_integer(count):
    claim = confirmed('one_sample_t', mu0=1., multiplicity_policy='bonferroni', multiplicity_count=count)
    assert execute(claim, pd.DataFrame({'y': [1., 2., 3., 4.]}))['state'] == 'BLOCKED'


def test_multivariable_target_is_selected_term_and_survives_predictor_reordering():
    frame = pd.DataFrame({'x': [0., 1., 0., 2., 2., 3., 1., 4.],
                          'z': [0., 0., 1., 1., 3., 2., 4., 3.],
                          'y': [1., 3.1, 10., 14., 32.1, 24.8, 40., 36.1]})
    # [수정: 0 이영] 2026-09-30 22:50 KST — C09: 반환 terms와의 자기 비교 외에 NumPy 독립 최소제곱 계수도 대조한다.
    design = np.column_stack([np.ones(len(frame)), frame.x, frame.z])
    expected_z = np.linalg.lstsq(design, frame.y.to_numpy(), rcond=None)[0][2]
    results = []
    for order in (['x', 'z'], ['z', 'x']):
        claim = confirmed('linear_regression', x_column='z',
                          decomposition={'claim_kind': 'regression', 'predictor_hints': order})
        contract = build_typed_contract(claim, 'd', 'h')
        assert contract.target_predictor == 'z'
        run = execute_contract(contract, frame)
        assert run['state'] == 'EXECUTED', run
        assert run['result']['estimate'] == pytest.approx(run['result']['terms']['z']['estimate'])
        assert run['result']['p_value'] == pytest.approx(run['result']['terms']['z']['p_value'])
        assert run['result']['target_predictor'] == 'z'
        assert run['result']['estimate'] == pytest.approx(expected_z)
        results.append(run['result'])
    assert results[0]['estimate'] == pytest.approx(results[1]['estimate'])
    assert results[0]['p_value'] == pytest.approx(results[1]['p_value'])


def test_multivariable_contract_without_target_is_blocked():
    contract = RegressionContract('R', ContractType.REGRESSION, 1, 'q', 'd', 'h',
        human_confirmed=True, method='linear_regression', missing_policy='complete_case',
        outcome='y', predictors=['x', 'z'],
        analysis_spec=AnalysisSpecification(missing_policy='complete_case', human_confirmed=True).to_dict())
    run = execute_contract(contract, pd.DataFrame({'x': [1., 2., 3.], 'z': [3., 1., 2.], 'y': [2., 4., 3.]}))
    assert run['state'] == 'BLOCKED'
    assert 'regression target predictor' in run['missing']


def test_regression_target_is_bound_to_reproduction_identity():
    values = dict(claim_snapshot={}, analysis_spec_snapshot={}, dataset_hash='h',
                  engine_version='0', runtime_snapshot={})
    a = reproduction_key(contract_snapshot={'predictors': ['x', 'z'], 'target_predictor': 'x'}, **values)
    b = reproduction_key(contract_snapshot={'predictors': ['x', 'z'], 'target_predictor': 'z'}, **values)
    assert a != b


# [수정: 0 이영] 2026-09-30 22:50 KST — 필드형 오류와 대응검정의 정상 확인 경로를 함께 검증한다.
@pytest.mark.parametrize('field,value', [('variance_estimator', []), ('multiplicity_policy', {})])
def test_invalid_spec_field_types_fail_closed(field, value):
    claim = confirmed('pearson_r', x_column='x', **{field: value})
    run = execute(claim, pd.DataFrame({'x': [1., 2., 3., 4.], 'y': [2., 3., 5., 7.]}))
    assert run['state'] == 'BLOCKED'
    assert run['result'] is None


@pytest.mark.parametrize('method', ['paired_t', 'wilcoxon_signed'])
def test_confirmed_paired_methods_remain_executable(method):
    frame = pd.DataFrame({'pre': [1., 2., 3., 4.], 'post': [2., 4., 5., 7.]})
    claim = confirmed(method, column='post', x_column='pre')
    run = execute(claim, frame)
    assert run['state'] == 'EXECUTED'
    assert run['result']['method'] == method


# [수정: 0 이영] 2026-09-30 22:57 KST — C03: 새 보정 지원의 접수·미확인 차단·서명 연결을 함께 검증한다.
@pytest.mark.parametrize('field,value', [
    ('missing_policy', 'imputation'), ('missing_policy_confirmed', False),
    ('analysis_spec_confirmed', False), ('variance_estimator', 'HC3'),
    ('multiplicity_count', 4), ('multiplicity_policy', 'holm'),
])
def test_one_sample_analysis_policy_changes_invalidate_signature(field, value):
    claim = confirmed('one_sample_t', mu0=1., multiplicity_policy='bonferroni', multiplicity_count=3)
    previous = claim.verification_signature()
    setattr(claim, field, value)
    assert claim.verification_signature() != previous


def test_one_sample_bonferroni_proposal_remains_unconfirmed_and_unexecuted():
    from core.proposal_intake import validate_proposal_json
    source = 'Synthetic mean difference from reference 1.'
    original = Claim('PROPOSAL', source, 1., source_page=1, source_quote=source)
    frame = pd.DataFrame({'y': [1., 2., 3., 4.]})
    proposal = {'claim_id': 'PROPOSAL', 'data_fingerprint': '0' * 64,
                'evidence': {'source_page': 1, 'source_quote': source},
                'column': 'y', 'method': 'one_sample_t', 'filters': [],
                'denominator': 'all four observed participants', 'missing_policy': 'complete_case',
                'unit': 'units', 'reported_value': 1., 'tolerance': 0., 'alpha': .05, 'mu0': 1.,
                'analysis_spec': {'population': 'four observed participants',
                                  'estimand': 'mean difference from reference 1',
                                  'variance_estimator': 'classical',
                                  'multiplicity_policy': 'bonferroni', 'multiplicity_count': 3}}
    result = validate_proposal_json(json.dumps(proposal), original, frame, '0' * 64)
    assert result['state'] == 'PROPOSED', result
    assert result['candidate_claim'].semantic_confirmed is False
    assert result['analysis_spec'].human_confirmed is False
    run = execute_contract(result['contract'], frame, result['analysis_spec'])
    assert run['state'] == 'BLOCKED'
    assert run['result'] is None


def test_one_sample_confirmed_holm_uses_the_complete_target_family():
    frame = pd.DataFrame({'y': [1., 2., 3., 4.]})
    raw = float(stats.ttest_1samp(frame.y, 1.).pvalue)
    claim = confirmed('one_sample_t', mu0=1., multiplicity_policy='holm', multiplicity_count=2,
                      multiplicity_p_values=[raw, .5], multiplicity_target_index=0,
                      multiplicity_family_definition='two prespecified synthetic mean tests')
    run = execute(claim, frame)
    assert run['state'] == 'EXECUTED', run
    assert run['result']['raw_p_value'] == pytest.approx(raw)
    assert run['result']['p_value'] == pytest.approx(raw * 2)

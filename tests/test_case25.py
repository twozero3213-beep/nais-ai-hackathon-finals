import pandas as pd
from core.models import Claim
from core.contracts import build_typed_contract,build_analysis_spec,check_analysis_spec,ContractType
from core.executor import execute_contract
from core.benchmark_case25 import score_cases


def regression_claim(**kw):
    c=Claim('case25-C','y associated with x',column='y',analysis_method='linear_regression',x_column='x',semantic_confirmed=True,**kw)
    c.decomposition={'claim_kind':'regression','predictor_hints':['x']}
    return c


def test_analysis_spec_unknown_blocks_case25_executor():
    df=pd.DataFrame({'x':[1,2,3,4],'y':[2,4,6,8]})
    c=regression_claim(missing_policy='complete_case',missing_policy_confirmed=True)
    ct=build_typed_contract(c,'d.csv','hash')
    run=execute_contract(ct,df,build_analysis_spec(c))
    assert run['state']=='BLOCKED'
    assert 'analysis specification confirmation' in run['missing']


def test_confirmed_supported_analysis_spec_executes():
    df=pd.DataFrame({'x':[1,2,3,4,5],'y':[2,4,6,8,10]})
    c=regression_claim(missing_policy='complete_case',missing_policy_confirmed=True,analysis_spec_confirmed=True,analysis_population='reported population',estimand='slope')
    ct=build_typed_contract(c,'d.csv','hash')
    run=execute_contract(ct,df,build_analysis_spec(c))
    assert run['state']=='EXECUTED'


def test_unsupported_missing_policy_fails_closed():
    df=pd.DataFrame({'x':[1,2,3,4],'y':[2,4,6,8]})
    c=regression_claim(missing_policy='multiple_imputation',missing_policy_confirmed=True,analysis_spec_confirmed=True)
    ct=build_typed_contract(c,'d.csv','hash')
    run=execute_contract(ct,df,build_analysis_spec(c))
    assert run['state']=='BLOCKED'
    assert any('multiple_imputation' in x for x in run['unsupported'])


def test_contract_json_contains_analysis_specification():
    c=regression_claim(missing_policy='complete_case',missing_policy_confirmed=True,analysis_spec_confirmed=True,variance_estimator='classical',multiplicity_policy='none_reported')
    d=build_typed_contract(c,'d.csv','hash').to_dict()
    assert d['analysis_spec']['missing_policy']=='complete_case'
    assert d['analysis_spec']['variance_estimator']=='classical'


def test_benchmark_reports_separate_metrics_not_marketing_score():
    m=score_cases([{'claim_found':True,'top1':True,'top3':True,'filter_exact':False,'method_exact':True,'should_block':True,'blocked':True}])
    assert m['claim_recall']==1 and m['filter_exact_accuracy']==0
    assert 'overall_score' not in m

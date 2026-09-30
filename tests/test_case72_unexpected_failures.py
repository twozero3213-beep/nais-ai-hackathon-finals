import math
import pandas as pd
import pytest
from core.models import Claim, Status
from core.typed_contracts import build_typed_contract, route_contract_type, ContractType, check_evidence_sufficiency
from core.executor import execute_contract
from core.statistics import inferential
from core.provenance import evidence_snapshot
from core.diagnostics import comparative_diagnostics
from core.verifier import verify


# [수정: 0 이영] 2026-09-30 23:35 KST — confirmed 합성 fixture가 1표본/대응 추론의 분석명세까지 확인하도록 완결한다. 미확정 실제 Claim은 계속 차단한다.
def confirmed_claim(method, **kw):
    c=Claim('case72','claim',column=kw.pop('column','y'),analysis_method=method,semantic_confirmed=True,method_confirmed=True,missing_policy='complete_case',missing_policy_confirmed=True,analysis_spec_confirmed=True,variance_estimator='welch' if method=='welch_t' else 'classical',multiplicity_policy='none_reported',**kw)
    return c

def test_one_sample_t_is_not_silently_mean_and_preserves_mu0():
    df=pd.DataFrame({'y':[4.,5.,6.,7.]})
    c=confirmed_claim('one_sample_t',mu0=5.0)
    ct=build_typed_contract(c,'d','h')
    assert route_contract_type(c)==ContractType.DESCRIPTIVE
    run=execute_contract(ct,df)
    assert run['state']=='EXECUTED' and run['result']['method']=='one_sample_t'
    assert run['result']['estimate']==pytest.approx(0.5)

def test_paired_methods_route_to_two_column_contract_and_execute():
    df=pd.DataFrame({'pre':[1.,2.,3.,4.],'post':[2.,4.,5.,7.]})
    for method in ('paired_t','wilcoxon_signed'):
        c=confirmed_claim(method,column='post',x_column='pre')
        ct=build_typed_contract(c,'d','h')
        assert ct.contract_type==ContractType.ASSOCIATION
        run=execute_contract(ct,df)
        assert run['state']=='EXECUTED' and run['result']['method']==method

def test_missing_comparison_group_is_blocked_before_categorical_test():
    df=pd.DataFrame({'g':['A','A','B','B'],'y':['X','Y','X','Y']})
    c=confirmed_claim('chi_square',column='y',group_column='g',group_a='A',group_b='Z')
    ct=build_typed_contract(c,'d','h')
    check=check_evidence_sufficiency(ct,df)
    assert not check.executable and 'observed group B' in check.missing
    assert execute_contract(ct,df)['state']=='BLOCKED'

def test_calculation_diagnostics_and_provenance_share_normalized_filter_semantics():
    df=pd.DataFrame({'week':[12.0,13.0],'g':[1.0,2.0],'y':[1.,2.]})
    c=Claim('x','x',column='y',filters=[{'column':'week','value':12}],semantic_confirmed=True)
    snap=evidence_snapshot(c,df,'d','h')
    assert snap['rows_used']==1
    d=comparative_diagnostics(pd.DataFrame({'g':[1.0]*3+[2.0]*3,'y':[1,2,3,4,5,6]}),'y','g',1,2)
    assert d['n_a']==3 and d['n_b']==3

def test_degenerate_inferential_inputs_fail_closed():
    with pytest.raises(ValueError): inferential(pd.DataFrame({'y':[1.]}),'one_sample_t','y')
    with pytest.raises(ValueError): inferential(pd.DataFrame({'a':[1.],'b':[2.]}),'paired_t','a',x_col='b')
    with pytest.raises(ValueError): inferential(pd.DataFrame({'x':[1,1,1],'y':[2,3,4]}),'spearman_r','y',x_col='x')

def test_invalid_alpha_and_tolerance_are_not_executed():
    df=pd.DataFrame({'g':['A','A','B','B'],'y':[1.,2.,3.,4.]})
    for alpha in (float('nan'),0,1,-.1,2):
        c=confirmed_claim('welch_t',group_column='g',group_a='A',group_b='B',alpha=alpha)
        assert execute_contract(build_typed_contract(c,'d','h'),df)['state']=='BLOCKED'
        assert verify(c,df)[0]==Status.REVIEW
    c=Claim('d','d',column='y',aggregation='mean',semantic_confirmed=True,tolerance=float('nan'),current_value=2)
    assert execute_contract(build_typed_contract(c,'d','h'),df)['state']=='BLOCKED'
    assert verify(c,df)[0]==Status.REVIEW

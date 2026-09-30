"""case62 synthetic multiplicity checks; no human certification or benchmark claim."""
import math
import pytest
from core.statistics import adjust_pvalues
from core.analysis_spec import AnalysisSpecification, check_analysis_spec, build_analysis_spec
from core.executor import apply_multiplicity
from core.models import Claim

# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: 손계산 Holm/BH 및 순서·ties 검증 / 왜: 가족 순서가 목표 p를 바꾸면 안 됨.
@pytest.mark.parametrize('method,expected', [('holm',[.09,.04,.09,.2]),('bh',[.04,.04,.04,.2]),('fdr_bh',[.04,.04,.04,.2])])
def test_hand_calculated_family_order_and_ties(method, expected):
    assert adjust_pvalues([.03,.01,.03,.2],method)==pytest.approx(expected)

# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: 비유한·범위·차원·빈 가족 차단 / 왜: 잘못된 p를 계산 성공으로 반환하지 않음.
@pytest.mark.parametrize('values',[[],[math.nan],[math.inf],[-.01],[1.01],[[.01,.02]]])
def test_invalid_family_rejected(values):
    with pytest.raises(ValueError): adjust_pvalues(values,'holm')

# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: 명시적 전체 가족 fixture / 입력·출력: 4 p와 0-based 대상 1 -> 분석명세.
def family_spec(**changes):
    fields=dict(missing_policy='complete_case', human_confirmed=True,
                multiplicity_policy='holm', multiplicity_count=4,
                multiplicity_p_values=[.03,.01,.03,.2], multiplicity_target_index=1,
                multiplicity_family_definition='All four prespecified endpoint tests: A, B, C, D (target B)')
    fields.update(changes)
    return AnalysisSpecification(**fields)

# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: 불완전 가족 fail-closed / 왜: 부분 p 벡터의 보정을 전체 가족 재현으로 오인 금지.
@pytest.mark.parametrize('changes',[
    {'multiplicity_count':5},{'multiplicity_family_definition':' '},
    {'multiplicity_target_index':None},{'multiplicity_target_index':4},
    {'multiplicity_target_index':-1},{'multiplicity_target_index':True},
    {'multiplicity_p_values':[.01,.02]}, {'multiplicity_p_values':[.03,.01,math.nan,.2]},
])
def test_incomplete_family_blocked(changes):
    spec=family_spec(**changes)
    assert not check_analysis_spec(spec,'ASSOCIATION')[0]
    with pytest.raises(ValueError): apply_multiplicity({'p_value':.01},spec)

# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: 보정 결과 해석·원 p·CI 분리 / 왜: BH는 FWER가 아니고 marginal CI는 동시구간 아님.
@pytest.mark.parametrize('method,control',[('holm','FWER'),('bh','FDR'),('fdr_bh','FDR')])
def test_complete_family_applies_and_exposes_interpretation(method,control):
    spec=family_spec(multiplicity_policy=method)
    assert check_analysis_spec(spec,'ASSOCIATION')[0]
    out=apply_multiplicity({'p_value':.01,'ci95':(-1,2)},spec)
    assert out['p_value']==pytest.approx(.04)
    assert out['raw_p_value']==.01 and out['ci95']==(-1,2)
    assert out['multiplicity_error_control']==control
    assert out['multiplicity_family_definition']==spec.multiplicity_family_definition
    assert out['multiplicity_p_values']==spec.multiplicity_p_values
    assert '동시' in out['multiplicity_note']

# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: 대상 p 일치·승인서명 회귀 / 왜: 다른 검정 가족/대상으로 기존 승인을 재사용 금지.
def test_target_mismatch_and_changed_signature():
    with pytest.raises(ValueError,match='대상'): apply_multiplicity({'p_value':.01001},family_spec())
    claim=Claim('family','correlation p=.01',claim_type='association',analysis_method='pearson_r')
    claim.multiplicity_p_values=[.03,.01,.03,.2]
    claim.multiplicity_target_index=1
    claim.multiplicity_family_definition='Four endpoints'
    spec=build_analysis_spec(claim)
    assert spec.multiplicity_p_values==claim.multiplicity_p_values
    previous=claim.verification_signature()
    claim.multiplicity_family_definition='Other endpoints'
    assert previous!=claim.verification_signature()

# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: 실제 Pearson 실행과 가족 대상 결속 / 왜: helper 통과만으로 엔진 연결을 검증할 수 없음.
# 입력·출력: 고정 합성 자료·일치/불일치 원 p -> EXECUTED/BLOCKED.
@pytest.mark.parametrize('mismatch',[False,True])
def test_executor_family_target_mismatch_blocks(mismatch):
    import pandas as pd
    from core.executor import execute_contract
    from core.statistics import inferential
    from core.typed_contracts import AssociationContract, ContractType
    df=pd.DataFrame({'x':[1,2,3,4,5,6,7,8], 'y':[2,1,4,3,6,5,8,7]})
    contract=AssociationContract(claim_id='synthetic',contract_type=ContractType.ASSOCIATION,
        source_page=1,source_quote='Synthetic Pearson',dataset_name='synthetic.csv',
        dataset_hash='synthetic',human_confirmed=True,method='pearson_r',
        missing_policy='complete_case',x='x',y='y')
    raw=inferential(df,'pearson_r','y',x_col='x')['p_value']
    family=[.03,raw+.001 if mismatch else raw,.03,.2]
    spec=family_spec(multiplicity_p_values=family)
    run=execute_contract(contract,df,spec)
    assert run['state']==('BLOCKED' if mismatch else 'EXECUTED')
    if mismatch: assert run['result'] is None and '대상' in run['reason']
    else:
        assert run['result']['raw_p_value']==raw
        assert run['result']['p_value']==pytest.approx(adjust_pvalues(family,'holm')[1])

# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: 보고 p 비교가 보정 p를 사용 / 왜: 원 p=.02는 유의하지만 Holm=.08은 .05 미만 아님.
def test_reproduction_compares_adjusted_p_and_keeps_assumption_review():
    from core.gates import inferential_reproduction_gate
    spec=family_spec(multiplicity_p_values=[.03,.02,.03,.2])
    out=apply_multiplicity({'p_value':.02},spec)
    claim=Claim('p','p < .05',reported_p_value=.05,reported_p_operator='<')
    assert out['p_value']==pytest.approx(.08)
    assert inferential_reproduction_gate(claim,out).status=='FAIL'
    claim.reported_p_value=.08; claim.reported_p_operator='='
    out['assumption_alerts']=['Synthetic assumption needs review']
    assert inferential_reproduction_gate(claim,out).status=='REVIEW'

# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: 확률 경계·수치오차·알 수 없는 방법 검증 / 왜: 유효 0/1은 보존하고 다른 방법은 거부.
def test_boundary_values_and_roundoff():
    assert adjust_pvalues([0,1,1],'holm')==[0,1,1]
    assert adjust_pvalues([0,1,1],'bh')==[0,1,1]
    assert apply_multiplicity({'p_value':.01+1e-16},family_spec())['p_value']==pytest.approx(.04)
    with pytest.raises(ValueError): adjust_pvalues([.01,.02],'unknown')

# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: 소수 가족크기 잘림 방지 / 왜: 4.5를 4로 바꿔 잘못된 분모를 승인하지 않음.
def test_build_spec_preserves_invalid_family_count_for_blocking():
    claim=Claim('family','correlation',multiplicity_count=4.5,
        multiplicity_policy='holm',multiplicity_p_values=[.03,.01,.03,.2],
        multiplicity_target_index=1,multiplicity_family_definition='four tests',
        missing_policy='complete_case',analysis_spec_confirmed=True)
    spec=build_analysis_spec(claim)
    assert spec.multiplicity_count==4.5
    assert not check_analysis_spec(spec,'ASSOCIATION')[0]

# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: 표현 범위 초과 정수 p의 공통 오류 변환 / 왜: UI/명세의 ValueError 차단 경계를 우회하지 않음.
def test_oversized_integer_family_rejected_as_value_error():
    with pytest.raises(ValueError):
        adjust_pvalues([10**1000,.1],'holm')

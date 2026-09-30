"""case83 proposal boundary regression: JSON is a suggestion, never approval."""
import copy
import json
from dataclasses import asdict
import pandas as pd
import pytest
from core.models import Claim, Status
from core.proposal_intake import validate_proposal_json

# [작성: 제안보안 전문가] 2026-09-28 case83: 명시 명세 생성; 누락 기본값 숨김 방지; 입력 없음->JSON 사전; 검증: 아래 경계 시험.
def proposal():
    return dict(claim_id='C1', data_fingerprint='a'*64, evidence={'source_page':1,'source_quote':'Mean 2 kg'}, column='y', method='mean', filters=[], denominator='nonmissing y after filters', missing_policy='complete_case', unit='kg', reported_value=2.0, tolerance=.15)

# [작성: 제안보안 전문가] 2026-09-28 case83: 실제 선택 원자료에 대해 제안 검사; dict/JSON->기계 결과; 검증: 전체 모듈.
def run(payload, original=None):
    return validate_proposal_json(payload if isinstance(payload,str) else json.dumps(payload), original or Claim('C1','Mean 2 kg',2.0), pd.DataFrame({'y':[1.,2.,3.], 'x':[2.,4.,6.], 'group':['A','B','A']}), 'a'*64)

# [작성: 제안보안 전문가] 2026-09-28 case83: 완전 입력도 미확정 보존; JSON->PROPOSED; 검증: 실행 계약 차단.
def test_valid_proposal_never_confirms_or_mutates_original():
    from core.executor import execute_contract
    original=Claim('C1','Mean 2 kg',2.,semantic_confirmed=True,status=Status.VALIDATED,validated_signature='old',validated_data_hash='old',method_confirmed=True,analysis_spec_confirmed=True)
    before=copy.deepcopy(asdict(original))
    result=run(proposal(),original)
    assert result['state']=='PROPOSED' and not result['missing'] and not result['errors']
    claim=result['candidate_claim']
    assert claim is not original and asdict(original)==before
    assert claim.status==Status.REVIEW and not claim.semantic_confirmed and not claim.method_confirmed
    assert not claim.analysis_spec_confirmed and not claim.missing_policy_confirmed and not claim.scope_confirmed
    assert not claim.validated_signature and not claim.validated_data_hash
    assert not result['analysis_spec'].human_confirmed
    assert execute_contract(result['contract'],pd.DataFrame({'y':[1.,2.,3.]}),result['analysis_spec'])['state']=='BLOCKED'

# [작성: 제안보안 전문가] 2026-09-28 case83: 필수 누락 전부 열거; 불완전 JSON->BLOCKED; 검증: 필드별 시험.
@pytest.mark.parametrize('field',list(proposal()))
def test_required_fields_not_defaulted(field):
    data=proposal(); del data[field]
    result=run(data)
    assert result['state']=='BLOCKED' and field in result['missing'] and result['candidate_claim'] is None

# [작성: 제안보안 전문가] 2026-09-28 case83: 알 수 없는 키 차단; 제어/파일/실행 입력->BLOCKED; 검증: 필드별 시험.
@pytest.mark.parametrize('key',['code','path','schema','semantic_confirmed','analysis_spec_confirmed','status','provider','current_value'])
def test_extra_keys_blocked(key):
    data=proposal(); data[key]='anything'
    assert run(data)['state']=='BLOCKED'

# [작성: 제안보안 전문가] 2026-09-28 case83: strict JSON 파서 경계; 중복/비유한/잘못된 JSON->BLOCKED; 검증: 독립 문자열 시험.
@pytest.mark.parametrize('text',['{}','[]','null','{"method":"mean","method":"sum"}','{"evidence":{"source_page":1,"source_page":2}}','{"tolerance":NaN}','{"reported_value":Infinity}','{bad','{"reported_value":1e999}'])
def test_invalid_json_fails_closed(text):
    result=run(text)
    assert result['state']=='BLOCKED' and result['candidate_claim'] is None

# [작성: 제안보안 전문가] 2026-09-28 case83: bool 수치 오인·범위 오류 차단; 숫자필드->BLOCKED; 검증: 파라미터 시험.
@pytest.mark.parametrize('field,value',[('reported_value',True),('tolerance',False),('tolerance',-.1),('tolerance','0.1'),('reported_value',None)])
def test_bad_numeric_fields(field,value):
    data=proposal(); data[field]=value
    assert run(data)['state']=='BLOCKED'

# [작성: 제안보안 전문가] 2026-09-28 case83: 실행 엔진 지원 및 실제 연결 검사; 위조/미지원 입력->BLOCKED; 검증: 개별 의미 경계.
@pytest.mark.parametrize('field,value',[('method','arbitrary_model'),('data_fingerprint','b'*64),('data_fingerprint','../data.csv'),('claim_id','C2'),('column','absent'),('missing_policy','imputation'),('unit',''),('denominator',''),('reported_value',20.)])
def test_evidence_binding_and_supported_methods(field,value):
    data=proposal(); data[field]=value
    result=run(data)
    assert result['state']=='BLOCKED' and result['candidate_claim'] is None

# [작성: 제안보안 전문가] 2026-09-28 case83: 원문 위치·필터 구조·연산자 제한; nested JSON->BLOCKED; 검증: 잘못된 하위 필드.
@pytest.mark.parametrize('field,value',[('evidence',{'source_page':True,'source_quote':'q'}),('evidence',{'source_page':1}),('evidence',{'source_page':1,'source_quote':'q','path':'x'}),('filters',[{'column':'y','value':1,'op':'>'}]),('filters',[{'column':'absent','value':1}]),('filters',[{'column':'y','value':{'code':'evil'}}]),('filters',{})])
def test_nested_schema_fail_closed(field,value):
    data=proposal(); data[field]=value
    assert run(data)['state']=='BLOCKED'

# [작성: 제안보안 전문가] 2026-09-28 case83: 분석명세 기존 검사 재사용; 미확정 inferential JSON->PROPOSED; 검증: unsupported 분산 정책.
def test_inferential_analysis_spec_reused_unconfirmed():
    data=proposal(); data.update(method='pearson_r',x_column='x',alpha=.05,analysis_spec={'population':'observed participants','estimand':'Pearson correlation','variance_estimator':'classical','multiplicity_policy':'none'})
    result=run(data)
    assert result['state']=='PROPOSED' and result['analysis_spec'].human_confirmed is False
    data['analysis_spec']['variance_estimator']='robust'
    assert 'variance estimator:robust' in run(data)['unsupported']

# [작성: 제안보안 전문가] 2026-09-28 case83: 추론 명세·변수 무기본값 보존; 불완전 JSON->누락; 검증: missing 목록.
def test_inferential_missing_fields_reported():
    data=proposal(); data['method']='pearson_r'
    result=run(data)
    assert result['state']=='BLOCKED'
    assert {'x_column','alpha','analysis_spec'}.issubset(result['missing'])

# [작성: 제안보안 전문가] 2026-09-28 case83: 필터는 등가 비교만 허용; 안전 scalar->미확정 제안; 검증: 정상 필터 및 provenance.
def test_filter_candidates_keep_unconfirmed_provenance():
    data=proposal(); data['filters']=[{'column':'group','value':'A'}]
    result=run(data)
    assert result['state']=='PROPOSED'
    assert not result['candidate_claim'].evidence_provenance.get('confirmed_by')
    assert result['candidate_claim'].decomposition['proposal_metadata']['denominator']==data['denominator']

# [작성: 제안보안 전문가] 2026-09-28 case83: JSON resource 한도; oversized/deep->BLOCKED; 검증: 파서 예외 미유출.
def test_resource_limits():
    assert run(' '*65537)['state']=='BLOCKED'
    assert run('['*2000+']'*2000)['state']=='BLOCKED'

# [작성: 제안보안 전문가] 2026-09-28 case83: 선택 원문 증거 결속; 거짓 위치/인용->BLOCKED; 검증: 실제 원Claim 불변.
@pytest.mark.parametrize('evidence',[{'source_page':2,'source_quote':'Mean 2 kg'},{'source_page':1,'source_quote':'different quote'}])
def test_evidence_matches_existing_original(evidence):
    data=proposal(); data['evidence']=evidence
    assert run(data,Claim('C1','Mean 2 kg',2.,source_page=1))['state']=='BLOCKED'

# [작성: 제안보안 전문가] 2026-09-28 case83: 미지지 분석명세를 기술통계에 숨김 금지; spec->BLOCKED; 검증: 없는 분석 실행 경로.
def test_descriptive_does_not_silently_ignore_analysis_spec():
    data=proposal(); data['analysis_spec']={'variance_estimator':'robust'}
    assert run(data)['state']=='BLOCKED'

# [작성: 제안보안 전문가] 2026-09-28 case83: 방법별 필수값 생략 거절; 방법->누락필드; 검증: 기존 engine 인자 기본값 미대체.
@pytest.mark.parametrize('method,field',[('weighted_mean','weight_column'),('proportion','success_value'),('one_sample_t','mu0'),('welch_t','group_column'),('pearson_r','x_column')])
def test_method_specific_fields_missing(method,field):
    data=proposal(); data['method']=method
    assert field in run(data)['missing']

# [작성: 제안보안 전문가] 2026-09-28 case83: analysis 하위 제어·수치·명세 타입 제한; 이상 spec->BLOCKED; 검증: 파라미터 시험.
@pytest.mark.parametrize('spec', [{'human_confirmed':True},{'multiplicity_count':True},{'multiplicity_p_values':[True]},{'multiplicity_p_values':[1.1]},{'reference_levels':[]},{'transforms':[]},{'interactions':[2]}])
def test_nested_analysis_spec_types(spec):
    data=proposal(); data['analysis_spec']=spec
    assert run(data)['state']=='BLOCKED'

# [작성: 제안보안 전문가] 2026-09-28 case83: 범위 과잉 주장을 평균으로 우회 금지; overclaim->BLOCKED; 검증: original 선언 보존.
def test_scope_claim_cannot_be_recast_as_mean():
    original=Claim('C1','Mean 2 kg',2.,decomposition={'overclaim_signal':True})
    assert run(proposal(),original)['state']=='BLOCKED'

# [작성: 제안보안 전문가] 2026-09-28 case83: 원문과 정정안 값을 구분; 정정된Claim->원문 제안만 수용; 검증: original/current 보존.
def test_amended_claim_is_bound_to_original_report():
    original=Claim('C1','Mean 2 kg',2.,current_value=9.,revision_count=1)
    result=run(proposal(),original)
    assert result['state']=='PROPOSED'
    assert result['candidate_claim'].original_value==2. and result['candidate_claim'].current_value==2.
    assert original.current_value==9. and original.revision_count==1
    data=proposal(); data['reported_value']=9.
    assert run(data,original)['state']=='BLOCKED'

# [작성: 제안보안 전문가] 2026-09-28 case83: 잘못된 공용 호출도 fail-closed; None/위조 df->BLOCKED; 검증: 외부 예외 없음.
@pytest.mark.parametrize('dataframe',[None,object(),{'columns':['y']}])
def test_bad_trusted_dataframe_blocks(dataframe):
    result=validate_proposal_json(json.dumps(proposal()),Claim('C1','Mean 2 kg',2.),dataframe,'a'*64)
    assert result['state']=='BLOCKED' and result['errors']

# [작성: 제안보안 전문가] 2026-09-28 case83: 중복 열의 모호한 연결 거절; 동일열 df->BLOCKED; 검증: 해시만으로 column 의미 추측 없음.
def test_duplicate_dataset_columns_block():
    result=validate_proposal_json(json.dumps(proposal()),Claim('C1','Mean 2 kg',2.),pd.DataFrame([[1,2]],columns=['y','y']),'a'*64)
    assert result['state']=='BLOCKED'

# [작성: 제안보안 전문가] 2026-09-28 case83: 실행기가 적용하지 않는 1표본 가족보정 거절; 명세->BLOCKED; 검증: 조용한 정책 누락 방지.
# [수정: 0 이영] 2026-09-30 23:35 KST — 확인된 1표본 Bonferroni 실행 지원에 맞춰 제안 수용을 검증한다. 제안은 확인하지 않으므로 실제 실행 BLOCKED를 함께 검증한다.
def test_one_sample_multiplicity_proposed_but_requires_confirmation():
    from core.executor import execute_contract
    data=proposal(); data.update(method='one_sample_t',mu0=0.,alpha=.05,analysis_spec={'population':'observed participants','estimand':'mean difference from zero','variance_estimator':'classical','multiplicity_policy':'bonferroni','multiplicity_count':3})
    result=run(data)
    assert result['state']=='PROPOSED' and not result['unsupported']
    claim=result['candidate_claim']
    assert not claim.semantic_confirmed and not claim.method_confirmed
    assert not claim.analysis_spec_confirmed and not claim.missing_policy_confirmed
    assert not result['analysis_spec'].human_confirmed
    execution=execute_contract(result['contract'],pd.DataFrame({'y':[1.,2.,3.]}),result['analysis_spec'])
    assert execution['state']=='BLOCKED' and execution['result'] is None

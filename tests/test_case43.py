"""case43: independent claim verdicts, multiplicity, and replay evidence."""
import pandas as pd
import pytest

from core.models import Claim, Status
from core.workflow import revise_and_reverify
from core.verifier import refresh_reported_status


# [작성: 전문가4] 2026-09-25 case43
# 무엇을: 원문·정정 판정 분리 회귀 / 왜: 정정 승인 뒤 원문 실패를 데이터에서 지우지 않기 위해 / 입력·출력: 보고값 18.4, 원자료 14.8 / 검증: 원문 CONFLICT, 정정 SUPPORTED.
def test_reported_and_amendment_status_survive_snapshot(tmp_path):
    from core.team_workspace import Workspace, make_snapshot
    c=Claim('C-1','보고값 18.4',18.4,column='score',semantic_confirmed=True)
    df=pd.DataFrame({'score':[14.7,14.9]})
    refresh_reported_status(c,df)
    revise_and_reverify(c,df,14.8,'연구자 정정')
    assert c.reported_status==Status.CONFLICT
    assert c.amendment_status==Status.SUPPORTED
    assert c.status==Status.SUPPORTED
    snapshot=make_snapshot({'claims':[c],'audit_store':type('Ledger',(),{'for_claim':lambda *_args,**_kw:[],'attempts_for_claim':lambda *_args,**_kw:[]})(),'dataset_hash':'h','dataset_name':'raw.csv','df':df})
    store=Workspace(tmp_path)
    item=store.save('이영','검토','진행 중',snapshot=snapshot)
    saved=Workspace(tmp_path).get(item)['snapshot']['claims'][0]
    assert saved['reported_status']=='CONFLICT'
    assert saved['amendment_status']=='SUPPORTED'
    assert saved['original_value']==18.4 and saved['current_value']==14.8


# [작성: 전문가6] 2026-09-25 case43
# 무엇을: 보정 명세의 수치와 미완성 차단 회귀 / 왜: 보정 없는 p를 보고 p와 비교하는 오류 방지 / 입력·출력: p=.01, 3개 검정 -> .03 / 검증: 손계산 기대값.
def test_bonferroni_requires_family_count_and_preserves_raw_p():
    from core.analysis_spec import AnalysisSpecification,check_analysis_spec
    from core.executor import apply_multiplicity
    spec=AnalysisSpecification(missing_policy='complete_case',variance_estimator='classical',multiplicity_policy='bonferroni',human_confirmed=True)
    assert not check_analysis_spec(spec,'COMPARATIVE')[0]
    spec.multiplicity_count=3
    assert check_analysis_spec(spec,'COMPARATIVE')[0]
    result=apply_multiplicity({'p_value':0.01},spec)
    assert result['raw_p_value']==0.01
    assert result['p_value']==pytest.approx(0.03)
    assert result['multiplicity_policy']=='bonferroni'


# [작성: 전문가6] 2026-09-25 case43
# 무엇을: 가정 경고가 숫자 일치를 자동 PASS로 바꾸지 못하게 함 / 왜: 실행과 추론 적합성 분리 / 입력·출력: 수치가 일치하지만 표본 부족인 결과 / 검증: REVIEW 유지.
def test_assumption_alert_prevents_inferential_pass():
    from core.gates import inferential_reproduction_gate
    claim=Claim('I-1','p=0.04',reported_p_value=0.04,reported_p_operator='=')
    gate=inferential_reproduction_gate(claim,{'p_value':0.04,'assumption_alerts':['각 집단 유효 표본 3 미만']})
    assert gate.status=='REVIEW'


# [작성: 전문가7] 2026-09-25 case43
# 무엇을: 미승인 라벨의 성능 수치 차단 / 왜: AI가 제안한 정답을 사람 정답처럼 발표하지 않기 위해 / 입력·출력: 결과·라벨 / 검증: NOT_SCORED.
def test_comparison_requires_human_labels():
    from core.evaluation import score_comparison
    labels=[{'claim_id':'A','expected_action':'EXECUTE','expected_value':2,'review_status':'PENDING_HUMAN','verified_by':None}]
    runs={'system':[{'claim_id':'A','action':'EXECUTE','value':2,'source_hash':'h'}]}
    assert score_comparison(runs,labels,{'A':'h'})['status']=='NOT_SCORED'


# [작성: 전문가7] 2026-09-25 case43
# 무엇을: 거짓 실행률·재현률 분모 검증 / 왜: 서로 다른 분모를 섞는 발표 오류 방지 / 입력·출력: 승인된 3건 / 검증: 1/1 거짓 실행, 1/2 재현.
def test_comparison_uses_correct_denominators():
    from core.evaluation import score_comparison
    labels=[{'claim_id':'A','expected_action':'EXECUTE','expected_value':2,'tolerance':0,'review_status':'APPROVED','verified_by':'조지현'},
            {'claim_id':'B','expected_action':'EXECUTE','expected_value':3,'tolerance':0,'review_status':'APPROVED','verified_by':'조지현'},
            {'claim_id':'C','expected_action':'BLOCK','expected_value':None,'tolerance':0,'review_status':'APPROVED','verified_by':'조지현'}]
    # [수정: 전문가7] 2026-09-25 case49
    # 종류: 검증방법추가 / 재현 방법: 선택 이름만 승인된 합성 라벨은 새 독립 검토 관문에서 점수화되지 않음 / 변경 전: 승인 이름만 기록 / 변경 후: 두 외부 판정의 합성 근거를 입력에 추가 / 왜: 기존 분모 기대값은 보존하면서 채점 전제를 명시 / 영향: 실제 사람 정답이라는 뜻은 아님.
    for label in labels:
        label['independent_reviews']=[{'reviewer_id':f'external-{i}','identity_check_ref':f'synthetic-test-{i}',
            'independent_of_development':True,'blind_to_outputs':True,'source_location':'test p.1',
            'data_sha256':'h','expected_action':label['expected_action'],'expected_value':label['expected_value'],
            'rationale':'손계산 시험'} for i in (1,2)]
    runs={'system':[{'claim_id':'A','action':'EXECUTE','value':2,'source_hash':'h'},
                    {'claim_id':'B','action':'BLOCK','source_hash':'h'},
                    {'claim_id':'C','action':'EXECUTE','value':1,'source_hash':'h'}]}
    out=score_comparison(runs,labels,{x:'h' for x in 'ABC'})
    assert out['systems']['system']['false_execution_rate']==1
    assert out['systems']['system']['reproduction_rate']==0.5
    assert out['systems']['system']['review_seconds_median'] is None


# [작성: 전문가4] 2026-09-25 case43
# 무엇을: 제3자 재실행 값·차단 확인 / 왜: 본 앱 로직과 분리된 원자료 검산 / 입력·출력: 공개 3논문 6사례 / 검증: 손계산 가능한 행 수와 차단.
def test_independent_replay_uses_bundled_public_data():
    from tools.independent_replay import replay_cases
    rows={r['claim_id']:r for r in replay_cases()['results']}
    assert rows['PENG-ROWS']['value']==344
    assert rows['PENG-MISSING']['value']==19
    assert rows['WINE-RED']['value']==1599
    assert rows['WINE-WHITE']['value']==4898
    assert rows['DINO-X']['value']==pytest.approx(54.2632732394)
    assert rows['WINE-SVM']['action']=='BLOCK'


# [작성: 전문가4] 2026-09-25 case43
# 무엇을: 원자료 변조 차단 / 왜: 다른 CSV로 동일 Claim 재현을 주장하지 못하게 함 / 입력·출력: 잘못된 해시 / 검증: ValueError.
def test_independent_replay_rejects_changed_data(tmp_path,monkeypatch):
    import json
    from tools import independent_replay
    monkeypatch.setattr(independent_replay,'ROOT',tmp_path)
    (tmp_path/'raw.csv').write_text('x\n1\n',encoding='utf-8')
    manifest=tmp_path/'cases.json'
    manifest.write_text(json.dumps({'cases':[{'claim_id':'X','data_file':'raw.csv','data_sha256':'0'*64,'method':'count_rows'}]}),encoding='utf-8')
    with pytest.raises(ValueError,match='해시 불일치'):
        independent_replay.replay_cases(manifest)


# [작성: 전문가7] 2026-09-25 case43
# 무엇을: 실엔진 공개 사례 안전 차단 / 왜: 지원하지 않는 행 수·모형을 실행 성공으로 가장하지 않기 위해 / 입력·출력: 6개 공개 사례 / 검증: 지원 3건 실행, 나머지 차단.
def test_system_public_cases_do_not_fake_unsupported_methods():
    from tools.run_corpus_system import run_system
    rows={r['claim_id']:r for r in run_system()['results']}
    assert [x for x in rows if rows[x]['action']=='EXECUTE']==['WINE-RED','WINE-WHITE','DINO-X']
    assert rows['DINO-X']['verdict']=='SUPPORTED'
    assert rows['WINE-SVM']['action']=='BLOCK'


# [작성: 전문가6] 2026-09-25 case43
# 무엇을: Welch·Bonferroni 실행 경로 / 왜: 명세 확인이 실제 p 보정까지 전달되어야 함 / 입력·출력: 3 대 3 예시와 검정 3개 가족 / 검증: 보정 p=min(3×raw,1), 방법 불일치 차단.
def test_confirmed_welch_and_bonferroni_execute_together():
    from core.typed_contracts import build_typed_contract
    from core.analysis_spec import build_analysis_spec
    from core.executor import execute_contract
    df=pd.DataFrame({'group':['A']*3+['B']*3,'y':[1.,2.,4.,4.,5.,8.]})
    c=Claim('T','두 군 평균 차이',column='y',group_column='group',group_a='A',group_b='B',semantic_confirmed=True)
    c.decomposition={'claim_kind':'comparison'};c.analysis_method='welch_t';c.method_confirmed=True
    c.missing_policy='complete_case';c.missing_policy_confirmed=True;c.analysis_spec_confirmed=True;c.variance_estimator='welch';c.multiplicity_policy='bonferroni';c.multiplicity_count=3
    contract=build_typed_contract(c,'raw.csv','hash')
    run=execute_contract(contract,df,build_analysis_spec(c))
    assert run['state']=='EXECUTED',run
    assert run['result']['p_value']==pytest.approx(min(1,3*run['result']['raw_p_value']))
    c.variance_estimator='classical'
    blocked=execute_contract(contract,df,build_analysis_spec(c))
    assert blocked['state']=='BLOCKED'


# [작성: 전문가4] 2026-09-25 case43
# 무엇을: 공유 저장 시 추론 원문 판정 보존 / 왜: 기술통계 갱신 경로가 추론 결과를 덮지 않아야 함 / 입력·출력: 추론 Claim과 공유 스냅샷 / 검증: CONFLICT와 이유 유지.
def test_inferential_reported_verdict_survives_shared_snapshot():
    from core.team_workspace import make_snapshot
    c=Claim('I','두 집단 평균',column='y',analysis_method='welch_t')
    c.reported_status=Status.CONFLICT
    c.reported_reason='원문 p 불일치'
    state={'claims':[c],'audit_store':type('Ledger',(),{'for_claim':lambda *_a,**_k:[],'attempts_for_claim':lambda *_a,**_k:[]})(),
           'dataset_hash':'h','dataset_name':'raw.csv','df':pd.DataFrame({'y':[1,2]})}
    saved=make_snapshot(state)['claims'][0]
    assert saved['reported_status']=='CONFLICT'
    assert saved['reported_reason']=='원문 p 불일치'

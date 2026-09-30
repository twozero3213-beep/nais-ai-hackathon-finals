"""case47 regressions for the team workspace and independent review."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


# [작성: 전문가2] 2026-09-25 case47
# 무엇을: 안전 확인 누락으로 저장이 거부되어도 입력 초안을 유지 / 왜: 작성 중인 메모가 사라지면 팀 공유가 불가능 / 입력·출력: 제목·메모를 채운 팀 폼 -> 거부 후 같은 값 / 검증: 실제 Streamlit AppTest 제출.
def test_rejected_team_save_preserves_draft(tmp_path, monkeypatch):
    import core.paths as paths
    import core.team_workspace as team
    import inspect
    assert 'clear_on_submit=False' in inspect.getsource(team.render_workspace)
    monkeypatch.setattr(team,'settings',lambda:{})
    monkeypatch.setenv('EVIDENCE_GATE_LOCAL_MODE','1')
    monkeypatch.setenv('EVIDENCE_GATE_TEAM_DIR',str(tmp_path/'team'))
    monkeypatch.setattr(paths,'AUDIT_DB_PATH',tmp_path/'audit.db')
    monkeypatch.setattr(paths,'CHANGE_DB_PATH',tmp_path/'changes.db')
    monkeypatch.setattr(paths,'RUNTIME_LOG_PATH',tmp_path/'runtime.log')
    # [수정: 0 이영] 2026-10-01 00:17 KST — 팀 폼은 새 인증된 팀 진입점에서 검사한다. 초안 보존·확인 누락 거부 기대는 유지한다.
    at=AppTest.from_file(Path(__file__).resolve().parents[1]/'0_이영_팀작업실.py',default_timeout=30).run()
    at.radio(key='workspace_view').set_value('팀 공동 작업실').run()
    next(x for x in at.text_input if x.label=='작업 제목').set_value('재현 실험 초안').run()
    next(x for x in at.text_area if x.label=='진행 내용 · 검토 요청').set_value('원문 17변수와 CSV 8열 비교').run()
    next(x for x in at.button if x.label=='팀에 저장').click().run()
    assert not at.exception
    assert any('비밀정보 포함 여부' in x.value for x in at.error)
    assert next(x for x in at.text_input if x.label=='작업 제목').value=='재현 실험 초안'
    assert next(x for x in at.text_area if x.label=='진행 내용 · 검토 요청').value=='원문 17변수와 CSV 8열 비교'
    next(x for x in at.checkbox if x.label.startswith('첨부파일·메모에')).set_value(True).run()
    next(x for x in at.button if x.label=='팀에 저장').click().run()
    assert not at.exception
    assert len(team.Workspace(tmp_path/'team').list())==1
    assert next(x for x in at.text_input if x.label=='작업 제목').value==''


# [작성: 전문가4] 2026-09-25 case47
# 무엇을: 과거 중복 첨부가 있어도 공동 작업실 전체를 표시 / 왜: 동일 파일 재첨부 시 다운로드 위젯 키 충돌 / 입력·출력: 같은 이름·내용 첨부 2개가 있는 레코드 -> 화면 예외 없음 / 검증: 실제 AppTest 화면 렌더.
def test_duplicate_legacy_attachments_do_not_crash_workspace(tmp_path, monkeypatch):
    import core.paths as paths
    import core.team_workspace as team
    monkeypatch.setattr(team,'settings',lambda:{})
    monkeypatch.setenv('EVIDENCE_GATE_LOCAL_MODE','1')
    monkeypatch.setenv('EVIDENCE_GATE_TEAM_DIR',str(tmp_path/'team'))
    monkeypatch.setattr(paths,'AUDIT_DB_PATH',tmp_path/'audit.db')
    monkeypatch.setattr(paths,'CHANGE_DB_PATH',tmp_path/'changes.db')
    monkeypatch.setattr(paths,'RUNTIME_LOG_PATH',tmp_path/'runtime.log')
    store=team.Workspace(tmp_path/'team')
    record_id=store.save('이영','중복 첨부 시험','검토 요청',files=[('same.txt',b'x'),('same.txt',b'x')])
    assert len(store.get(record_id)['files'])==2
    # [수정: 0 이영] 2026-10-01 00:17 KST — 공개 검산으로 바뀐 app.py 대신 실제 팀 진입점의 중복 첨부 표시를 검사한다.
    at=AppTest.from_file(Path(__file__).resolve().parents[1]/'0_이영_팀작업실.py',default_timeout=30).run()
    at.radio(key='workspace_view').set_value('팀 공동 작업실').run()
    assert not at.exception


# [작성: 전문가7] 2026-09-25 case47
# 무엇을: 95% 신뢰수준을 효과 백분율로 잘못 뽑는 경로 차단 / 왜: 방법의 신뢰수준과 Claim 값은 다름 / 입력·출력: 두 손계산 구간 -> CI 후보만 / 검증: 0.1~0.3, -0.4~-0.1.
def test_confidence_level_is_not_a_percentage_claim():
    from core.pdf_claims import extract_numeric_claims
    for sentence,bounds in [('The effect had a 95% CI [0.1, 0.3].',(0.1,0.3)),
                            ('The effect had a 95% CI from -0.4 to -0.1.',(-0.4,-0.1))]:
        candidates=extract_numeric_claims(sentence)
        assert [(c['claim_type'],c['ci95']) for c in candidates]==[('confidence_interval',bounds)]


# [작성: 전문가7] 2026-09-25 case47
# 무엇을: 동일 Claim ID 중복 제출을 채점 전 차단 / 왜: 행 순서만 바꿔 재현률 0과 1을 선택 가능 / 입력·출력: 승인된 A 하나와 BLOCK·EXECUTE 중복 예측 -> 오류 / 검증: 두 순서 모두 ValueError.
def test_duplicate_predictions_cannot_change_comparison_score():
    from core.evaluation import score_comparison
    label={'claim_id':'A','expected_action':'EXECUTE','expected_value':2,'review_status':'APPROVED','verified_by':'이영'}
    # [수정: 전문가7] 2026-09-25 case49
    # 종류: 검증방법추가 / 재현 방법: 이름만 적힌 합성 라벨은 채점 전에 차단 / 변경 전: 이름만 입력 / 변경 후: 두 외부 판정의 합성 근거를 추가 / 왜: 중복 결과 거부 기대값은 그대로 검증 / 영향: 실제 독립 사람 라벨은 아님.
    label['independent_reviews']=[{'reviewer_id':f'external-{i}','identity_check_ref':f'synthetic-test-{i}',
        'independent_of_development':True,'blind_to_outputs':True,'source_location':'test p.1',
        'data_sha256':'h','expected_action':'EXECUTE','expected_value':2,'rationale':'손계산 시험'} for i in (1,2)]
    rows=[{'claim_id':'A','action':'BLOCK','source_hash':'h'},
          {'claim_id':'A','action':'EXECUTE','value':2,'source_hash':'h'}]
    for ordered in (rows,list(reversed(rows))):
        with pytest.raises(ValueError,match='중복'):
            score_comparison({'system':ordered},[label],{'A':'h'})


# [작성: 전문가6] 2026-09-25 case47
# 무엇을: 계산 불가능한 p·효과크기가 추론 재현 PASS로 승격되지 않게 함 / 왜: NaN 비교는 차이가 있어도 False / 입력·출력: p=.04, 재분석 NaN/None -> REVIEW / 검증: 상수열 Pearson처럼 유한 통계량 없음.
def test_nonfinite_inferential_result_never_passes():
    from core.gates import inferential_reproduction_gate
    from core.models import Claim
    claim=Claim('N','p=0.04',reported_p_value=0.04,reported_p_operator='=')
    for value in (float('nan'),float('inf'),None):
        assert inferential_reproduction_gate(claim,{'p_value':value}).status=='REVIEW'
    claim.reported_p_value=None
    claim.reported_effect=0.5
    claim.effect_kind='correlation_r'
    assert inferential_reproduction_gate(claim,{'estimate':float('nan')}).status=='REVIEW'


# [작성: 전문가6] 2026-09-25 case47
# 무엇을: 상수 X의 실제 Pearson 실행 결과를 차단 / 왜: NaN이 산출된 실행을 완료로 저장하면 검증 기반이 없음 / 입력·출력: X=[1,1,1], Y=[1,2,3] -> BLOCKED / 검증: 상수열 상관계수는 정의되지 않음.
def test_constant_input_pearson_is_not_executed(monkeypatch):
    import pandas as pd
    from scipy import stats
    from core.executor import execute_contract
    from core.typed_contracts import AssociationContract,ContractType
    # [수정: 0 이영] 2026-09-30 23:35 KST — 상수 입력 가드 자체에 도달하도록 합성 계약의 분석명세 확인을 명시한다. scipy 호출 금지 기대는 유지한다.
    from core.analysis_spec import AnalysisSpecification
    contract=AssociationContract(claim_id='N',contract_type=ContractType.ASSOCIATION,source_page=1,
        source_quote='Pearson r=0.5',dataset_name='raw.csv',dataset_hash='h',human_confirmed=True,
        method='pearson_r',method_confirmed=True,missing_policy='complete_case',missing_policy_confirmed=True,x='x',y='y',
        analysis_spec=AnalysisSpecification(
            population='synthetic observations',estimand='Pearson correlation',
            missing_policy='complete_case',variance_estimator='classical',
            multiplicity_policy='none_reported',human_confirmed=True).to_dict())
    # [수정: 전문가12·16] 2026-09-28 case81: case72의 계산 전 상수 차단을 검증. NaN 계산/경고 강제 대신 호출 자체 금지.
    def forbidden_pearson(*args,**kwargs):
        pytest.fail('상수 입력은 scipy 계산 전에 차단되어야 합니다.')
    monkeypatch.setattr(stats,'pearsonr',forbidden_pearson)
    result=execute_contract(contract,pd.DataFrame({'x':[1,1,1],'y':[1,2,3]}))
    assert result['state']=='BLOCKED'
    assert result['result'] is None
    assert '서로 다른 값' in result['reason']

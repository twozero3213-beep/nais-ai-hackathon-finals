"""Portable proposal review and rerun invalidation, without analysis or approval."""
import copy
import json
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from core.models import Claim
from core import proposal_intake as intake

# [작성: 전문가4·5] 2026-09-28 case84
# 무엇을: 손계산 10/20 평균15 입력 / 왜: 분야와 무관한 계약 시험 / 입력·출력: 열명->원문·자료·제안 / 검증: 아래 시험.
def case(column='value'):
    claim=Claim('C','Mean 15 units',15,source_page=1,source_quote='Mean 15 units')
    df=pd.DataFrame({column:[10,20]})
    p=dict(claim_id='C',data_fingerprint='a'*64,evidence=dict(source_page=1,source_quote=claim.text),column=column,method='mean',filters=[],denominator='nonmissing observations',missing_policy='complete_case',unit='units',reported_value=15,tolerance=0)
    return claim,df,p

# [작성: 전문가4·8] 2026-09-28 case84
# 무엇을: 기계 보고 재사용 / 왜: UI 밖에서도 동일한 차단 / 입력·출력: JSON->결속 보고 / 검증: 상태·부작용·직렬화.
@pytest.mark.parametrize('column',['rain_mm','response_seconds'])
def test_portable_report_is_deterministic_unconfirmed(column):
    claim,df,p=case(column); before=copy.deepcopy(claim)
    first=intake.review_proposal_json(json.dumps(p),claim,df,'a'*64)
    assert first==intake.review_proposal_json(json.dumps(p),claim,df,'a'*64)
    assert first['state']=='PROPOSED' and first['executed'] is False
    assert first['approved'] is False and first['semantic_verified'] is False
    assert first['next_steps'] and json.loads(json.dumps(first))==first
    assert claim==before

# [작성: 전문가4·7] 2026-09-28 case84
# 무엇을: 오류에서 수정행동 연결 / 왜: 단순 영문오류로 끝나지 않음 / 입출력: 반례->차단+필드 / 검증: 누락·미지원·불일치.
@pytest.mark.parametrize('field,value,category',[('denominator','', 'missing'),('method','unknown_model','unsupported'),('data_fingerprint','b'*64,'errors'),('reported_value',999,'errors')])
def test_blocked_report_has_actionable_feedback(field,value,category):
    claim,df,p=case();p[field]=value
    report=intake.review_proposal_json(json.dumps(p),claim,df,'a'*64)
    assert report['state']=='BLOCKED'
    assert any(row['category']==category and row['action'] and row['issue'] for row in report['next_steps'])
    assert report['executed'] is False

# [작성: 전문가4·7] 2026-09-28 case84
# 무엇을: 공급자 독립 요청 / 왜: 데이터 자동전송 없이 제안형식 제공 / 입출력: 원문·열목록->프롬프트 / 검증: 원자료 행 제외·유효 JSON.
def test_request_prompt_excludes_rows_and_preserves_original():
    claim,df,p=case();df['private_note']=['SECRET_ROW_1','SECRET_ROW_2']
    request=intake.proposal_request(claim,df,'a'*64)
    encoded=json.dumps(request,ensure_ascii=False)
    assert 'SECRET_ROW_1' not in encoded and 'SECRET_ROW_2' not in encoded
    assert request['proposal_template']['reported_value']==15
    assert request['proposal_template']['method']==''
    assert request['data_rows_included'] is False
    assert 'private_note' in request['column_names']

# [작성: 전문가4·5] 2026-09-28 case84
# 무엇을: 아주 작은 원문 값 변경도 검토 무효화 / 왜: 재현성용15자리 정규화와 캐시무효화 구분 / 입력·출력: 다른float->다른지문 / 검증: 동일표시 반올림 경계.
def test_context_key_does_not_round_original_report():
    claim,_,p=case();claim.original_value=1.0000000000000002
    first=intake.proposal_review_key(json.dumps(p),claim,'a'*64)
    claim.original_value=1.0000000000000004
    assert first!=intake.proposal_review_key(json.dumps(p),claim,'a'*64)

# [작성: 전문가4·8] 2026-09-28 case84
# 무엇을: UI없는 재사용 예제 검증 / 왜: 검토 기능은서버 불필요 / 입출력: 합성행렬->2후보8차단 / 검증: 실행·승인0.
def test_portable_demo_without_ui():
    from tools.proposal_review_demo import run_demo
    report=run_demo()
    assert report['all_passed'] and len(report['cases'])==10
    assert sum(row['actual']=='BLOCKED' for row in report['cases'])==8
    assert report['ai_calls']==report['human_labels']==report['new_papers_reproduced']==0

# [작성: 전문가4·1] 2026-09-28 case84
# 무엇을: 결과 재실행 유지·입력변경 무효화 / 왜: 다운로드 재실행에서 결과 유실 및 오래된 판정 금지 / 입출력: 클릭/수정->표시 / 검증: 실제 AppTest.
def test_review_survives_rerun_and_disappears_when_input_changes():
    app=AppTest.from_string('''
import streamlit as st
import pandas as pd
from core.models import Claim
from core.proposal_ui import render_proposal_review
if 'c' not in st.session_state:
    st.session_state.c=Claim('C','Mean 15 units',15,source_page=1,source_quote='Mean 15 units')
if 'dataset_hash' not in st.session_state: st.session_state.dataset_hash='a'*64
render_proposal_review(st.session_state.c,pd.DataFrame({'value':[10,20]}),st.session_state.dataset_hash)
''',default_timeout=30).run()
    _,_,p=case()
    app.text_area(key='proposal_json_C').set_value(json.dumps(p))
    app.button(key='proposal_check_C').click().run()
    assert not app.exception and app.json
    app.run()
    assert app.json, 'review must remain available after download/rerun'
    assert any(d.label=='AI 분석 제안 요청 JSON' for d in app.get('download_button'))
    app.session_state.dataset_hash='b'*64;app.run()
    assert not app.json, 'old dataset report must not remain visible'
    app.session_state.dataset_hash='a'*64
    app.button(key='proposal_check_C').click().run()
    app.text_area(key='proposal_json_C').set_value('{}').run()
    assert not app.json, 'edited proposal needs a new review'
    app.text_area(key='proposal_json_C').set_value(json.dumps(p))
    app.button(key='proposal_check_C').click().run()
    app.session_state.c.original_value=99;app.run()
    assert not app.json, 'original report change invalidates the cached report'

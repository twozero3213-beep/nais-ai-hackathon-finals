"""Candidate review UI; proposals never replace a claim or execute an analysis."""
import json
import streamlit as st
from core.proposal_intake import MAX_PROPOSAL_CHARS, proposal_request, proposal_review_key, review_proposal_json


# [작성: UX·통합 담당] 2026-09-28 case83
# 무엇을: AI 제안의 누락·불일치 검토 / 왜: 자유 답변과 실행 명세 분리 / 입력·출력: 원문Claim·df·지문 -> 검토화면 / 검증: test_case83_integration.
def render_proposal_review(claim, dataframe, dataset_hash):
    st.caption('어떤 도구가 작성한 제안이든 같은 JSON 형식으로 검사합니다. 원문·정정안·승인을 변경하거나 계산을 실행하지 않습니다. 원문 보고값을 사용하세요.')
    # [수정: 전문가1·7] 2026-09-28 case84 / 종류: 효율화 / 재현: AI별 임의 답변 형식 / 전후: 빈 양식만→공통 요청+양식 / 왜: 공급자 독립 연결 / 영향: 외부 자동전송 없음.
    request = proposal_request(claim, dataframe, dataset_hash)
    template = request['proposal_template']
    st.download_button('AI 분석 제안 요청 JSON', json.dumps(request, ensure_ascii=False, indent=2),
                       file_name='analysis_request.json', mime='application/json', key='proposal_request_'+claim.claim_id)
    st.caption('내려받은 요청을 선택한 AI에 직접 전달하고 JSON 제안을 붙여 넣습니다. 자동 API 호출은 없습니다. 원자료 행은 제외하지만 인용문·열 이름도 민감할 수 있습니다.')
    st.download_button('분석 제안 JSON 빈 양식', json.dumps(template, ensure_ascii=False, indent=2),
                       file_name='analysis_proposal.json', mime='application/json', key='proposal_template_'+claim.claim_id)
    text = st.text_area('분석 제안 JSON', max_chars=MAX_PROPOSAL_CHARS,
                        key='proposal_json_'+claim.claim_id)
    # [수정: 전문가4·1] 2026-09-28 case84 / 종류: 오류수정 / 재현: 검사 뒤 rerun시 결과 유실 / 전후: 일회 출력→문맥 지문 결속 세션 기록 / 왜: 다운로드 유지·오래된 결과 차단 / 영향: 실행·승인 상태 불변.
    cache_key='proposal_review_'+claim.claim_id
    context=proposal_review_key(text,claim,dataset_hash)
    cached=st.session_state.get(cache_key)
    if cached and cached['context_sha256'] != context:
        del st.session_state[cache_key]
    if st.button('제안 형식·조건 검사', key='proposal_check_'+claim.claim_id):
        st.session_state[cache_key]=review_proposal_json(text,claim,dataframe,dataset_hash)
    report=st.session_state.get(cache_key)
    if report is None:
        return
    if report['state'] == 'PROPOSED':
        st.info('미확정 후보: 형식과 현재 자료의 조건을 대조했습니다. 원문 의미·분석조건 확정 및 실행·승인은 수행하지 않았습니다.')
    else:
        st.warning('후보 접수 차단: 아래 missing(누락), unsupported(미지원), errors(불일치)를 수정하세요.')
    # [수정: UX 담당] 2026-09-28 case88 / 종류: 효율화 / 재현: 영문오류와포괄안내 / 전후: 목록→필드·원문위치표 / 왜: 안전한복구 / 영향: 값 자동수정없음.
    st.dataframe([{'수정할 필드':step['field_path'],'문제':step['issue'],
                   '원문 페이지':str(step['source_page']),'다음 행동':step['action']}
                  for step in report['next_steps']],hide_index=True)
    with st.expander('선택한 원문 근거 · 자동 수정 없음'):
        st.text(claim.source_quote or claim.text)
    st.json(report)
    st.download_button('제안 검토 결과 JSON', json.dumps(report, ensure_ascii=False, indent=2),
                       file_name='proposal_review.json', mime='application/json', key='proposal_result_'+claim.claim_id)

"""case105 team intake: explain usable evidence without turning it into approval."""
import json

import streamlit as st


# 작성: 총괄·UX | 2026-09-29 | 기존 검산기를 연결하고 팀 진술·서지·계산을 분리한다.
def render_team_materials():
    from core.team_case_intake import intake_summary, run_forest_intake

    with st.expander('새 팀 자료로 이해하기 · 산불·유통·추가 논문', expanded=False):
        st.markdown('**예시: “논문이 517건을 분석했다는데, 자료에도 517줄이 있을까?”**')
        st.write('산불 자료의 줄 수를 직접 셉니다. 숫자가 같아도 예측모형의 정확도나 연구 결론까지 맞다는 뜻은 아닙니다.')
        try:
            summary = intake_summary()
            st.caption('산불: 공개 자료와 논문 표본 수 연결 · 유통: 논문과 자료의 기간·대상 차이로 계산 보류')
            if st.button('산불 자료 517행 직접 확인', key='case105_forest_intake_run'):
                result = run_forest_intake()
                if result['action'] == 'ARITHMETIC_MATCH':
                    st.success('논문 표본 수 517건 = 자료 517행. 줄 수 검산은 일치했습니다.')
                    st.caption('517은 좋은 점수나 평균이 아니라 기록 개수입니다. 강수량 단위와 예측 성능은 확인되지 않았습니다.')
                elif result['action'] == 'ARITHMETIC_MISMATCH':
                    st.warning('논문 보고 수와 자료의 행 수가 다릅니다. 대상·버전·필터를 확인해야 합니다.')
                else:
                    st.error('입력 자료나 조건을 확인할 수 없어 계산을 보류했습니다.')
                with st.expander('현재 실행 결과와 입력 지문'):
                    st.json(result)
                st.download_button('산불 검산 근거 내려받기', json.dumps(result, ensure_ascii=False, indent=2),
                                   file_name='forest_intake_result.json', mime='application/json')
            with st.expander('산불·유통 자료의 사용 범위와 제한'):
                st.json(summary)
        except (ValueError, OSError, KeyError, TypeError, UnicodeError):
            st.error('팀 자료의 입력·지문을 확인할 수 없어 검산을 중단했습니다.')
        st.markdown('**추가 논문 20편**: 논문 근거 검색 → 서지 검색에서 찾을 수 있습니다. 이번 편입은 제목·DOI·출처 정보이며 본문 답변이나 계산 정답은 아닙니다.')
        st.markdown('**N3-11814 후속 자료**: 원문 위치와 공변량 의미 충돌 후보를 보강했습니다. 사람 확인 상태가 문서끼리 달라 팀 진술로 보관하며, 기존 16개 검토 업무는 미완료입니다.')
        st.caption('원자료를 공개 검색에 넣거나 모델 가중치를 재학습하지 않았습니다. 산불 강수량 단위 차이와 유통 PostCode 부재도 미해결로 남깁니다.')

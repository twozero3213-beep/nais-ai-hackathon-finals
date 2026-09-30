"""NTIS connection status without public project data disclosure."""
import os

import streamlit as st


def _configured():
    if os.environ.get('NTIS_API_KEY', '').strip():
        return True
    try:
        return bool(st.secrets.get('ntis', {}).get('api_key', '').strip())
    except Exception:
        return False


def render_ntis(actor):
    with st.expander('NTIS 국가 R&D 과제 찾기'):
        st.write('국가 R&D 과제 메타데이터 검색 서비스입니다. 논문 원문 검증 기능은 아닙니다.')
        st.info('연결 상태: 미검증. 현재 검색 기능을 제공하지 않습니다.')
        st.caption('운영 키 설정: ' + ('있음' if _configured() else '없음') + ' · 설정 여부는 API 이용 승인이나 접속 성공을 뜻하지 않습니다.')
        st.caption('확인한 NTIS 전체용 서비스는 신청기관 내부 활용을 안내합니다. 대국민용과 이용 조건이 다를 수 있어, 신청한 서비스와 공개 제공 가능 범위를 확인해야 합니다.')
        st.link_button('NTIS에서 원제공 정보 확인', 'https://www.ntis.go.kr/ThSearchProjectList.do')

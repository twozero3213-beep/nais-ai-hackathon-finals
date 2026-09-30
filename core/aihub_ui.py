"""case95 staged, manual AI Hub dataset discovery; no download or approval actions."""
import os
from urllib.parse import urlsplit

import streamlit as st

from core.research_tasks import SECRET_PATTERN
from core.research_tasks_ui import scoped_key, _time


def configured_key():
    """Presence only: the backend resolves the credential independently."""
    if os.environ.get('AIHUB_API_KEY', '').strip():
        return True
    try:
        return bool(st.secrets.get('aiHub', {}).get('api_key', '').strip())
    except Exception:
        return False


def search_datasets(query, limit=5):
    from core.aihub import search_datasets as search
    return search(query, limit=limit)


def official_url(value):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(char) < 32 for char in value):
        return ''
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == 'https' and parsed.hostname in {'aihub.or.kr', 'www.aihub.or.kr'}
                and not parsed.username and not parsed.password and parsed.port in {None, 443}):
            return value
    except ValueError:
        pass
    return ''


def _count(value):
    return str(value) if type(value) is int and value >= 0 else '미확인'


# [작성: AIHub UX 담당] 2026-09-29 case95 / 공개주제→수동5건카드·공식링크 / 검증: staged test_case95_aihub_ui, 조회·다운로드자동0.
def render_aihub(actor):
    with st.expander('AI Hub에서 연구용 데이터 찾기'):
        st.write('연구·AI 학습에 사용할 데이터셋을 찾습니다. 개별 논문의 인용순 검색과 다른 기능입니다.')
        query = st.text_input('공개 연구 주제', placeholder='예: 교육 · 기후 · 한국어', max_chars=200,
                              key=scoped_key(actor, 'aihub_query')).strip()
        st.caption('버튼을 누르면 공개 주제를 AI Hub에 전송합니다. 개인정보·비공개 자료는 입력하지 마세요.')
        configured = bool(configured_key())
        if not configured:
            st.info('AI Hub 연결 설정이 아직 없습니다. 운영자가 연결 설정을 추가하면 조회할 수 있습니다.')
        result_key = scoped_key(actor, 'aihub_result')
        signature = (query, configured)
        saved = st.session_state.get(result_key)
        if saved and saved.get('signature') != signature:
            st.session_state.pop(result_key, None)
        if st.button('AI Hub 데이터 찾기', key=scoped_key(actor, 'aihub_search'), width='stretch'):
            st.session_state.pop(result_key, None)
            if not query:
                st.info('찾고 싶은 공개 연구 주제를 입력하세요.')
            elif any(ord(char) < 32 or ord(char) == 127 for char in query) or SECRET_PATTERN.search(query):
                st.warning('공개 연구 주제만 입력하세요. 비공개 연결정보·제어문자가 포함된 입력은 전송하지 않습니다.')
            elif not configured:
                st.info('AI Hub 연결 설정 후 조회할 수 있습니다. 키를 이 화면에 입력할 필요는 없습니다.')
            else:
                try:
                    with st.spinner('AI Hub의 공개 데이터셋 정보를 조회합니다…'):
                        report = search_datasets(query, limit=5)
                    if not isinstance(report, dict) or not isinstance(report.get('items'), list):
                        raise ValueError('AIHUB_INVALID_RESPONSE')
                    st.session_state[result_key] = {'signature': signature, 'report': report}
                except (ValueError, OSError, TypeError, KeyError, ImportError):
                    st.error('AI Hub 정보를 조회하지 못했습니다. 연결 설정·서비스 상태를 확인하고 다시 눌러 주세요.')
        saved = st.session_state.get(result_key)
        if not saved or saved.get('signature') != signature:
            return
        report = saved['report']
        st.caption('사용 신청·승인 조건은 확인하지 않았습니다. 데이터 다운로드·신청·외부 메시지 발송은 자동으로 하지 않습니다.')
        st.caption('조회수·다운로드수는 데이터셋의 기록입니다. 논문 인용수나 데이터 품질·사용 가능 여부의 판정이 아닙니다.')
        items = report['items'][:5]
        if not items:
            st.info('이 주제에서 표시할 데이터셋이 없습니다. 다른 공개 주제로 다시 찾아보세요.')
        for item in items:
            link = official_url(item.get('url'))
            if not link:
                continue
            with st.container(border=True):
                st.text(str(item.get('title') or '제목 미확인'))
                st.caption('분야: ' + str(item.get('domain') or '미확인') + ' · 구축연도: ' + _count(item.get('year')))
                st.caption('조회수 ' + _count(item.get('views')) + ' · 다운로드 기록 ' + _count(item.get('download_count')))
                st.link_button('AI Hub에서 조건·데이터 확인', link)

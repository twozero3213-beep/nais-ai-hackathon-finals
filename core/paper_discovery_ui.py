"""case95 manual public-paper discovery with readable cards and task handoff."""
from urllib.parse import urlencode
import hashlib

import streamlit as st
from core.activity_privacy import activity_view, activity_detail

from core.paper_library_ui import public_url
from core.research_tasks_ui import scoped_key, get_store, STORE_ERRORS, _time

TOPICS = {'AI': ('AI · 인공지능', 'artificial intelligence'),
          'climate': ('기후·환경', 'climate adaptation'),
          'health': ('보건·건강', 'public health'),
          'economy': ('경제·사회', 'economic inequality'),
          'materials': ('소재·에너지', 'materials energy storage'),
          'education': ('교육·학습', 'education learning')}
MODES = {'최근 발행 논문': ('latest', 1), '최근 등록·갱신 논문': ('registered', 1),
         '최근 1년 발행 · 인용 많은 순': ('cited', 1), '최근 3년 발행 · 인용 많은 순': ('cited', 3)}
PROVIDER_LABELS = {'crossref': 'Crossref', 'openalex': 'OpenAlex', 'europepmc': 'Europe PMC'}


def search_papers(query, mode='latest', years=1, limit=8, institution=''):
    from core.paper_sources import search_resilient as search
    return search(query, mode=mode, years=years, limit=limit, institution=institution)


def get_institutions():
    from core.paper_discovery import INSTITUTIONS
    return INSTITUTIONS


def get_fields():
    from core.research_fields import FIELDS
    return FIELDS


# [작성: 탐색범위 UX 담당] 2026-09-29 case95 / 세부분야선택→검색어만입력,자동조회0 / 검증: test_case95_discovery_ui.
def _prefill_field(actor):
    chosen = st.session_state.get(scoped_key(actor, 'discovery_field'), '')
    field = get_fields().get(chosen)
    if field:
        st.session_state[scoped_key(actor, 'discovery_query')] = field['query']


def validate_query(query):
    from core.paper_discovery import validate_query as validate
    return validate(query)


# [수정: 0 이영 · Codex] 2026-10-01T02:53:50+09:00 — 번역을 끈 경우에는 준비 중이라고 표시하지 않는다. 출처 제목과 번역 초안의 역할을 구분한다.
def translation_enabled():
    try:
        from core.title_translation import enabled
        return enabled()
    except ImportError:
        return False


def korean_title(title, *, stored_draft=None):
    """Optional offline translation; keep the source title readable without it."""
    try:
        from core.title_translation import korean_title as translate
        return translate(title, stored_draft=stored_draft)
    except (ImportError, ValueError, OSError, TypeError):
        return None


def _save_paper(actor, item, on_task, signature):
    current_mode, current_years = MODES[st.session_state.get(scoped_key(actor, 'discovery_mode'), next(iter(MODES)))]
    current = (st.session_state.get(scoped_key(actor, 'discovery_query'), '').strip(), current_mode, current_years,
               st.session_state.get(scoped_key(actor, 'discovery_institution'), ''))
    if current != signature:
        st.warning('검색 조건이 바뀌었습니다. 논문을 다시 찾은 뒤 저장하세요.')
        return
    title = item['title']
    try:
        task = get_store().create(actor, '이 논문의 내용과 한계를 공개 근거로 검토해 주세요: ' + title[:950],
                                  query=title[:1000], doi=item['doi'], case_id='', daily_hour=None)
        st.session_state[scoped_key(actor, 'selected')] = task['id']
        st.session_state[scoped_key(actor, 'home_next')] = '예시·내 연구 과제'
        st.session_state[scoped_key(actor, 'notice')] = '논문을 검토 과제로 저장했습니다. 실행 시 선택 DOI 직접 근거와 관련 문헌을 구분합니다. 서지 조회만으로 선택 논문 원문을 검토한 것은 아닙니다. 무료 OA 원문 포함 실행은 별도 버튼으로 요청하세요.'
        if on_task is not None:
            on_task()
    except STORE_ERRORS:
        st.error('검토 과제를 저장하지 못했습니다. DOI·논문 제목과 과제 저장소 상태를 확인하세요.')


# [작성: 논문 탐색 UX 담당] 2026-09-29 case95
# 무엇·왜: 관심예시→수동공개검색→읽는카드→저장과제 연결 / 입력·출력: query·순서→현재Crossref서지 / 검증: test_case95_discovery_ui 조건변경·호출0/1·저장만.
def render_paper_discovery(actor, on_task=None):
    st.title('어떤 연구가 궁금하세요?')
    st.write('관심 분야를 고르거나 검색어를 적어보세요. 찾은 논문은 검토 과제로 이어갈 수 있습니다.')
    # case95: 연구 데이터 검색도 같은 시작 화면에 연결; 버튼 전에는 API 호출하지 않는다.
    from core.aihub_ui import render_aihub
    render_aihub(actor)
    query_key = scoped_key(actor, 'discovery_query')
    for offset in (0, 3):
        columns = st.columns(3)
        for column, (name, (label, query)) in zip(columns, list(TOPICS.items())[offset:offset + 3]):
            if column.button(label, key=scoped_key(actor, 'discovery_topic_' + name), width='stretch'):
                st.session_state[query_key] = query
    st.caption('시작을 돕는 주제 예시입니다. 검색량으로 매긴 인기 순위는 아닙니다.')
    fields = get_fields()
    st.selectbox('다른 분야 찾아보기', ['', *fields],
                 format_func=lambda key: '세부분야 예시 30개 · 선택사항' if not key else fields[key]['group'] + ' · ' + fields[key]['label'],
                 key=scoped_key(actor, 'discovery_field'), on_change=_prefill_field, args=(actor,))
    st.caption('분야 선택은 검색어만 채웁니다. 목록에 없는 분야도 아래에 직접 입력할 수 있습니다.')
    query = st.text_input('논문 검색어', placeholder='예: climate adaptation · machine learning',
                          max_chars=300, key=query_key).strip()
    label = st.radio('어떤 논문부터 볼까요?', list(MODES), key=scoped_key(actor, 'discovery_mode'))
    mode, years = MODES[label]
    try:
        institutions = get_institutions()
    except (ValueError, TypeError, ImportError):
        institutions = {}
    institution_key = scoped_key(actor, 'discovery_institution')
    if st.session_state.get(institution_key, '') not in ['', *institutions]:
        st.session_state[institution_key] = ''
    with st.expander('대학·연구기관으로 좁히기 · 선택사항'):
        institution = st.selectbox('논문에 기록된 저자 소속', ['', *institutions],
                                   format_func=lambda value: '전체 기관' if not value else institutions[value]['label'],
                                   key=institution_key)
        st.caption('등록된 저자 소속이 선택 기관과 일치하는 논문만 표시합니다. 교수 신원 확인이나 대학 전체의 성과 순위는 아닙니다.')
    st.caption('검색 버튼을 누를 때만 검색어를 무료 공개 논문 API로 전송합니다. 개인정보·비공개 자료는 입력하지 마세요.')
    result_key = scoped_key(actor, 'discovery_result')
    signature = (query, mode, years, institution)
    saved = st.session_state.get(result_key)
    if saved and saved['signature'] != signature:
        st.session_state.pop(result_key, None)
    if st.button('논문 찾기 · 새로고침', type='primary', key=scoped_key(actor, 'discovery_search'), width='stretch'):
        st.session_state.pop(result_key, None)
        if not query:
            st.info('관심 분야를 고르거나 검색어를 입력하세요.')
        else:
            try:
                with st.spinner('공개 논문 정보를 지금 조회합니다…'):
                    report = search_papers(query, mode=mode, years=years, limit=8, institution=institution)
                st.session_state[result_key] = {'signature': signature, 'report': report}
            except (ValueError, OSError, KeyError, TypeError, ImportError):
                st.error('논문을 조회하지 못했습니다. 검색어·무료 API 연결을 확인하고 다시 눌러 주세요. 비공개 연결정보가 포함된 검색어는 전송하지 않습니다.')
    with st.expander('검색 순서와 인용수는 무슨 뜻인가요?'):
        st.write('최근 발행: Crossref에 기록된 발행일이 최신인 순서입니다. 최근 등록·갱신: 서지 등록 순서이며 오래전에 발행한 논문도 나타날 수 있습니다.')
        st.write('최근 1년·3년 인용순: 그 기간에 발행한 논문의 현재 누적 인용 기록으로 정렬합니다. 그 기간 동안 받은 인용수와 다릅니다. 인용이 많아도 연구의 정확성이나 효과가 입증된 것은 아닙니다.')
        st.write('실시간은 조회 시점의 공개 서지 정보를 뜻합니다. 기본 출처는 Crossref이며 연결 오류 시 조건에 맞는 대체 출처를 사용할 수 있습니다. 세계 전체 논문이나 원문을 모두 확보한 것은 아닙니다. 자동 조회는 하지 않습니다.')
    try:
        external_query = validate_query(query)
    except (ValueError, OSError, TypeError, ImportError):
        external_query = ''
    if external_query:
        with st.expander('다른 논문 검색 서비스에서 찾아보기'):
            st.link_button('Google Scholar 열기', 'https://scholar.google.com/scholar?' + urlencode({'q': external_query}))
            st.link_button('네이버 학술검색 열기', 'https://academic.naver.com/search.naver?' + urlencode({'query': external_query}))
            st.caption('외부 검색 페이지를 엽니다. 이 앱에서 두 서비스의 검색 결과를 수집한 것은 아닙니다.')
    saved = st.session_state.get(result_key)
    if not saved or saved['signature'] != signature:
        return
    report = saved['report']
    provider = PROVIDER_LABELS.get(report.get('provider', 'crossref'), '공개 출처')
    st.caption('버튼으로 조회한 공개 서지 기록입니다. 현재 내용은 다시 조회해 확인할 수 있습니다.')
    st.caption(f'출처: {provider} · 인용수는 이 출처의 현재 누적 기록입니다. 연구의 참·거짓이나 정상 범위를 판단하는 수치가 아닙니다.')
    if report.get('fallback_used'):
        st.info(f'기본 출처 연결에 문제가 있어 {provider} 결과를 표시합니다. 출처별 인용 기록은 합산하지 않습니다.')
    items = report.get('items', [])
    st.subheader(f'찾은 논문 {len(items)}편')
    with st.expander('검색 범위·빠진 결과 확인'):
        st.text(str(report.get('scope', '')))
        for limitation in report.get('limitations', []):
            st.text(str(limitation))
        with st.expander('고급 · 조회 출처·응답 기록'):
            st.json(activity_view(report))
    if not items:
        st.info('이 조건에서 표시할 논문이 없습니다. 검색어를 바꾸거나 다른 순서를 선택해 다시 찾아보세요.')
    for position, item in enumerate(items, 1):
        with st.container(border=True):
            if mode == 'cited':
                st.caption(f'{position}위 · 이번 {provider} 응답 안에서의 누적 인용순')
            st.subheader(item['title'])
            # [수정: 0 이영 · Codex] 2026-10-01T03:19:13+09:00 — 저장된 번역도 같은 운영 설정·깨진 출력 검사를 거친다. 원제목은 위에 그대로 표시한다.
            translated = korean_title(item['title'], stored_draft=item.get('title_ko'))
            # [수정: 0 이영 · Codex] 2026-10-01T02:53:50+09:00 — 원제목을 중복 표시하거나 미실행 번역을 준비 중으로 안내하지 않는다. 출력 검사는 의미 정확성을 보증하지 않는다.
            if translated and translated != item['title']:
                st.caption("기계 번역 초안 · 오역 가능성이 있으니 원제목과 대조하세요")
                st.write(translated)
            elif translation_enabled() and not translated:
                st.caption('한국어 번역 없음 · 원제목 기준으로 확인하세요')
            st.caption('발행일 ' + str(item.get('published') or '미확인') + ' · ' + str(item.get('journal') or '학술지 미확인'))
            if item.get('registered_at'):
                st.caption(provider + ' 등록 시각: ' + _time(item['registered_at']))
            if item.get('affiliations'):
                st.caption('기록된 저자 소속: ' + ' · '.join(item['affiliations']))
            citations = item.get('citations')
            st.write(provider + ' 누적 인용 ' + (str(citations) + '회' if citations is not None else '미확인'))
            source = public_url(item.get('url'))
            if source:
                st.link_button('논문 출처 열기', source)
            paper_key = hashlib.sha256((item['doi'] + repr(signature)).encode('utf-8')).hexdigest()[:20]
            st.button('이 논문을 검토 과제로 저장', key=scoped_key(actor, 'discovery_save_' + paper_key),
                      on_click=_save_paper, args=(actor, item, on_task, signature))

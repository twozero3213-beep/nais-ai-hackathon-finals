"""Manual, actor-scoped public data exploration; never downloads data or approves claims."""
from urllib.parse import urlsplit

import streamlit as st

from core.paper_discovery import _plain
from core.paper_library_ui import public_url
from core.research_data_sources import COLLECTIONS, INDICATORS
from core.research_tasks import SECRET_PATTERN
from core.research_tasks_ui import scoped_key, _time

CATEGORIES = {'전체': None, '공공 통계': {'public', 'statistics'},
              '위성·환경': {'satellite'}, '연구 데이터': {'datasets'}}
MODE_LABELS = {'catalog': '자료 목록 찾기', 'items': '위성 촬영정보 보기',
               'observations': '한국 지표값 보기'}
COLLECTION_LABELS = {'sentinel-2-l2a': 'Sentinel-2 · L2A',
                     'sentinel-2-c1-l2a': 'Sentinel-2 · Collection 1 L2A',
                     'landsat-c2-l2': 'Landsat · Collection 2 L2'}
INDICATOR_LABELS = {'SP.POP.TOTL': '인구 · 사람 수',
                    'NY.GDP.MKTP.CD': '국내총생산(GDP) · 현재 미 달러',
                    'SP.DYN.LE00.IN': '출생 시 기대수명 · 년'}
ACCESS_LABELS = {
    'metadata public; data access unknown': '설명 정보 공개 · 원자료 접근 조건 미확인',
    'metadata public; asset terms require review': '설명 정보 공개 · 영상 이용 조건 확인 필요',
    'public API metadata': '공개 API의 자료 설명',
    'public API observation': '공개 API의 연도별 지표값',
    'public event observations': '공개 지진 이벤트 기록',
    'DOI metadata public; dataset access unknown': 'DOI 설명 정보 공개 · 원자료 접근 조건 미확인',
}
EXAMPLES = {
    'kci': '국내 학술논문을 찾고 싶어요 → 제목 검색어: 인공지능 또는 기후',
    'aida': '국내 연구 데이터셋을 찾고 싶어요 → 검색어: 논문 (서비스 승인·접근권한 필요)',
    'nasa_cmr': '위성 관측 자료의 범위가 궁금해요 → 검색어: precipitation',
    'earth_search': '한국 근처 Sentinel-2 촬영정보가 궁금해요 → 위성 촬영정보 보기 · 한국 주변 · 최근 7일',
    'world_bank': '한국 인구의 연도별 값이 궁금해요 → 한국 지표값 보기 · 인구',
    'usgs': '한국 주변 최근 지진이 궁금해요 → 한국 주변 · 최근 7일',
    'datacite': '연구 데이터 DOI가 궁금해요 → 검색어: climate',
    'data_gov': '공공 환경 데이터가 궁금해요 → 검색어: air quality',
    'korea_data': '한국 인구·환경 공공데이터가 궁금해요 → 검색어: 인구 또는 대기질',
}


def source_catalog():
    from core.research_data_sources import source_catalog as catalog
    return catalog()


def search_research_data(source, query='', limit=5, **options):
    from core.research_data_sources import search_research_data as search
    return search(source, query, limit, **options)


def _text(value, fallback='미확인'):
    """Reuse the existing plain-text/secret guard; provider markup is never Markdown."""
    if value is None or value == 'unknown' or isinstance(value, (dict, list, bool)):
        return fallback
    try:
        return _plain(str(value), 1200)
    except (ValueError, TypeError):
        return fallback


def _link(value):
    # Reuse public_url, adding credential/control checks for external provider links.
    if not isinstance(value, str) or len(value) > 2000 or SECRET_PATTERN.search(value):
        return ''
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return ''
    try:
        parsed = urlsplit(value)
        return public_url(value) if parsed.scheme == 'https' and not parsed.username and not parsed.password else ''
    except ValueError:
        return ''


def _filters(source, mode):
    supported = source.get('supported_filters', {})
    return set(supported.get(mode, [])) if isinstance(supported, dict) else set(supported)


def _card(item, source):
    with st.container(border=True):
        st.text(_text(item.get('title'), '제목 미확인'))
        kind = item.get('data_kind')
        st.caption('실제 관측·지표값' if kind == 'observation' else '자료 설명·목록 정보')
        origin = source.get('label') if item.get('source') == source.get('id') else item.get('source')
        st.text('출처: ' + _text(origin, _text(source.get('label'))))
        # case105: reuse plain text; provider update date is separate from data period.
        if item.get('provider'): st.text('제공기관: ' + _text(item['provider']))
        if item.get('updated_at'): st.text('목록 수정일: ' + _text(item['updated_at']))
        if item.get('provider_license_code') not in (None, 'unknown'):
            st.caption('이용허락 코드: ' + _text(item['provider_license_code']) + ' · 의미와 전문은 원제공 페이지에서 확인하세요.')
        st.text('지역 범위: ' + _text(item.get('spatial')))
        st.text('자료 기간: ' + _text(item.get('temporal')))
        st.text('이용 조건: ' + _text(item.get('license')))
        access = _text(item.get('access'))
        st.text('접근 방식: ' + ACCESS_LABELS.get(access, access))
        if kind == 'observation':
            st.text('제공 값: ' + _text(item.get('value')) + ' · 단위: ' + _text(item.get('unit')))
            if item.get('unit_source') == 'indicator_definition':
                st.caption('단위는 제공 응답에서 누락되어 공식 지표 정의로 표시했습니다. 원제공 지표 설명을 함께 확인하세요.')
        st.write('다음 행동: 원제공 화면에서 단위·대상·기간을 확인한 뒤 비교하세요.' if kind == 'observation'
                 else '다음 행동: 원제공 화면에서 자료 범위와 이용 조건을 확인하세요.')
        with st.expander('자료 설명·식별자 보기'):
            st.text(_text(item.get('description'), '제공된 설명 없음'))
            st.text('식별자: ' + _text(item.get('id')))
        link = _link(item.get('url'))
        if link:
            st.link_button('원제공 자료·이용 조건 열기', link)


# [작성: 데이터 UX] case100 / 기존 actor키·시간·plain 도우미 재사용; 명시 버튼 외 조회0.
def render_research_data(actor):
    st.title('연구에 쓸 공개 데이터 찾기')
    st.write('공공 통계, 위성·환경 관측, 연구 데이터 DOI를 찾아 원제공 자료로 이동합니다.')
    st.info('자료 목록은 데이터의 설명입니다. 관측·지표값은 제공된 기록입니다. 어느 쪽도 논문의 검토 완료나 연구 결론의 확인을 뜻하지 않습니다.')
    with st.expander('처음이라면 · 질문 예시와 읽는 순서'):
        st.write('① 궁금한 자료 종류를 고릅니다. ② 출처와 조건을 선택합니다. ③ 찾기 버튼을 누릅니다. ④ 카드의 지역·기간·단위·이용 조건을 확인합니다.')
        for example in EXAMPLES.values():
            st.text(example)
        st.caption('위성 영상·대용량 원자료는 내려받지 않습니다. 영어 제목은 원제목이며 자동 번역하거나 데이터의 타당성을 판정하지 않습니다.')
    result_key = scoped_key(actor, 'data_result')
    try:
        catalog = source_catalog()
        if not isinstance(catalog, list) or not catalog or any(not isinstance(s, dict) for s in catalog):
            raise ValueError()
    except (ValueError, TypeError, OSError, ImportError):
        st.session_state.pop(result_key, None)
        st.error('자료 출처 목록을 표시하지 못했습니다. 잠시 후 다시 열어 주세요.')
        return
    # case100: horizontal choices reduce scrolling; Streamlit wraps them on narrow screens.
    category = st.radio('어떤 자료가 필요한가요?', list(CATEGORIES), horizontal=True, key=scoped_key(actor, 'data_category'))
    allowed = CATEGORIES[category]
    choices = [s for s in catalog if allowed is None or s.get('category') in allowed]
    if not choices:
        st.session_state.pop(result_key, None)
        st.info('이 종류에서 사용할 출처가 없습니다.')
        return
    lookup = {s['id']: s for s in choices}
    source_key = scoped_key(actor, 'data_source')
    if st.session_state.get(source_key) not in lookup:
        st.session_state[source_key] = next(iter(lookup))
    source_id = st.selectbox('자료 출처', list(lookup), format_func=lambda x: _text(lookup[x].get('label'), x), key=source_key)
    source = lookup[source_id]
    st.caption(_text(source.get('notice'), '공식 자료의 설명과 이용 조건을 확인하세요.'))
    st.caption(EXAMPLES.get(source_id, '원제공 자료의 범위와 조건을 확인하세요.'))
    needs_key = source.get('status') == 'NEEDS_KEY'
    if needs_key:
        st.warning('NEEDS_KEY · 연결 설정 필요. 현재 연결된 출처가 아닙니다. 공식 안내에서 접근 조건을 확인하세요.')
    else:
        st.caption('공개 조회 경로 제공 · 버튼으로 조회한 뒤 성공 여부를 확인합니다.')
    source_links = st.columns(2)
    for column, (field, label) in zip(source_links, [('url', '공식 제공 사이트 열기'), ('docs_url', '공식 API·접근 안내 열기')]):
        link = _link(source.get(field))
        if link:
            column.link_button(label, link)
    modes = source.get('modes') or ['catalog']
    mode_key = scoped_key(actor, 'data_mode_' + source_id)
    mode = st.selectbox('조회할 내용', modes,
                        format_func=lambda x: '지진 관측값 보기' if source_id == 'usgs' else MODE_LABELS.get(x, x), key=mode_key)
    supported = _filters(source, mode)
    options = {'mode': mode}
    query = ''
    if 'query' in supported:
        query = st.text_input('공개 검색어', max_chars=200, placeholder='예: climate · precipitation',
                              key=scoped_key(actor, 'data_query_' + source_id)).strip()
    else:
        st.caption('이 조회는 검색어를 사용하지 않습니다. 아래 지원 조건만 적용합니다.')
    if 'region' in supported:
        options['region'] = st.selectbox('지역 범위', ['global', 'korea'],
            format_func=lambda x: '전 세계' if x == 'global' else '한국 주변 · 경계 상자', key=scoped_key(actor, 'data_region_' + source_id))
        st.caption('한국 주변 경계 상자는 행정구역과 정확히 같지 않습니다.')
    if 'days' in supported:
        options['days'] = st.select_slider('최근 며칠을 볼까요?', options=[1, 3, 7, 14, 30], value=7,
                                          key=scoped_key(actor, 'data_days_' + source_id))
    if 'collection' in supported:
        options['collection'] = st.selectbox('위성 자료 묶음', list(COLLECTIONS),
            format_func=lambda x: COLLECTION_LABELS.get(x, x), key=scoped_key(actor, 'data_collection_' + source_id))
        st.caption('촬영정보와 원제공 링크를 표시합니다. 영상 픽셀값을 읽거나 분석하지 않습니다.')
    if 'indicator' in supported:
        options['indicator'] = st.selectbox('한국 지표', list(INDICATORS), format_func=lambda x: INDICATOR_LABELS.get(x, x),
                                            key=scoped_key(actor, 'data_indicator_' + source_id))
        st.caption('국가 범위는 한국(KOR)으로 고정됩니다. 개별 사람의 기록이나 정상 범위가 아닙니다.')
    signature = (source_id, source.get('status'), query, tuple(options.items()))
    saved = st.session_state.get(result_key)
    if saved and saved.get('signature') != signature:
        st.session_state.pop(result_key, None)
    st.caption('버튼을 누르면 위 조건만 원제공 API로 전송합니다. 개인정보·비공개 자료·연결정보는 입력하지 마세요. 최대 5건을 표시합니다.')
    if st.button('선택한 출처에서 자료 찾기', type='primary', disabled=needs_key,
                 width='stretch', key=scoped_key(actor, 'data_search')):
        st.session_state.pop(result_key, None)
        if SECRET_PATTERN.search(query) or any(ord(c) < 32 or ord(c) == 127 for c in query):
            st.warning('공개 검색어만 입력하세요. 비공개 연결정보가 포함된 입력은 전송하지 않습니다.')
        else:
            try:
                with st.spinner('선택한 출처에서 자료를 확인합니다…'):
                    report = search_research_data(source_id, query, limit=5, **options)
                if not isinstance(report, dict) or not isinstance(report.get('items'), list):
                    raise ValueError()
                if report.get('status') not in {'OK', 'EMPTY', 'NEEDS_KEY', 'ERROR'}:
                    raise ValueError()
                st.session_state[result_key] = {'signature': signature, 'report': report}
            except Exception:
                # Provider errors can include URLs/credentials; never echo exception or raw payload.
                st.error('자료를 조회하지 못했습니다. 출처의 서비스 상태와 공식 안내를 확인한 뒤 다시 눌러 주세요.')
    saved = st.session_state.get(result_key)
    if not saved or saved.get('signature') != signature:
        return
    report = saved['report']
    # case105: sanitized adapter codes preserve permission/network distinctions.
    if report.get('status') == 'ERROR':
        errors = {'AUTH_REQUIRED': '인증 실패 · 키와 해당 서비스 이용신청 상태를 확인하세요.',
                  'PERMISSION_DENIED': '서비스 권한 거부 · 이 검색 API의 이용승인 상태를 확인하세요.',
                  'RATE_LIMITED': '조회 한도 초과 · 잠시 후 다시 조회하세요.',
                  'TIMEOUT': '응답 시간 초과 · 잠시 후 다시 조회하세요.',
                  'UNAVAILABLE': '출처 연결 실패 · 네트워크와 서비스 상태를 확인하세요.',
                  'HTTP_ERROR': '출처 HTTP 오류 · 공식 서비스 상태를 확인하세요.',
                  'INVALID_KEY': '인증키 설정 형식 오류 · 비공개 설정을 확인하세요.',
                  'INVALID_RESPONSE': '출처 응답 형식 오류 · 결과를 표시할 수 없습니다.',
                  'RESPONSE_TOO_LARGE': '출처 응답이 허용 크기를 초과했습니다.'}
        st.error(errors.get(report.get('error'), '자료를 조회하지 못했습니다. 공식 안내를 확인하세요.'))
        return
    if report.get('status') == 'NEEDS_KEY':
        st.warning('NEEDS_KEY · 연결 설정 필요. 조회에 성공한 출처가 아닙니다.')
        return
    st.caption(_text(report.get('notice'), '일부 검색 결과이며 전체 자료 수집이나 검증된 데이터 판정이 아닙니다.'))
    if not report['items']:
        st.info('이 조건에서 표시할 자료가 없습니다. 기간·검색어를 바꾸어 다시 찾아보세요. 자료가 전혀 없다는 뜻은 아닙니다.')
    for item in report['items'][:5]:
        if isinstance(item, dict):
            _card(item, source)

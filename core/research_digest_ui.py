"""case95 readable, read-only scheduled snapshots; no source API or model calls."""
from datetime import date, datetime, timedelta, timezone
import re
from urllib.parse import quote

import streamlit as st

from core.research_tasks_ui import scoped_key
from core.research_fields import FIELDS
from core.paper_discovery_ui import korean_title, PROVIDER_LABELS

ENTRY_LABELS = {'papers:' + key: field['group'] + ' · ' + field['label'] for key, field in FIELDS.items()}
ENTRY_LABELS.update({'news:mit': 'MIT 연구 소식', 'news:kaist': 'KAIST 연구 소식', 'news:harvard': 'Harvard 연구 소식'})
TOPIC_QUERIES = {'papers:' + key: field['query'] for key, field in FIELDS.items()}
KST = timezone(timedelta(hours=9))


def utc_now():
    return datetime.now(timezone.utc)


def load_digest():
    from core.research_digest_remote import load_digest as load
    return load()


# [작성: 자동피드 UX 담당] 2026-09-29 case95
# 무엇·왜: 미래·무시간대 날짜로 신선도 주장 방지 / 입력·출력: ISO시각→KST·경과시간/미확인 / 검증: test_case95_digest_ui.
def timestamp_display(value, now=None):
    now = now or utc_now()
    try:
        if not isinstance(value, str):
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None or parsed > now:
            raise ValueError()
        return parsed.astimezone(KST).strftime('%Y-%m-%d %H:%M') + ' 한국시간', now - parsed
    except (ValueError, TypeError, OverflowError):
        return '시각 미확인', None


def _paper_date(value):
    try:
        parsed = date.fromisoformat(str(value))
        if parsed > utc_now().astimezone(KST).date():
            raise ValueError()
        return parsed.isoformat()
    except (ValueError, TypeError):
        return '발행일 미확인'


def _paper_link(item):
    doi = item.get('doi')
    if not isinstance(doi, str) or len(doi) > 200 or not re.fullmatch(r'10\.\d{4,9}/[^\s]+', doi):
        return ''
    return 'https://doi.org/' + quote(doi, safe='/')


def _open_topic(actor, query):
    st.session_state[scoped_key(actor, 'discovery_query')] = query[:200]
    st.session_state[scoped_key(actor, 'home_next')] = '논문 둘러보기'


# [작성: 자동피드 UX 담당] 2026-09-29 case95
# 무엇·왜: 예약조회 snapshot을 최신실검색과 구분 / 입력·출력: 원격/보관digest→최대3카드·신선도·수동검색 / 검증: test_case95_digest_ui, 원본API0.
def render_digest(actor, kind='papers'):
    if kind not in {'papers', 'news'}:
        raise ValueError('Unsupported digest kind')
    st.subheader('보관된 연구')
    # [수정: 0 이영] 2026-10-01 00:07 KST — 예약 수집 미설정 상태를 보관 조회와 구분한다.
    st.caption('저장된 조회 결과입니다. 정기 수집은 아직 연결되지 않았습니다. 직접 검색으로 현재 결과를 확인할 수 있습니다.')
    try:
        digest, source_label, error_code = load_digest()
    except (ValueError, OSError, KeyError, TypeError, ImportError):
        digest, source_label, error_code = None, '', 'UNAVAILABLE'
    if not isinstance(digest, dict) or not isinstance(digest.get('entries'), list):
        st.info('아직 표시할 자동 수집 기록이 없습니다. 위의 직접 검색·조회 기능을 사용할 수 있습니다.')
        return
    if error_code:
        st.warning('최근 원격 갱신을 확인하지 못해 보관된 묶음을 표시합니다. 보관 결과의 갱신 상태를 확인하세요.')
    if source_label:
        st.caption(str(source_label))
    options = [key for key in ENTRY_LABELS if key.startswith(kind + ':')]
    default = 'papers:computing' if kind == 'papers' else 'news:mit'
    chosen = st.selectbox('자동 수집 주제' if kind == 'papers' else '자동 수집 대학 소식', options,
                          index=options.index(default), format_func=lambda key: ENTRY_LABELS[key],
                          key=scoped_key(actor, 'digest_selection_' + kind))
    entries = {entry['id']: entry for entry in digest['entries'] if isinstance(entry, dict) and isinstance(entry.get('id'), str)}
    entry = entries.get(chosen)
    if not isinstance(entry, dict) or entry.get('kind') != kind:
        st.info('선택한 주제의 보관 기록을 확인하지 못했습니다. 직접 검색할 수 있습니다.')
        return
    _, age = timestamp_display(entry.get('last_success_at'))
    if age is None:
        st.caption('수집 시각 미확인 · 갱신 상태 확인 필요')
        st.warning('성공 시각을 확인하지 못했습니다. 이 보관 내용을 최신 결과로 해석하지 마세요.')
    elif age > timedelta(hours=15):
        st.warning('마지막 성공 이후 15시간이 넘었습니다. 오래된 보관 결과일 수 있습니다.')
    data = entry.get('data')
    if entry.get('status') == 'error':
        st.warning('최근 수집에 실패해 이전 성공 결과를 보존해 표시합니다.' if data else '최근 수집을 완료하지 못했습니다. 아직 보관된 성공 결과가 없습니다.')
    query = TOPIC_QUERIES.get(chosen, '')
    if kind == 'papers' and isinstance(data, dict):
        query = data.get('query') or query
    elif kind == 'news' and isinstance(data, dict):
        articles = data.get('articles', [])
        if articles:
            query = next(iter(articles[0].get('categories', [])), '') or articles[0].get('title', '')
    query = query or ENTRY_LABELS[chosen]
    st.button('이 주제로 직접 검색', key=scoped_key(actor, 'digest_open_' + kind),
              on_click=_open_topic, args=(actor, query))
    st.caption('보관한 공개 메타데이터입니다. 주제 예시는 세계 연구 트렌드나 인기 순위를 뜻하지 않습니다.')
    if not isinstance(data, dict):
        return
    rows = data.get('items' if kind == 'papers' else 'articles', [])
    if not rows:
        st.info('이 보관 응답에는 표시할 항목이 없습니다. 직접 조회에서 다른 검색어·조건을 사용할 수 있습니다.')
    for row in rows[:3]:
        if kind == 'papers':
            link = _paper_link(row)
        else:
            from core.research_news import _safe_article_link
            link = _safe_article_link(row.get('link'), chosen.removeprefix('news:'))
        if not link:
            continue
        with st.container(border=True):
            st.text(str(row.get('title') or '제목 미확인'))
            if kind == 'papers':
                translated = row.get('title_ko') or korean_title(row.get('title', ''))
                if translated:
                    st.caption("한국어 참고 번역 · 학술 용어 확인 필요")
                    st.write(translated)
                else:
                    st.caption('한국어 번역 준비 중')
                st.caption('발행일 ' + _paper_date(row.get('published')) + ' · ' + str(row.get('journal') or '학술지 미확인'))
                count = row.get('citations')
                provider = PROVIDER_LABELS.get(data.get('provider', 'crossref'), '공개 출처')
                st.caption('보관 당시 ' + provider + ' 누적 인용 ' + (str(count) + '회' if type(count) is int and count >= 0 else '미확인'))
            else:
                published, _ = timestamp_display(row.get('published'))
                st.caption('소식 발행: ' + published)
            st.link_button('논문 출처 열기' if kind == 'papers' else '대학 공식 소식 열기', link)

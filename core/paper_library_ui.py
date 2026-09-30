"""Read-only paper evidence search; never creates or approves analysis claims."""
import hashlib
import json
from urllib.parse import urlparse

import streamlit as st
from core.paths import PROJECT_ROOT
from core.research_corpus import search_corpus, strict_json, read_correction_pair, load_team_metadata


# [작성:전문가1·4] 2026-09-27 case68 목적: 깨진 색인도 오류 안내로 종료; 입력: 파싱한 corpus; 출력: 표시용 계수; 검증: 객체·정수·합계·split 구조 검사.
def display_summary(corpus):
    if not isinstance(corpus,dict) or not isinstance(corpus.get('summary'),dict):raise ValueError('Invalid corpus summary')
    summary=corpus['summary'];splits=summary.get('splits')
    if not isinstance(splits,dict) or set(splits)!={'development','validation'}:raise ValueError('Invalid split summary')
    values=[summary.get(key) for key in ['records','fulltext','bibliography_only']]+list(splits.values())
    if any(type(value) is not int or value<0 for value in values):raise ValueError('Invalid summary count')
    if summary['fulltext']+summary['bibliography_only']!=summary['records'] or sum(splits.values())!=summary['records']:raise ValueError('Inconsistent summary count')
    return summary


# [작성:전문가1·4] 2026-09-27 case68 목적: 안전한 공식 링크 표시; 입력: URL; 출력: HTTP(S) 링크 또는 빈값; 검증: 스킴·host 없는 링크 차단.
def public_url(value):
    parsed=urlparse(str(value or ''))
    return str(value) if parsed.scheme in {'http','https'} and parsed.hostname else ''


# [작성: 자료통합·UX 담당] 2026-09-28 case83
# 무엇을: 팀원 추가 서지 별도 열람 / 왜: 원문·재현 수의 허위 증가 방지 / 입력·출력: inventory -> 후보표 / 검증: test_case83_integration.
def _team_candidates():
    with st.expander('팀원 추가 참고자료 · 원문 미확보 후보'):
        try:
            raw=(PROJECT_ROOT/'data/research_fields/team_candidate_inventory.json').read_bytes()
            inventory=strict_json(raw)
            records=inventory['records']
            if not isinstance(records,list) or any(not isinstance(row,dict) or row.get('is_fulltext') is not False or not isinstance(row.get('title'),str) for row in records):
                raise ValueError('Invalid candidate inventory')
            st.caption(f'참고 레코드 {len(records)}개 · 이 추가 목록의 신규 원문 확보 0건. 논문·정책·도구가 섞여 있으며 기존 본문 검색 색인과 별도입니다.')
            query=st.text_input('팀원 후보 제목 검색',key='team_candidate_query').strip().casefold()
            rows=[{'제목':row['title'],'종류':row.get('record_type','candidate'),
                   '상태':'서지 후보 · 원문 미확인','원제공 링크':public_url(row.get('url'))}
                  for row in records if query in row['title'].casefold()]
            st.dataframe(rows,hide_index=True)
            st.warning('후보의 제목·링크를 모두 검증한 것은 아닙니다. 원문·원자료·분석조건을 확보하기 전에는 실행 근거로 사용하지 않습니다.')
            st.download_button('팀원 후보·검토 기록 JSON',raw,file_name='team_candidate_inventory.json',mime='application/json')
        except (OSError,ValueError,KeyError,TypeError):
            st.info('팀원 후보 목록을 확인할 수 없습니다. 기존 본문 검색은 별도로 사용할 수 있습니다.')


# [작성:전문가1·4] 2026-09-27 case68 목적: 근거 후보와 분석 승인 분리; 입력: 검증된 검색 결과; 출력: 출처·본문·인용 표시; 검증: 메타데이터를 본문으로 표시하지 않음.
# [수정:전문가4·7] 2026-09-27 case69 / 종류:검증방법추가 / 재현방법: 확장 후보 출처 표시 / 변경전: 단락·서지만 표시 / 변경후: 표·경계·확장어와 실제 범위 표시 / 왜: 근거 수준 구분 / 영향: 자동 승인·분석 없음.
def render_result(result, index):
    st.subheader(f"{index}. {result['title']}")
    if result.get('title_ko_unverified'):
        st.caption('한국어 제목 · 미검토 번역 초안')
        st.text(result['title_ko_unverified'])
    if result['evidence_level']=='BIBLIOGRAPHY_ONLY':
        st.info('서지 후보 · 이 결과는 원문 단락 근거가 아닙니다.')
    elif result['evidence_level']=='TABLE_CANDIDATE':
        st.caption('표 텍스트 후보 · 셀 병합·행열 관계·통계값을 자동 해석하지 않습니다.')
    elif result['evidence_level']=='BOUNDARY_CANDIDATE':
        st.caption('경계 문맥 후보 · 서로 다른 조각/문단의 일부이며 하나의 주장으로 합성한 것이 아닙니다.')
    else:
        st.caption('원문 단락 후보 · 분석 적격성 미확정')
    st.text(result['text'])
    st.caption(f"분야: {result['field']} · 구분: {result['split']} · rank_score: {result['rank_score']} (검색 순위 점수, 확률 아님)")
    st.text('DOI: '+result['doi'])
    source=public_url(result.get('source_url'))
    if source:st.link_button('논문 출처 열기',source)
    with st.expander('인용 위치와 무결성 근거'):
        st.json({key:result.get(key) for key in ['doi','source_path','locator','source_sha256','source_url','evidence_level']})
        # [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 확장검색 근거와 원위치 공개 / 입력·출력: result→표시 / 검증: test_case69_ui.
        if result.get('retrieval_options'):
            st.json({key:result.get(key) for key in ['retrieval_options','source_locators','source_ranges','expanded_terms','synonym_source','match_basis','table_interpretation']})
        # [수정: 0 이영 · Codex] 2026-10-01T03:04:44+09:00 — 논문 검색 안내의 전문어를 한국어 주장으로 통일한다.
        st.caption('표시한 파일·위치·해시는 검색 시 대조한 출처입니다. 원자료 다운로드·분석 재현·주장 승인이 아닙니다.')


# [작성:전문가1·4] 2026-09-27 case68 목적: 실제900 자료를 읽기 검색에 연결; 입력: 사용자 검색어/자료구분; 출력: 검증된 후보; 검증: 기본 development·오류 시 이전 결과 폐기·Claim 상태 불변.
# [수정:전문가4·7] 2026-09-27 case69 / 종류:검증방법추가 / 재현방법: 검색 후 옵션 변경 / 변경전: 확장 선택 없음 / 변경후: 기본off 옵션과 signature 결속 / 왜: 이전 결과 혼동 차단 / 영향: 기본 검색 유지.
# [작성: 자료통합·UX 담당] 2026-09-28 case86
# 무엇을: 원논문·공지 별도 열람 / 왜: 오류 후보 수집을 재계산 성공과 구분 / 입력·출력: 178후보 -> 선택한 쌍의 검증 원문 / 검증: test_case86 화면·전수검사.
def _correction_pairs():
    with st.expander('팀원 정정·철회 자료 · 원논문과 공지 비교'):
        try:
            inventory = strict_json((PROJECT_ROOT/'data/paper_expansion/inventory.json').read_bytes())
            pairs = inventory['pairs']
            st.caption('검수 시점: 후보 178쌍 · 허용 원문 331개(원논문 170·공지 161) · 양쪽 본문 보관 159쌍. 기존 900편 색인·블라인드 평가와 분리합니다.')
            st.warning('AI(에이아이, 인공지능) 사전 분류는 정답이 아닙니다. 정정·철회 공지가 있어도 모든 수치가 틀렸다는 뜻은 아닙니다.')
            query = st.text_input('정정·철회 후보 제목 또는 DOI 검색',key='correction_pair_query').strip().casefold()
            matches = [p for p in pairs if query in (p['title']+' '+p['doi']).casefold()]
            if not matches:
                st.info('일치하는 후보가 없습니다.'); return
            selected = st.selectbox('열람할 원논문·공지',range(len(matches)),format_func=lambda i: matches[i]['pair_id']+' · '+matches[i]['title'],key='correction_pair_choice')
            pair = matches[selected]
            st.caption('팀원 AI 사전 분류: '+pair['ai_prescreen']+' · 원자료·저자 코드 미포함')
            for role,doi in [('원논문',pair['doi']),('공지',pair['notice_doi'])]:
                if doi:st.link_button(role+' 출처', 'https://doi.org/'+doi)
            if st.button('파일 무결성 확인 후 쌍 열람',key='correction_pair_read'):
                result = read_correction_pair(PROJECT_ROOT,pair)
                st.info('재계산은 실행하지 않았습니다. 자료 열람만 수행했습니다.')
                st.caption('공지 XML이 원논문을 직접 참조합니다.' if result['relationship']=='NOTICE_LINKS_TO_ORIGINAL' else '공지 XML에서 원논문 직접 참조는 확인되지 않았습니다. 후보 연결 상태입니다.')
                for role,label in [('original','원논문'),('notice','정정·철회 공지')]:
                    st.subheader(label)
                    document = result['documents'].get(role)
                    if not document:
                        st.info('본문 또는 재사용 면허를 확인하지 못해 링크만 제공합니다.'); continue
                    st.json({k:v for k,v in document.items() if k not in {'passages','tables'}})
                    st.dataframe(document['passages'],hide_index=True)
                    st.download_button(label+' 검증 원문 단락 JSON',json.dumps(document,ensure_ascii=False,indent=2),file_name=pair['pair_id']+'-'+role+'.json',mime='application/json')
        except (OSError,ValueError,KeyError,TypeError):
            st.error('자료 쌍을 열 수 없습니다. 파일·식별자·면허 검증에 실패했습니다.')


# [수정: 자료통합 담당] 2026-09-28 case86
# 종류: 검증방법추가 / 재현 방법: 별도 팀 자료 미노출 / 변경 전: 서지 후보만 / 변경 후: 공지 쌍 읽기 기능 / 왜: 원문 추적 활용 / 영향: 기존 색인·실행 경로 불변.
def render_paper_library():
    st.title('논문 근거 검색')
    # [수정: 0 이영 · Codex] 2026-10-01T03:04:44+09:00 — 논문 검색 기능의 실행 경계를 한국어로 설명한다.
    st.caption('검색은 원문 또는 서지 후보를 찾는 기능입니다. 주장 생성·승인이나 분석을 자동 실행하지 않습니다.')
    # [수정: 자료통합 담당] 2026-09-28 case83 / 종류: 효율화 / 재현: 후보문서 분산 / 전후: 파일보관→별도 후보목록 / 왜: 원문과 분리 / 영향: 기존 색인 불변.
    _team_candidates()
    _correction_pairs()
    try:
        raw=(PROJECT_ROOT/'data/research_corpus/corpus.json').read_bytes()
        corpus=strict_json(raw)
        summary=display_summary(corpus)
        cols=st.columns(3)
        cols[0].metric('전체 논문 목록',summary['records'])
        cols[1].metric('보관 원문',summary['fulltext'])
        cols[2].metric('원문 없는 서지',summary['bibliography_only'])
        st.caption('색인에 기록된 수량이며, 검색 시 현재 원문과 다시 대조합니다.')
    except (OSError,ValueError,KeyError,TypeError):
        st.session_state.pop('paper_library_results',None)
        st.error('검색 자료를 읽을 수 없습니다. 설치된 논문 색인과 원문 파일을 확인하세요.')
        return
    try:
        team_metadata=load_team_metadata(PROJECT_ROOT,corpus['papers']) if isinstance(corpus.get('papers'),list) else []
        st.caption(f"기존 색인 {summary['records']}편 · 별도 팀 서지 {len(team_metadata)}편 · 서지 검색 합계 {summary['records']+len(team_metadata)}편. 별도 팀 서지는 원문 단락 근거가 아닙니다.")
    except (OSError,ValueError,KeyError,TypeError):
        st.session_state.pop('paper_library_results',None)
        st.error('별도 팀 서지의 무결성을 확인할 수 없어 검색을 차단했습니다. 메타데이터 파일을 확인하세요.')
        return
    split_label=st.selectbox('자료 구분',['개발용 자료','검증용 자료 열람'],key='paper_library_split')
    split='development' if split_label=='개발용 자료' else 'validation'
    if split=='validation':
        st.warning('검증용 자료를 열람합니다. 열람한 자료는 블라인드 평가에 사용했다고 주장할 수 없습니다.')
    mode_label=st.radio('검색 대상',['원문 단락','서지 목록'],horizontal=True,key='paper_library_mode')
    mode='passages' if mode_label=='원문 단락' else 'bibliography'
    # [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 확장을 명시선택하고 옵션변경은 이전결과 무효화 / 입력·출력: bool→검색옵션 / 검증: UI stale 차단.
    with st.expander('검색 보완 옵션 · 기본 꺼짐'):
        include_tables=st.checkbox('표 텍스트 후보 포함',key='paper_library_tables',disabled=mode!='passages') and mode=='passages'
        boundary_context=st.checkbox('조각·문단 경계 문맥 포함',key='paper_library_boundary',disabled=mode!='passages') and mode=='passages'
        expand_synonyms=st.checkbox('고정 한영 용어 대응 사용',key='paper_library_synonyms')
        st.caption('한영 용어 6쌍의 수동 목록입니다. 번역·의미 이해·검색 정확도를 보장하지 않습니다. 표와 경계 후보는 원문 위치를 확인해야 합니다.')
    st.caption(f"선택한 자료 구분: {summary['splits'][split]}편. 서지 목록 검색은 원문 보관 여부와 관계없이 논문 목록을 검색합니다.")
    team_count=sum(row['split']==split for row in team_metadata)
    st.caption(f"현재 선택 구분: 기존 색인 {summary['splits'][split]}편 · 별도 팀 서지 {team_count}편 · 서지 검색 합계 {summary['splits'][split]+team_count}편.")
    query=st.text_input('검색어',placeholder='예: missing data, data provenance',key='paper_library_query')
    signature=(query.strip(),split,mode,hashlib.sha256(raw).hexdigest(),include_tables,boundary_context,expand_synonyms)
    if st.button('근거 검색',type='primary',key='paper_library_search'):
        st.session_state.pop('paper_library_results',None)
        if not query.strip():
            st.info('검색어를 입력하세요.')
        else:
            st.session_state.paper_library_results={'signature':signature}
    saved=st.session_state.get('paper_library_results')
    if not saved or saved['signature']!=signature:return
    try:
        # 재표시 때도 현재 출처를 대조해 이전 세션 결과가 검증을 우회하지 않도록 한다.
        with st.spinner('원문과 인용 위치를 대조하고 있습니다…'):
            results=search_corpus(corpus,query.strip(),split=split,mode=mode,limit=10,root=PROJECT_ROOT,include_tables=include_tables,boundary_context=boundary_context,expand_synonyms=expand_synonyms)
    except (OSError,ValueError,KeyError,TypeError):
        st.session_state.pop('paper_library_results',None)
        st.error('검색을 차단했습니다. 색인·원문·출처의 무결성을 확인하세요.')
        return
    if not results:
        st.info('일치하는 후보가 없습니다. 검색어 또는 자료 구분을 확인하세요.')
        return
    st.caption(f'후보 {len(results)}개 · rank_score는 검색 순위 점수이며 신뢰도·정확도 확률이 아닙니다.')
    for index,result in enumerate(results,1):render_result(result,index)

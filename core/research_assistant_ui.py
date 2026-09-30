"""case93 guided public-evidence research; external transfer is off until opted in."""
import hashlib
import json
import os

import streamlit as st
from core.activity_privacy import activity_view, activity_detail

from core.paper_library_ui import public_url
from core.plain_language import STATISTIC_HELP, STATISTIC_LABELS, STATUS_LABELS, explain_reason


# [작성: 일반사용자 UX 담당] 2026-09-29 case93
# 무엇·왜: 서버 설정만 읽고 키 입력·표시 금지 / 입력·출력: secrets·환경→메모리 설정 / 검증: test_case93_ux 미설정·노출금지.
def provider_settings():
    try:
        config = dict(st.secrets.get('research_agent', {}))
    except (FileNotFoundError, KeyError, TypeError):
        config = {}
    return {'api_key': str(config.get('api_key') or os.environ.get('ANTHROPIC_API_KEY', '')),
            'model': str(config.get('model') or os.environ.get('NAIS_AGENT_MODEL', '')),
            'enabled': config.get('enabled') is True or os.environ.get('NAIS_AGENT_ENABLED', '').lower() == 'true'}


def search_evidence(query, limit=5):
    from core.research_agent import search_evidence as search
    return search(query, limit=limit)


def run_research_agent(question, evidence, *, api_key, model):
    from core.research_agent import run_research_agent as run
    return run(question, evidence, api_key=api_key, model=model)


# [작성: 일반사용자 UX 담당] 2026-09-29 case93
# 무엇·왜: 질문·선택근거·설정 변경 시 답변/동의 폐기 / 입력·출력: 현재 입력→비밀값 없는 지문 / 검증: test_case93_ux 변경4종.
def input_signature(question, evidence, config):
    return hashlib.sha256(json.dumps([question, evidence, config], ensure_ascii=False,
                                    sort_keys=True, default=str).encode('utf-8')).hexdigest()


def _clear_result():
    st.session_state.pop('research_result', None)
    st.session_state['research_consent'] = False


def _redact(value, api_key):
    if isinstance(value, str):
        return value.replace(api_key, '[비공개 설정]') if api_key else value
    if isinstance(value, list):
        return [_redact(item, api_key) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, api_key) for key, item in value.items()}
    return value


# [작성: 일반사용자 UX 담당] 2026-09-29 case93
# 무엇·왜: 모델 텍스트를 HTML 없이 표시하고 인용을 입력출처에 결속 / 입력·출력: 보고·선택근거→화면·키없는 JSON / 검증: test_case93_ux 명시실행.
def _display_report(report, question, evidence, api_key, reference_numbers=None):
    report = activity_view(_redact(report, api_key))
    status = report.get('status', 'BLOCKED')
    st.subheader('4. 출처와 함께 답변 확인')
    st.write(STATUS_LABELS.get(status, STATUS_LABELS['BLOCKED']))
    if status == 'READY' and report.get('answer'):
        st.text(report['answer'])
    else:
        st.info('현재 근거로 답변을 작성하지 못했습니다. 아래 제한을 확인하고 질문을 좁히거나 추가 원문을 확보하세요.')
    references = {row['id']: row for row in evidence}
    reference_numbers = reference_numbers or {row['id']: index for index, row in enumerate(evidence, 1)}
    for citation in report.get('citations', []):
        if citation in references:
            row = references[citation]
            number = reference_numbers[citation]
            st.text(f"인용 근거 {number} · DOI {row['doi']}")
            with st.expander(f'인용 위치·식별자 · 근거 {number}'):
                st.text(f"식별자 {citation} · 위치 {row['locator']}")
            link = public_url('https://doi.org/' + row['doi']) if row['doi'] else ''
            if link:
                st.link_button(f'인용한 논문 열기 · 근거 {number}', link)
    st.write('이 답변의 제한과 다음 단계')
    for item in report.get('limitations', []):
        st.text(explain_reason(item))
    for item in report.get('steps', []):
        if isinstance(item, dict):
            role = {'retrieval': '선택 원문 기록', 'researcher': 'AI 초안 작성',
                    'critic': '추가 AI 근거 검토', 'deterministic_validator': '인용·형식 검사'}.get(item.get('role'), '검토 단계')
            outcome = '보류' if item.get('status') == 'BLOCKED' else '완료 · 사실 확증 아님'
            st.text(role + ': ' + outcome)
            if item.get('reason'):
                st.text(explain_reason(item['reason']))
        else:
            st.text(str(item))
    usage = report.get('usage', {})
    tokens = {key: value if type(value) is int else '미확인' for key, value in
              ((key, usage.get(key)) for key in ('input_tokens', 'output_tokens'))}
    st.caption(f"이 실행의 모델 호출 시도 {usage.get('calls', '미기록')}회 · 입력 토큰 {tokens['input_tokens']} · 출력 토큰 {tokens['output_tokens']}. 토큰은 모델이 처리한 텍스트 단위이며 비용은 여기서 측정하지 않았습니다.")
    st.warning('출처를 제한한 검토 초안입니다. 논문 전체 재현·의학 판단·최종 승인으로 사용할 수 없습니다. 원문 의미·분석조건·최종 승인은 이 기능에서 확인하지 않았습니다.')
    download = {key: report.get(key) for key in ('status', 'answer', 'citations', 'limitations', 'steps', 'usage', 'budget', 'telemetry', 'input_snapshot_sha256', 'provider', 'model', 'prompt_sha256')}
    download.update(question=_redact(question, api_key), evidence=_redact(evidence, api_key), approved=False, executed=False)
    st.download_button('질문·출처·답변 보고서 내려받기',
                       json.dumps(download, ensure_ascii=False, indent=2),
                       file_name='research_assistant_report.json', mime='application/json')


def _registered_replay():
    with st.expander('직접 계산해 보기 · 공개 등록 논문의 숫자'):
        st.write('보관된 공개 저자 분석자료와 원래·정정 분석조건을 대조합니다. 외부 AI 호출 없이 실제 재계산합니다.')
        st.caption('회귀계수·표준오차·t값의 산술 대조입니다. 원자료 선택의 타당성이나 논문의 참·거짓을 판정하지 않습니다.')
        if not st.button('등록 논문의 숫자 재계산', key='research_replay'):
            return
        try:
            from core.portfolio_workspace import registered_model_comparison, model_followup_tasks
            with st.spinner('등록된 분석조건으로 숫자를 다시 계산합니다…'):
                report = registered_model_comparison()
            summary = report['summary']
            st.write(f"등록 모형 쌍 {summary['model_pairs']}개 중 정정 조건 수치 일치 {summary['corrected_matches']}개 · 원래 조건 수치 재현 {summary['original_matches']}개")
            st.warning(f"정정 공지 자유도와 잔차 자유도 불일치 {summary['corrected_df_mismatches']}건. 원래 수치를 재현했어도 올바른 분석이라는 뜻은 아닙니다.")
            st.write('다음으로 확인할 것')
            for task in {item['task']: item for item in model_followup_tasks(report)}.values():
                st.text(task['task'])
            st.download_button('재계산 근거 보고서 내려받기', json.dumps(report, ensure_ascii=False, indent=2),
                               file_name='registered_arithmetic_report.json', mime='application/json')
        except (ValueError, OSError, KeyError, TypeError, UnicodeError):
            st.error('재계산을 중단했습니다. 등록 원문·자료·분석조건을 담당자가 확인한 뒤 다시 실행하세요.')


# [작성: 일반사용자 UX 담당] 2026-09-29 case93
# 무엇·왜: 버튼1회에 공식 서지만 비교 / 입력·출력: DOI·이전서지→기준/변경보고 / 검증: test_case93_ux mock; 자동예약·AI호출 없음.
def _metadata_watch():
    with st.expander('논문 변경 알림 확인'):
        st.write('DOI를 입력하면 공식 Crossref에 등록된 제목·관계·정정 연결을 확인합니다. 버튼을 누를 때만 무료 서지 API에 DOI를 전송합니다.')
        st.caption('자동 예약이나 메시지 발송은 하지 않습니다. 서지 변화는 원문을 다시 검토할 신호이며, 모든 정정·철회를 탐지하지 못합니다.')
        doi = st.text_input('변경을 확인할 논문 DOI', placeholder='예: 10.1234/example',
                            max_chars=200, key='research_watch_doi').strip().lower()
        saved = st.session_state.get('research_watch_report')
        if saved and saved['doi'] != doi:
            st.session_state.pop('research_watch_report', None)
        if st.button('공식 서지에서 변경 확인', key='research_watch_run'):
            if not doi:
                st.info('확인할 논문의 DOI를 입력하세요.')
                return
            st.session_state.pop('research_watch_report', None)
            try:
                from core.research_watch import fetch_metadata, compare_metadata
                previous = st.session_state.get('research_watch_previous')
                previous = previous if previous and previous['doi'] == doi else None
                with st.spinner('공식 서지의 현재 등록 내용을 확인합니다…'):
                    current = fetch_metadata(doi)
                    report = compare_metadata(current, previous)
                st.session_state['research_watch_previous'] = current
                st.session_state['research_watch_report'] = report
            except (ValueError, OSError, KeyError, TypeError):
                st.error('공식 서지를 확인하지 못했습니다. DOI 형식·연결을 확인하고 다시 시도하세요. 이전 확인을 현재 결과로 표시하지 않습니다.')
        saved = st.session_state.get('research_watch_report')
        if not saved or saved['doi'] != doi:
            return
        states = {'BASELINE': '첫 확인 · 비교 기준 저장', 'UNCHANGED': '이전 확인 이후 서지 변화 없음',
                  'METADATA_CHANGED': '이전 확인 이후 서지 변화 감지'}
        st.write(states.get(saved['state'], '확인 결과를 다시 점검하세요.'))
        for title in saved['current'].get('title', []):
            st.text(str(title))
        names = {'title': '제목', 'updates': '정정 연결', 'relations': '논문 관계', 'type': '자료 유형', 'doi': 'DOI'}
        if saved['changed_fields']:
            st.text('변경 항목: ' + ', '.join(names.get(field, field) for field in saved['changed_fields']))
        st.text(f"현재 등록된 정정·업데이트 연결 {len(saved['current'].get('updates', []))}개")
        for limitation in saved['limitations']:
            st.caption(limitation)
        st.download_button('논문 변경 확인 보고서 내려받기', json.dumps(activity_view(saved), ensure_ascii=False, indent=2),
                           file_name='research_metadata_watch.json', mime='application/json')


# [작성: 일반사용자 UX 담당] 2026-09-29 case93
# 무엇·왜: 질문→공개근거→선택동의→수동 AI검토 / 입력·출력: 질문·선택→추적 가능한 제한 답변 / 검증: test_case93_ux 무호출·무효화·비밀오류.
def render_research_assistant():
    st.title('질문에서 근거까지 · 연구 도우미')
    st.write('궁금한 내용을 적고, 보관된 공개 논문의 원문을 먼저 확인하세요. 답변은 선택한 출처 안에서 검토합니다.')
    st.caption('현재 가능: 공개 원문 검색, 등록 논문 숫자 재계산. 인터넷 전체 검색·임의 원자료 분석·최종 승인은 지원하지 않습니다.')
    with st.expander('숫자와 버튼이 낯설다면 · 쉬운 설명'):
        st.write('근거 찾기: 공개 보관 원문을 검색합니다. AI로 검토: 동의한 질문과 원문만 외부 모델에 보내 초안을 검토합니다. 보고서: 질문·출처·제한을 함께 저장합니다.')
        for key, explanation in STATISTIC_HELP.items():
            st.markdown('**' + STATISTIC_LABELS[key] + '**')
            st.write(explanation)
    _registered_replay()
    _metadata_watch()
    st.subheader('1. 궁금한 내용 적기')
    question = st.text_area('연구 질문', placeholder='예: 이 연구에서는 결측값을 어떻게 처리했나요?',
                            key='research_question', max_chars=1000).strip()
    keywords = st.text_input('근거 검색어 · 비워두면 질문으로 검색',
                             placeholder='예: missing data, data provenance',
                             key='research_query', max_chars=1000).strip()
    query = keywords or question
    st.caption('검색은 문구 중심입니다. 결과가 없으면 논문에 쓰인 영어 용어로 바꿔 보세요. 개인정보·비공개 연구자료를 입력하지 마세요.')
    previous = st.session_state.get('research_search_question')
    if previous is not None and (previous != question or st.session_state.get('research_search_query') != query):
        st.session_state.pop('research_search_question', None)
        st.session_state.pop('research_evidence', None)
        st.session_state.pop('research_selection', None)
        _clear_result()
    st.subheader('2. 출처 찾고 선택하기')
    # [수정: UX 담당] 2026-09-29 case93 / 입력 blur 전 버튼 활성→클릭으로 질문 반영; 빈입력 서버 검사; test_case93_ux.
    if st.button('공개 원문에서 근거 찾기', key='research_search', type='primary'):
        if not question:
            st.info('연구 질문을 먼저 입력하세요.')
            return
        st.session_state['research_search_question'] = question
        st.session_state['research_search_query'] = query
        st.session_state.pop('research_evidence', None)
        st.session_state.pop('research_selection', None)
        _clear_result()
    if st.session_state.get('research_search_question') != question or not question:
        st.info('다음 단계: 질문을 적고 근거 찾기 버튼을 누르세요.')
        return
    try:
        with st.spinner("공개 원문 파일을 대조하고 관련 근거를 찾습니다…"):
            evidence = search_evidence(query, limit=5)
        if evidence != st.session_state.get('research_evidence'):
            st.session_state['research_evidence'] = evidence
            st.session_state.pop('research_selection', None)
            _clear_result()
    except (ValueError, OSError, KeyError, TypeError, ImportError):
        _clear_result()
        st.error('공개 근거를 읽을 수 없습니다. 담당자가 검색 색인과 원문 파일을 확인해야 합니다.')
        return
    if not evidence:
        _clear_result()
        st.info('현재 보관 자료에서 일치하는 원문을 찾지 못했습니다. 질문을 좁히거나 영어 검색어로 바꿔 다시 찾아보세요. 근거 없이 AI 답변을 실행하지 않습니다.')
        return
    choices = {row['id']: row for row in evidence}
    numbers = {row['id']: index for index, row in enumerate(evidence, 1)}
    selected = st.multiselect('검토에 사용할 근거', list(choices), default=list(choices),
                              format_func=lambda value: f"근거 {numbers[value]} · DOI {choices[value]['doi']}", key='research_selection')
    selected_evidence = [choices[value] for value in selected]
    for row in selected_evidence:
        number = numbers[row['id']]
        st.text(f"근거 {number} · DOI {row['doi']}")
        with st.expander(f'원문 위치·식별자 · 근거 {number}'):
            st.text(f"식별자 {row['id']} · 위치 {row['locator']}")
        # Read-only native text area preserves whitespace that st.text strips.
        preview_key = 'research_preview_' + input_signature('', [row], {})
        st.text_area(f'전송할 원문 · 근거 {number}', value=row['text'], height=140,
                     disabled=True, key=preview_key)
    config = provider_settings()
    signature = input_signature(question, selected_evidence, config)
    if signature != st.session_state.get('research_input_signature'):
        _clear_result()
        st.session_state['research_input_signature'] = signature
    st.subheader('3. 선택한 출처로 AI 검토 · 선택사항')
    configured = bool(config['api_key'] and config['model'])
    enabled = config.get('enabled') is True
    if not configured:
        st.info('외부 AI 연결 미설정: 지금은 검색과 숫자 재계산을 사용할 수 있습니다. 연결하려면 담당자가 서버의 키·모델 설정을 준비해야 합니다.')
    elif not enabled:
        st.info('외부 AI 설정 있음 · 실행 꺼짐. 유료 호출은 실행하지 않습니다. 담당자가 별도로 실행을 허용해야 합니다.')
    else:
        st.caption('외부 AI 서버 설정 있음 · 실제 연결 성공 여부는 아직 확인하지 않았습니다. 버튼을 누르면 최대 2회 모델 호출하며 제공사 비용이 발생할 수 있습니다.')
    st.write('외부로 전송할 질문 · 아래 질문과 위에서 선택한 원문 전체가 전송 대상입니다.')
    st.text_area('전송할 질문', value=question, height=100, disabled=True,
                 key='research_question_preview_' + input_signature(question, [], {}))
    consent = st.checkbox('이 질문과 선택한 공개 원문을 외부 AI 제공사에 보내는 데 동의합니다', key='research_consent', disabled=not (configured and enabled and selected_evidence))
    if st.button('선택한 근거로 AI 검토 실행', key='research_run',
                 disabled=not (configured and enabled and consent and selected_evidence)):
        st.session_state.pop('research_result', None)
        try:
            with st.spinner('선택한 원문만으로 답변을 작성하고 인용을 확인합니다…'):
                report = run_research_agent(question, selected_evidence, api_key=config['api_key'], model=config['model'])
            if input_signature(question, selected_evidence, provider_settings()) != signature:
                raise ValueError('Settings changed during run')
            st.session_state['research_result'] = {'signature': signature, 'report': _redact(report, config['api_key'])}
        except Exception:
            st.error('AI 검토를 완료하지 못했습니다. 서버 연결·허용 모델·응답 형식을 담당자가 확인한 뒤 다시 시도하세요. 이전 답변은 표시하지 않습니다.')
    saved = st.session_state.get('research_result')
    if saved and saved['signature'] == signature:
        _display_report(saved['report'], question, selected_evidence, config['api_key'], numbers)
    else:
        st.caption('다음 단계: 원문과 질문을 확인하세요. 외부 AI를 쓰려면 실행 설정과 전송 동의가 모두 필요합니다.')

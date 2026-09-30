"""case95 actor-scoped research tasks: register, explicitly run, reopen and export."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import sqlite3

import streamlit as st
from core.activity_privacy import activity_view, activity_detail
from core.research_cases import shared_provenance

from core.paper_library_ui import public_url
from core.plain_language import (STATISTIC_HELP, TASK_STATUS_LABELS, TASK_STEP_LABELS,
                                 TASK_STEP_STATUS_LABELS, TASK_TOOL_HELP, TASK_CALCULATION_LABELS)

STORE_ERRORS = (ValueError, OSError, KeyError, TypeError, sqlite3.Error)

TASK_EXAMPLES = (
    ('public_wheat', '밀 재배 실험으로 시작', '밀 재배 실험에서 개화기 3개·성숙기 4개의 반복 단위가 원자료에 있는지 비교해 주세요.', 'wheat water carbon dioxide'),
    ('public_penguins', '펭귄 자료로 시작', '펭귄 공개 원자료의 행 수가 논문의 보고값과 같은지 확인해 주세요.', 'penguins'),
    ('public_bat', '갈색지방 연구로 시작', '갈색지방 양성 기록 수와 선택한 표본의 평균 연령을 비교해 주세요.', 'brown adipose tissue'),
    ('n3_11814', '반복연구 계수로 시작', '탐욕과 사회경제적 지위 반복연구에서 원래·정정 회귀계수를 비교해 주세요.', 'greed socioeconomic status'),
    ('public_forest', '산불 자료로 시작', '산불 공개 자료의 기록 수를 확인하고, 예측 성능은 아직 확인하지 않았음을 구분해 주세요.', 'forest fires'),
)


def get_store():
    from core.research_tasks import TaskStore
    return TaskStore()


def list_cases():
    from core.research_cases import list_cases as cases
    return cases(include_extensions=True)


def calculation_summary(calculation):
    """Explain only engine row decisions; a match is never a paper verdict."""
    rows = calculation.get('rows', [])
    matches = sum(row.get('status') in {'ARITHMETIC_MATCH', 'COEFFICIENT_MATCH'} for row in rows)
    if not rows:
        return '이번 실행에는 비교할 수 있는 계산 결과가 없습니다.'
    return (f'등록 수치 {len(rows)}개 중 {matches}개가 정해진 허용오차 안에서 일치하고, '
            f'{len(rows)-matches}개는 추가 확인이 필요합니다. 논문 전체가 맞다는 뜻은 아닙니다.')


def _provenance_lines(calculation):
    # Reuse the engine's exact binding, rather than reconstructing hashes in the UI.
    provenance = calculation.get('provenance')
    if not provenance:
        return ['이 과거 보고서에는 입력 지문이 없습니다. 새로 실행하면 자료·조건 지문을 남깁니다.']
    return ['SHA256은 같은 파일·조건인지 비교하는 지문이며, 정확도 점수나 사람 승인 표시가 아닙니다.',
            '아래 지문은 이 실행에 사용한 입력입니다. 현재 입력과 같다는 보장은 재실행으로 확인합니다.',
            '```json', json.dumps(shared_provenance(provenance), ensure_ascii=False, indent=2, allow_nan=False), '```',
            '같은 프로젝트를 복원한 뒤 실행: python -m tools.replay_research_report --report research_task_report.json']


# [작성: 예시 UX 담당] 2026-09-29 case95 / 클릭→새과제 입력만 채움; 저장·실행0 / 검증: test_case95_discovery_ui.
def prefill_example(actor, case_id, question, query):
    for name, value in [('question', question), ('query', query), ('doi', ''), ('case', case_id)]:
        st.session_state[scoped_key(actor, name)] = value


# [작성: 쉬운 과제 UX 담당] 2026-09-29 case95
# 무엇·왜: 검토자 전환 시 입력·선택 혼합 방지 / 입력·출력: actor,name→범위키 / 검증: test_case95_tasks_ui actor격리.
def scoped_key(actor, name):
    return 'taskui_' + hashlib.sha256(str(actor).encode('utf-8')).hexdigest()[:16] + '_' + name


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S') + ' 한국시간'
    except (ValueError, TypeError):
        return '시간 기록 없음'


def _number(value):
    if type(value) in (int, float) and math.isfinite(value):
        return f'{value:.8g}'
    return '미확인'


def _claim_label(row, index):
    label = str(row.get('label') or f'숫자 비교 {index}')
    return label + (' · ' + str(row['claim_id']) if row.get('claim_id') else '')


def _calculation_help(calculation):
    text = (str(calculation.get('label', '')) + ' ' + str(calculation.get('scope', ''))).lower()
    rows = calculation.get('rows', [])
    regression = any(str(row.get('status', '')).startswith('COEFFICIENT_') for row in rows) or '회귀' in text or 'regression' in text
    methods = {row.get('method') for row in rows}
    methods.update(item.get('conditions', {}).get('method')
                   for item in calculation.get('provenance', {}).get('inputs', []))
    keys = (['coefficient', 'se', 'df', 'tolerance'] if regression else
            [key for key in ('count_rows', 'missing_count', 'mean') if key in methods] + ['tolerance'])
    return [STATISTIC_HELP[key] for key in keys]


def _card(title, rows, empty):
    with st.container(border=True):
        st.subheader(title)
        for text in rows or [empty]:
            st.text(str(text))


def evidence_scope(task):
    """case100: derive DOI scope for old reports too; never relabel old related evidence as direct."""
    run = task.get('latest_run') or {}
    doi = str(task.get('doi') or '').lower()
    rows = run.get('evidence', [])
    direct = [row for row in rows if doi and str(row.get('doi', '')).strip().lower() == doi]
    related = [row for row in rows if row not in direct]
    scope = dict(run.get('selected_paper') or {})
    scope.update(doi=doi or None, direct_count=len(direct), related_count=len(related))
    if doi:
        text = f'선택 논문 직접 근거 {len(direct)}개 · 관련 문헌 {len(related)}개. '
        text += '선택 논문 전체 원문 미검토.' if direct else '선택 논문 원문 미확보·미검토.'
        scope.setdefault('status', 'EXCERPTS_NOT_REVIEWED' if direct else 'FULLTEXT_MISSING')
    else:
        text = f'DOI를 선택하지 않았습니다. 일반 관련 문헌 {len(related)}개이며 특정 논문 검토가 아닙니다.'
        scope.setdefault('status', 'NOT_SELECTED')
    scope['explanation'] = text + ' 다른 DOI의 근거는 선택 논문 검토 범위에 합산하지 않습니다. 최종 승인 없음.'
    if doi and not direct:
        scope['fallback'] = '무료 OA 원문 포함 실행을 요청하거나 선택 DOI 링크에서 원문을 직접 확인하세요. 공개 허용 원문과 인용 위치를 확보한 뒤 다시 검토하세요. Europe PMC 미수집·라이선스 미확인은 논문 부재의 증거가 아닙니다.'
    return scope, direct, related


def result_brief(task):
    """Same plain-language decision in the screen and downloadable report."""
    run = task.get('latest_run') or {}
    scope, direct, related = evidence_scope(task)
    if not run:
        headline = '아직 확인을 시작하지 않았습니다.'
    elif run.get('status') == 'RUNNING':
        headline = '확인 중입니다. 완료 결과를 기다려 주세요.'
    elif run.get('status') != 'CHECKED_PARTIAL':
        headline = '추가 확인이 필요합니다. 아래 이유부터 확인하세요.'
    elif task.get('doi') and not direct:
        headline = '선택 논문의 직접 근거가 없습니다. 내용 판단을 보류하세요.'
    else:
        headline = '일부 자료를 확인했습니다. 연구 결론의 승인은 아직 아닙니다.'
    calculation = run.get('calculation')
    return dict(headline=headline, evidence=scope['explanation'],
                numbers=calculation_summary(calculation) if calculation else '이번 실행에서 숫자를 재계산하지 않았습니다.',
                next_action=next(iter(run.get('next_actions') or []), '저장한 과제를 실행한 뒤 근거와 계산 조건을 확인하세요.'),
                approved=False)


# [작성: 쉬운 과제 UX 담당] 2026-09-29 case95
# 무엇·왜: 결과를 질문·실행에 결속한 두 보고서 제공 / 입력·출력: 저장과제→MD/JSON / 검증: test_case95_tasks_ui 다운로드·불변.
def report_downloads(task):
    report = {key: task.get(key) for key in ('id', 'question', 'query', 'doi', 'case_id', 'status', 'latest_run')}
    report['approved'] = False
    run = task.get('latest_run') or {}
    scope, direct, related = evidence_scope(task)
    report['selected_paper'] = scope
    brief = result_brief(task)
    report['result_brief'] = brief
    lines = ['# 연구 과제 보고서', '', '## 질문', '', task['question'], '',
             '상태: ' + TASK_STATUS_LABELS.get(task.get('status'), '상태 확인 필요'),
             '저장한 검색어: ' + str(task.get('query') or '질문으로 검색'),
             '선택한 DOI: ' + str(task.get('doi') or '없음'),
             '이 보고서는 근거 수집·선택 서지 조회·등록 계산 결과입니다. 논문 전체 재현·정상 범위·최종 승인은 확인하지 않았습니다.']
    lines.extend(['', '## 먼저 읽는 결과', '', brief['headline'], brief['numbers'],
                  '다음 행동: ' + brief['next_action'], '', '## 선택 논문 검토 범위', '', scope['explanation']])
    if scope.get('fallback'):
        lines.append(scope['fallback'])
    fulltext = scope.get('fulltext')
    if fulltext:
        lines.extend(['무료 OA 원문 조회: ' + str(fulltext.get('status', '미확인')),
                      '조회 출처: ' + str(fulltext.get('source', '미확인')),
                      '원문 출처 URL: ' + str(fulltext.get('source_url') or '없음'),
                      '원문 라이선스: ' + str(fulltext.get('license') or '미확인')])
        lines.extend(str(value) for value in fulltext.get('limitations', []))
    for label, key in [('알아낸 것', 'known'), ('아직 모르는 것', 'unknown'), ('다음 행동', 'next_actions')]:
        lines.extend(['', '## ' + label, ''])
        lines.extend('- ' + str(value) for value in run.get(key, []) or ['추가 기록 없음'])
    lines.extend(['', '## 실행 단계', ''])
    for step in run.get('steps', []):
        lines.append('- ' + TASK_STEP_LABELS.get(step.get('role'), '확인 단계') + ': ' +
                     TASK_STEP_STATUS_LABELS.get(step.get('status'), '상태 확인 필요') + ' · ' + str(step.get('detail', '')))
    lines.extend(['', '## 원문 근거', ''])
    for index, row in enumerate(run.get('evidence', []), 1):
        label = '선택 논문 직접 근거' if row in direct else '관련 문헌 · 선택 논문 직접 근거 아님'
        lines.extend([f"### 근거 {index} · DOI {row.get('doi', '미확인')} · {label}",
                      '인용 위치: ' + str(row.get('locator', '미확인')), '',
                      *('> ' + line for line in str(row.get('text', '')).splitlines()), ''])
    calculation = run.get('calculation')
    if calculation:
        lines.extend(['', '## 숫자 비교 한눈에 보기', '', calculation_summary(calculation)])
        lines.extend(['', '## 등록 자료의 수치 비교', '', str(calculation.get('label', '등록 사례')), str(calculation.get('scope', '')),
                      '등록 계산 논문 DOI: ' + str(calculation.get('doi') or '미확인'),
                      '', '원문 주장 | 원문 보고값 | 계산값 | 차이 | 허용오차 | 단위 | 비교 결과', '--- | --- | --- | --- | --- | --- | ---'])
        # Reuse the UI's engine-status labels so MD preserves BLOCK/mismatch decisions too.
        for index, row in enumerate(calculation.get('rows', []), 1):
            lines.append(' | '.join([_claim_label(row, index), *(_number(row.get(key)) for key in
                             ('reported_value', 'calculated_value', 'difference', 'tolerance')), str(row.get('unit') or '미확인'),
                             TASK_CALCULATION_LABELS.get(row.get('status'), '확인 필요')]))
        lines.extend(['', *_calculation_help(calculation)])
        lines.extend(['', '## 같은 자료·조건으로 다시 확인하기', '', *_provenance_lines(calculation)])
    lines.extend(['', '## 추적 정보', '', '과제 식별자: ' + str(task['id']),
                  '실행 식별자: ' + str(run.get('id', '없음')), '사람 승인: 없음', ''])
    shared = activity_view(report)
    if calculation and calculation.get('provenance'):
        shared['latest_run']['calculation']['provenance'] = shared_provenance(calculation['provenance'])
    return '\n'.join(lines).encode('utf-8'), json.dumps(shared, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


def _result(task, actor):
    run = task.get('latest_run')
    if not run:
        st.info('아직 실행하지 않았습니다. 아래 실행 버튼으로 근거와 확인 결과를 모으세요.')
        return
    st.caption('이 과제의 저장된 질문과 선택 조건으로 실행한 결과입니다. 작업 시각은 표시하지 않습니다.')
    brief = result_brief(task)
    with st.container(border=True):
        st.subheader('먼저 이것만 확인하세요')
        st.write(brief['headline'])
        st.write(brief['numbers'])
        st.write('다음 행동: ' + brief['next_action'])
    scope, direct, related = evidence_scope(task)
    if task.get('doi'):
        st.warning(scope['explanation'])
        if scope.get('fallback'):
            st.info(scope['fallback'])
    else:
        st.info(scope['explanation'])
    fulltext = scope.get('fulltext')
    if fulltext:
        st.caption('무료 OA 조회: ' + str(fulltext.get('status')) + ' · 출처: ' + str(fulltext.get('source'))
                   + ' · 라이선스: ' + str(fulltext.get('license') or '미확인'))
    _card('알아낸 것', run.get('known', []), '현재 확보한 근거만으로 확인한 내용이 없습니다.')
    _card('아직 모르는 것', run.get('unknown', []), '추가 한계 기록 없음. 과학적 사실이나 최종 승인이 확인되었다는 뜻은 아닙니다.')
    _card('다음 행동', run.get('next_actions', []), '다른 질문·조건은 새 과제로 등록할 수 있습니다.')
    with st.expander('어떤 도구를 실행했나요?'):
        for step in run.get('steps', []):
            st.write(TASK_STEP_LABELS.get(step.get('role'), '확인 단계') + ' · ' +
                     TASK_STEP_STATUS_LABELS.get(step.get('status'), '상태 확인 필요'))
            st.text(str(step.get('detail', '')))
    with st.expander('사용한 원문과 논문 정보 확인'):
        for index, row in enumerate(run.get('evidence', []), 1):
            label = '선택 논문 직접 근거' if row in direct else '관련 문헌 · 선택 논문 직접 근거 아님'
            st.write(f"근거 {index} · DOI {row.get('doi', '미확인')} · {label}")
            st.text(str(row.get('text', '')))
            st.caption('인용 위치: ' + str(row.get('locator', '미확인')))
            link = public_url('https://doi.org/' + row.get('doi', ''))
            if row.get('doi') and link:
                st.link_button(f'근거 {index} 논문 열기', link)
        metadata = run.get('metadata')
        if metadata:
            label = {'BASELINE': '첫 서지 확인 · 다음 비교의 기준', 'UNCHANGED': '이전 확인 이후 서지 변화 없음',
                     'METADATA_CHANGED': '이전 확인 이후 서지 변화 감지'}.get(metadata.get('state'), '서지 확인 결과')
            st.write(label)
            for title in metadata.get('current', {}).get('title', []):
                st.text(str(title))
            for limitation in metadata.get('limitations', []):
                st.caption(str(limitation))
        if not run.get('evidence') and not metadata:
            st.info('이번 실행에서 확보한 원문·서지 정보가 없습니다. 다음 행동을 확인하세요.')
    calculation = run.get('calculation')
    if calculation:
        st.subheader('등록된 공개 자료의 숫자 비교')
        st.info(calculation_summary(calculation))
        st.write(str(calculation.get('label', '등록 사례')))
        st.caption(str(calculation.get('scope', '')))
        st.caption('질문으로 찾은 내 논문을 계산한 결과가 아닙니다. 미리 등록된 공개 자료·분석조건의 대조입니다.')
        rows = [{'원문 주장': _claim_label(row, index), '원문 보고값': _number(row.get('reported_value')),
                 '계산값': _number(row.get('calculated_value')), '차이': _number(row.get('difference')),
                 '허용오차': _number(row.get('tolerance')), '단위': row.get('unit') or '미확인',
                 '비교 결과': TASK_CALCULATION_LABELS.get(row.get('status'), '확인 필요')}
                for index, row in enumerate(calculation.get('rows', []), 1)]
        if rows:
            st.dataframe(rows, hide_index=True)
            st.caption('화면은 숫자를 유효숫자 8자리로 표시합니다. 계산 원값과 비교 조건은 데이터(JSON) 보고서에 보존합니다.')
        with st.expander('이 숫자는 무슨 뜻인가요?'):
            for explanation in _calculation_help(calculation):
                st.text(explanation)
        with st.expander('같은 자료·조건으로 다시 확인하기'):
            st.caption('파일 지문은 숫자의 정답 확률이 아닙니다. 다른 PC에서도 같은 입력인지 비교할 때 씁니다.')
            if calculation.get('provenance'):
                st.json(shared_provenance(calculation['provenance']))
                st.code('python -m tools.replay_research_report --report research_task_report.json', language='shell')
                st.caption('프로젝트와 JSON 보고서를 함께 전달하세요. 도구는 등록된 로컬 자료만 다시 계산하며 인터넷·유료 AI를 호출하지 않습니다.')
            else:
                st.info('이 과거 보고서에는 입력 지문이 없습니다. 과제를 다시 실행하면 새 보고서에 기록됩니다.')
    st.caption('원문 의미·분석조건·정상 범위·논문 전체의 참·거짓·최종 승인은 이 실행에서 확인하지 않았습니다.')
    md, raw = report_downloads(task)
    st.download_button('보고서 내려받기 · 문서(MD)', md, file_name='research_task_report.md',
                       mime='text/markdown', on_click='ignore', key=scoped_key(actor, 'md_' + task['id']))
    st.download_button('보고서 내려받기 · 데이터(JSON)', raw, file_name='research_task_report.json',
                       mime='application/json', on_click='ignore', key=scoped_key(actor, 'json_' + task['id']))
    with st.expander('고급 · 식별자·원시 결과·실행 이력'):
        if task.get('history_truncated'):
            st.caption('화면에는 최근 20회 실행만 표시합니다. 전체 이력은 현재 서버의 과제 저장소에 보관합니다. 클라우드 재배포 뒤 보관을 보장하지 않습니다.')
        st.json(task)


def _schedule(task, actor, store):
    with st.expander('정기 확인 시간 · 선택사항'):
        _worker_status(store, actor)
        st.caption('시간만 저장합니다. 백그라운드 실행기가 동작하지 않으면 자동 실행되지 않습니다. 클라우드 재배포 후 저장 상태도 확인하세요.')
        options = [None, *range(24)]
        current = task.get('daily_hour')
        current = current if type(current) is int and 0 <= current <= 23 else None
        with st.form(scoped_key(actor, 'schedule_form_' + task['id'])):
            hour = st.selectbox('매일 확인할 시간 · 한국시간', options, index=options.index(current),
                                format_func=lambda value: '예약하지 않음' if value is None else f'매일 {value:02}시',
                                key=scoped_key(actor, 'schedule_' + task['id']))
            save = st.form_submit_button('실행 시간 저장', key=scoped_key(actor, 'save_schedule_' + task['id']))
        if save:
            try:
                store.update_schedule(actor, task['id'], hour)
                st.session_state[scoped_key(actor, 'notice')] = '정기 확인 시간을 저장했습니다. 백그라운드 실행기가 없으면 자동 실행되지 않습니다.'
                st.rerun()
            except STORE_ERRORS:
                st.error('정기 확인 시간을 저장하지 못했습니다. 과제의 저장 상태를 확인하고 다시 시도하세요.')
        if task.get('status') == 'RUNNING':
            st.caption('15분 이상 중단된 실행만 대기 상태로 복구할 수 있습니다. 복구만으로 새 실행을 시작하지 않습니다.')
            if st.button('오래 중단된 실행 복구', key=scoped_key(actor, 'recover_' + task['id'])):
                try:
                    store.recover_stale(actor, task['id'])
                    st.session_state[scoped_key(actor, 'notice')] = '중단된 실행 상태를 복구했습니다. 같은 과제의 실행 버튼으로 다시 시도할 수 있습니다.'
                    st.rerun()
                except STORE_ERRORS:
                    st.info('아직 복구할 수 없습니다. 실행 시작 후 15분이 지나 중단된 과제만 복구할 수 있습니다.')


def _worker_status(store, actor):
    """Show recorded worker activity plus only this actor's scheduling information."""
    reader = getattr(store, 'worker_health', None)
    if not callable(reader):
        st.caption('자동 실행기의 운영 기록을 확인할 수 없습니다.')
        return
    try:
        health = reader(actor=actor)
    except STORE_ERRORS:
        st.warning('자동 실행기의 운영 기록을 읽지 못했습니다. 예약 시각만으로 실행 완료를 판단하지 마세요.')
        return
    labels = {'NEVER_RUN': '아직 자동 실행 기록이 없습니다', 'RUNNING': '종료 기록이 없는 자동 실행 시작 기록이 있습니다',
              'STALE': '과거 실행 중 15분 이상 활동 갱신이 없는 기록이 있습니다', 'COMPLETED': '최근 자동 실행기가 종료됐습니다',
              'FAILED': '최근 자동 실행에서 확인할 문제가 발생했습니다'}
    st.write(labels.get(health.get('status'), '자동 실행 상태 미확인'))
    st.caption('내 과제의 다음 예약: ' + _time(health.get('next_due')))
    st.caption('이 기록은 과거 실행 상태입니다. 현재 프로세스의 생존·중단·상주 여부는 확인하지 않았으며, 내 모든 과제가 성공했다는 보장도 아닙니다.')


# [작성: 쉬운 과제 UX 담당] 2026-09-29 case95
# 무엇·왜: 조각 도구를 저장 가능한 한 번의 연구과제로 연결 / 입력·출력: 질문·선택→불변과제·통합보고 / 검증: test_case95_tasks_ui 실행0/1·재실행·actor격리.
def render_research_tasks(actor):
    st.title('연구 질문을 과제로 맡기기')
    st.write('질문을 저장하고 한 번 실행하면, 공개 원문 근거와 선택한 논문 정보·등록 계산 결과를 모아드립니다.')
    st.caption('진행 순서: 근거 찾기 → 부족하면 선택 DOI 안에서 한 번 더 찾기 → 등록 숫자 비교 → 확인한 것과 남은 일 안내')
    st.caption('유료 AI 호출·외부 메시지 발송 없이 진행합니다. 선택한 DOI는 실행할 때 무료 Crossref 서지 API로 전송합니다.')
    notice = st.session_state.pop(scoped_key(actor, 'notice'), None)
    if notice:
        st.success(notice)
    with st.expander('이 도우미는 무엇을 해주나요?'):
        for role, explanation in TASK_TOOL_HELP.items():
            st.write(TASK_STEP_LABELS[role])
            st.text(explanation)
    try:
        store = get_store()
        tasks = store.list(actor)
    except (*STORE_ERRORS, ImportError):
        st.error('저장 과제를 열지 못했습니다. 과제 저장소의 연결·파일 상태를 확인한 뒤 다시 시도하세요.')
        return
    try:
        cases = list_cases()
    except (ValueError, OSError, KeyError, TypeError, ImportError):
        cases = []
        st.info('등록 계산 사례를 읽지 못했습니다. 원문 검색과 DOI 확인 과제는 만들 수 있습니다.')
    choices = {case['id']: case for case in cases}
    st.subheader('처음이라면 예시로 시작해 보세요')
    for case_id, label, question, query in TASK_EXAMPLES:
        if case_id in choices:
            if st.button(label, key=scoped_key(actor, 'example_' + case_id)):
                prefill_example(actor, case_id, question, query)
                st.info('예시를 아래 입력칸에 채웠습니다. 과제 저장과 실행은 각각 버튼으로 진행하세요.')
    st.caption('앱에 등록된 공개 자료를 이용하는 연습입니다. 예시 선택만으로 조회·저장·계산하지 않습니다.')
    st.subheader('1. 새 과제 만들기')
    st.caption('저장한 질문·조건은 바뀌지 않습니다. 다른 질문은 새 과제로 만들어 이전 보고서와 구분합니다. 개인정보·비공개 자료를 입력하지 마세요.')
    with st.form(scoped_key(actor, 'new_task')):
        question = st.text_area('궁금한 연구 질문', placeholder='예: 결측값을 어떻게 처리했나요?',
                                max_chars=1000, key=scoped_key(actor, 'question'))
        query = st.text_input('근거 검색어 · 선택사항', placeholder='예: missing data · 비워두면 질문으로 검색',
                              max_chars=1000, key=scoped_key(actor, 'query'))
        with st.expander('논문 정보·숫자 확인도 함께 하기 · 선택사항'):
            doi = st.text_input('정보를 확인할 논문 DOI', placeholder='예: 10.1234/example · 등록 사례 선택 시 해당 DOI 자동 사용',
                                max_chars=200, key=scoped_key(actor, 'doi'))
            case_id = st.selectbox('숫자 재계산 · 미리 등록된 공개 사례만', ['', *choices],
                                   format_func=lambda value: '계산하지 않음' if not value else choices[value]['label'],
                                   key=scoped_key(actor, 'case'))
            st.caption('등록 사례의 자료를 계산합니다. 검색으로 찾은 논문이나 내 원자료의 자동 분석이 아닙니다. 사례를 고르면 그 논문의 DOI도 함께 확인하며, 다른 DOI와 섞을 수 없습니다.')
        create = st.form_submit_button('과제 저장', type='primary', key=scoped_key(actor, 'create'))
    if create:
        if not question.strip():
            st.info('궁금한 연구 질문을 적어 주세요.')
        elif case_id and doi.strip() and doi.strip().lower() != choices[case_id]['doi'].lower():
            st.info('선택한 등록 계산 사례와 다른 DOI입니다. DOI를 비우면 그 사례의 DOI를 자동 사용합니다. 다른 논문은 별도 과제로 저장하세요.')
        else:
            try:
                effective_doi = doi.strip() or (choices[case_id]['doi'] if case_id else '')
                task = store.create(actor, question.strip(), query=query.strip(), doi=effective_doi, case_id=case_id, daily_hour=None)
                tasks = store.list(actor)
                st.session_state[scoped_key(actor, 'selected')] = task['id']
                st.success('과제를 저장했습니다. 아래 실행 버튼을 누르면 확인을 시작합니다.')
            except STORE_ERRORS:
                st.error('과제를 저장하지 못했습니다. 질문·DOI·선택한 등록 사례와 저장소 상태를 확인하세요.')
    st.subheader('2. 저장한 과제 열고 실행하기')
    st.caption('이 검토자 이름으로 저장한 과제만 표시합니다. 기본 저장소는 현재 서버의 SQLite 파일이며, 클라우드 재배포 뒤 영구 보관을 보장하지 않습니다. 보고서는 내려받아 보관하세요.')
    if not tasks:
        st.info('저장된 과제가 없습니다. 먼저 질문을 과제로 저장하세요.')
        return
    lookup = {task['id']: task for task in tasks}
    selection_key = scoped_key(actor, 'selected')
    if st.session_state.get(selection_key) not in lookup:
        st.session_state[selection_key] = tasks[0]['id']
    selected = st.selectbox('열어볼 저장 과제', list(lookup),
                            format_func=lambda value: lookup[value]['question'][:60] + ' · ' + TASK_STATUS_LABELS.get(lookup[value]['status'], '확인 필요'),
                            key=selection_key)
    try:
        task = store.get(actor, selected)
    except STORE_ERRORS:
        st.error('선택한 과제를 읽지 못했습니다. 다른 과제를 선택하거나 저장소 상태를 확인하세요.')
        return
    st.write('이 과제의 질문')
    st.text(task['question'])
    st.caption('저장된 검색어: ' + str(task.get('query') or '이 과제의 질문으로 검색'))
    st.write('상태: ' + TASK_STATUS_LABELS.get(task.get('status'), '확인 필요'))
    selected_case = choices.get(task.get('case_id'))
    if selected_case:
        st.caption('계산할 등록 사례: ' + selected_case['label'] + ' · ' + selected_case['scope'])
    if task.get('doi'):
        st.caption('서지를 확인할 DOI: ' + task['doi'])
        st.caption('기본 실행은 보관 원문을 검색합니다. 선택 DOI의 원문이 없으면 관련 문헌을 따로 표시하고 선택 논문은 미검토로 남깁니다.')
        st.caption('무료 OA 원문 포함 실행은 선택 DOI·검색어를 Europe PMC에 전송하고 OA·DOI·라이선스가 확인된 원문 조각만 읽습니다. 원문 전체 검토·유료 호출·모델 학습·자동 승인은 하지 않습니다.')
    label = '과제 다시 실행' if task.get('latest_run') else '과제 실행'
    if st.button(label, type='primary', key=scoped_key(actor, 'run_' + task['id']), disabled=task.get('status') == 'RUNNING'):
        try:
            with st.spinner('공개 원문 검색 → 선택한 논문 정보 확인 → 등록된 숫자 계산 → 보고서 저장 중…'):
                task = store.run(actor, task['id'])
            st.rerun()
        except STORE_ERRORS:
            st.error('이번 실행을 완료하지 못했습니다. 저장 상태를 확인하세요. 실행 중으로 남으면 15분 뒤 중단 복구를 사용할 수 있습니다.')
            try:
                task = store.get(actor, selected)
            except STORE_ERRORS:
                return
    if task.get('doi') and st.button('무료 OA 원문 포함하여 과제 실행',
                                     key=scoped_key(actor, 'run_oa_' + task['id']),
                                     disabled=task.get('status') == 'RUNNING'):
        try:
            with st.spinner('선택 DOI의 허용된 공개 원문 조각을 조회하고 새 보고서를 저장 중…'):
                task = store.run(actor, task['id'], retrieve_fulltext=True)
            st.rerun()
        except STORE_ERRORS:
            st.error('이번 공개 원문 포함 실행을 완료하지 못했습니다. 과거 원문은 이번 근거로 사용하지 않습니다. 저장 상태와 DOI 원문을 직접 확인하세요.')
            try:
                task = store.get(actor, selected)
            except STORE_ERRORS:
                return
    _result(task, actor)
    _schedule(task, actor, store)

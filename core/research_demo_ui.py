"""Three plain-language views of the existing deterministic workflow report."""
import json
import math
import streamlit as st
from core.paths import PROJECT_ROOT
from core.portfolio_workspace import claim_workflow_review
from core.research_tasks_ui import scoped_key


SCENES = ('1. 정상 · 행 수 산술 일치', '2. 근거 부족 · 계산 보류', '3. 자료 변경 · 이전 결과 재사용 금지')


def _next_scene(key):
    st.session_state[key] = SCENES[(SCENES.index(st.session_state[key]) + 1) % len(SCENES)]


def render_guided_demo(actor):
    opened = scoped_key(actor, 'guided_demo_open')
    scene_key = scoped_key(actor, 'guided_demo_scene')
    if st.session_state.get(opened):
        # [수정: 0 이영] 2026-09-30 21:05 KST — 사전 버전(case105) 고정 표기 대신 VERSION 파일 값 표시.
        st.caption(f"NAIS · v{(PROJECT_ROOT / 'VERSION').read_text(encoding='utf-8').strip()} · 공개 자료 체험")
    st.subheader('숫자가 맞아도, 근거가 바뀌면 다시 확인합니다')
    start, back = st.columns(2)
    if start.button('90초 근거 검증 체험', key='guided_demo_start', type='primary'):
        st.session_state[opened] = True
        st.session_state[scene_key] = SCENES[0]
        st.rerun()
    if not st.session_state.get(opened):
        st.caption('공개 펭귄 자료의 행 수를 세 장면으로 확인합니다. 유료 AI 호출 없이 진행합니다.')
        return False
    if back.button('연구 둘러보기로 돌아가기', key='guided_demo_close'):
        st.session_state[opened] = False
        st.rerun()
    st.caption('체험 순서: 정상 → 근거 부족 → 자료 변경. 90초는 안내 동선이며 실제 소요시간 측정값이 아닙니다.')
    scene = st.radio('확인할 장면', SCENES, key=scene_key, horizontal=True)
    # [수정: UI/UX 조지현] 2026-09-30 case105-UI / 지금 몇 번째 장면이고 다음이 무엇인지 한 줄로 표시. 판정 로직 무관.
    from core.theme import scene_progress
    st.markdown(scene_progress(SCENES, scene), unsafe_allow_html=True)
    try:
        report = claim_workflow_review()
        stages = {row['stage']: row for row in report['stages']}
        normal = stages['RECHECKED']['result']
        values = [normal[field] for field in ('reported_value', 'value', 'independent_value')]
        if (normal['action'] != 'ARITHMETIC_MATCH'
                or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values)
                or values[0] != values[1] or values[1] != values[2]
                or any(stages[name]['result']['action'] != 'BLOCK'
                       or stages[name]['result'].get('value') is not None
                       for name in ('MISSING_EVIDENCE', 'INPUT_CHANGED'))):
            raise ValueError('체험 장면의 실제 검산 상태가 기대 경계와 다릅니다.')
    except (ValueError, OSError, KeyError, TypeError, UnicodeError):
        st.error('현재 근거·자료·코드의 연결을 확인하지 못했습니다. 파일과 등록 지문을 확인한 뒤 다시 체험하세요.')
        return True
    st.info('이 체험의 정상은 등록된 행 수의 산술 일치입니다. 논문 전체가 참이라는 판정이나 사람 승인이 아닙니다.')
    st.caption('새 모델 호출 0회 · human_approval=false · 실제 승인 없음. 근거 누락과 자료 변경은 합성 오류입니다.')
    if scene == SCENES[0]:
        result = stages['RECHECKED']['result']
        st.success('등록된 행 수를 두 계산 경로로 확인했습니다.')
        for column, label, value in zip(st.columns(3), ('원래 보고값', '제품 계산값', '독립 계산값'),
                                        (result['reported_value'], result['value'], result['independent_value'])):
            column.metric(label, f'{value:g}행')
        known = (f"등록 원문 보고값은 {result['reported_value']:g}행입니다. 같은 공개 CSV에서 제품 경로는 "
                 f"{result['value']:g}행, 독립 계산 경로는 {result['independent_value']:g}행을 셌습니다.")
        unknown = '다른 주장·변수 의미·연구 방법의 타당성·논문 전체 재현은 확인하지 않았습니다.'
        next_action = '등록된 원문 위치와 인용을 확인하세요. 다른 주장에는 그 주장에 맞는 자료와 조건이 필요합니다.'
        selected = stages['RECHECKED']
    elif scene == SCENES[1]:
        selected = stages['MISSING_EVIDENCE']
        st.warning('근거 위치가 없어 계산을 보류했습니다. 합성 오류 장면입니다.')
        known = 'source_location을 빈 값으로 만든 사례는 BLOCK으로 차단되고 계산값을 만들지 않습니다.'
        unknown = '이 누락이 실제 AI 출력에서 발생했다는 증거는 없습니다. 원문 의미도 승인하지 않았습니다.'
        next_action = '기존 등록 원문에서 위치와 인용을 대조하고, 원문 위치를 복원한 뒤 다시 검산하세요.'
    else:
        selected = stages['INPUT_CHANGED']
        st.warning('자료 바이트가 달라져 이전 결과를 재사용하지 않습니다. 합성 변경 장면입니다.')
        known = '등록 지문과 현재 CSV가 달라 BLOCK으로 차단했습니다. 이전 344행 결과로 현재 자료를 승인하지 않습니다.'
        unknown = '지문은 파일 동일성을 확인합니다. 변경 이유·작성자 신원·자료의 진실성은 확인하지 않습니다.'
        next_action = '의도한 원자료와 등록 조건을 확인하고 다시 검산하세요. 해시를 자동으로 바꾸어 차단을 없애지 않습니다.'
    for column, title, text in zip(st.columns(3, border=True),
                                    ('확인한 것', '모르는 것', '다음 행동'), (known, unknown, next_action)):
        column.subheader(title)
        column.write(text)
    if scene == SCENES[1]:
        with st.expander('복구할 원문 위치와 인용'):
            repair = selected['repair']
            st.write('확인할 원문: ' + repair['source_file'])
            st.write('찾을 인용: ' + repair['source_quote'])
            st.write('기존 등록 위치: ' + report['mapping']['metadata']['source_location'])
    with st.expander('현재 장면의 검증 기록'):
        st.write({'단계': selected['stage'], '상태': selected['result']['action'],
                  '이유': selected['result']['reason'], '사람 의미 확인': selected['result']['source_scope_verified']})
        if scene == SCENES[2]:
            for row in report['change_scenarios'][0]['impact']['results']:
                st.write(f"{row['claim_id']}: {'변경 없음 · 별도 BAT 주장은 이 CSV에 의존하지 않음' if row['action'] == 'UNCHANGED' else '현재 자료 확인과 재검산 필요'}")
    st.button('다음 장면', key='guided_demo_next', on_click=_next_scene, args=(scene_key,))
    st.download_button('세 장면 검증 기록 JSON 내려받기', json.dumps(report, ensure_ascii=False, indent=2),
                       file_name='guided_demo_report.json', mime='application/json',
                       key='guided_demo_download', on_click='ignore')
    with st.expander('고정 사례 8건 확인'):
        st.caption('합성 4행의 미리 정한 기대값과 현재 등록 계산을 비교합니다. 실행 전에는 결과를 만들지 않습니다.')
        if st.button('고정 8건 실행', key='guided_demo_fixed_run'):
            try:
                from tools.fixed_demo_evaluation import run_fixed_demo_evaluation
                fixed = run_fixed_demo_evaluation()
            except (ValueError, OSError, KeyError, TypeError, UnicodeError):
                st.error('고정 입력 또는 기대값 지문이 다릅니다. 평가를 완료하지 못했습니다.')
            else:
                if fixed['all_passed']:
                    st.success(f"사전 고정 기대값 {fixed['passed_count']}/{fixed['case_count']}건 일치 · 차단 {fixed['actual_status_counts'].get('BLOCK', 0)}건")
                else:
                    st.error(f"사전 고정 기대값 불일치 {fixed['failed_count']}건 · 실패 기록을 확인하세요.")
                st.caption(fixed['limitations'] + ' 사람 승인 false · 새 모델 호출 0회.')
                st.dataframe([{'사례': row['id'], '조건': row['label'], '예상': row['expected']['action'],
                               '실제': row['actual']['action'], '일치': row['passed'],
                               '차이': ', '.join(row['different_fields'])} for row in fixed['cases']], hide_index=True)
                st.download_button('고정 8건 원출력 JSON 내려받기', json.dumps(fixed, ensure_ascii=False, indent=2),
                                   file_name='fixed_demo_evaluation.json', mime='application/json',
                                   key='guided_demo_fixed_download', on_click='ignore')
    return True

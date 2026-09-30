"""case95: explain an existing result without changing its statistical decision."""
from core.plain_language import STATISTIC_HELP


# 2026-09-29 case95: reuse the engine outcome; never invent population reference ranges.
# Check: tests/test_case95_guidance.py (blocked, descriptive and inferential paths).
def result_guidance(run, kind):
    if run.get('state') != 'EXECUTED':
        return {
            'meaning': '아직 계산하지 않았습니다. 숫자가 틀렸다는 판정은 아닙니다.',
            'next': '아래에 표시된 부족한 근거와 분석 조건을 확인하세요. 확보할 수 없으면 미확인으로 남겨도 됩니다.',
            'terms': [],
        }
    descriptive = kind == 'DESCRIPTIVE'
    method = (run.get('result') or {}).get('method', '')
    terms = ['tolerance']
    if descriptive and method == 'mean':
        terms.insert(0, 'mean')
    elif not descriptive:
        terms += ['p', 'ci']
        if kind == 'REGRESSION':
            terms += ['coefficient', 'se', 'df']
    return {
        'meaning': ('논문에 적힌 숫자와 선택한 자료로 다시 계산한 숫자를 비교했습니다. '
                    '일치는 이 계산의 재현 여부만 뜻하며 연구 결론의 옳고 그름을 확정하지 않습니다.'),
        'next': '대상·단위·빠진 자료·분석 방법이 원문과 같은지 확인하세요. 차이가 있으면 먼저 조건을 대조하세요.',
        'terms': [(key, STATISTIC_HELP[key]) for key in terms],
    }


def render_result_guidance(run, kind):
    import streamlit as st
    from core.plain_language import STATISTIC_LABELS
    guide = result_guidance(run, kind)
    st.info(guide['meaning'])
    st.caption('다음 할 일: ' + guide['next'])
    with st.expander('이 숫자를 어떻게 읽나요? · 평균과 정상 범위는 다릅니다'):
        st.write('정상·평균 범위는 대상과 단위가 같은 외부 기준 자료가 있어야 비교할 수 있습니다. 현재 결과에 공통 정상 범위를 적용하지 않습니다.')
        for key, value in guide['terms']:
            st.write(f"**{STATISTIC_LABELS[key]}** · {value}")
        st.write('사용 행은 실제 계산에 들어간 자료의 행 수입니다. 결측이나 조건 필터로 전체 자료보다 적을 수 있습니다.')

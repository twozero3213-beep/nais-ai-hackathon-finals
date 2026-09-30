"""Four visible review steps; presentation never grants scientific approval."""
# [작성: 0 이영 · Codex] 2026-10-01 KST — 조지현 공유 UI의 현재 단계만 강조하고 다음 행동을 명시한다.
import html
import streamlit as st

STEPS = ("근거 연결", "조건 확인", "지원 계산", "검토 기록")


def render_steps(step):
    current = min(4, max(1, int(step)))
    cells = []
    for index, title in enumerate(STEPS, 1):
        state = "current" if current == index else "done" if index < current else "waiting"
        label = "현재 단계" if state == "current" else "앞선 단계" if state == "done" else "다음 단계"
        cells.append(f'<div class="eg-review-step {state}" aria-label="{index} {html.escape(title)} · {label}"><b>{index:02}</b><span>{html.escape(title)}</span></div>')
    st.markdown('<div class="eg-review-steps" role="group" aria-label="검토 진행">' + ''.join(cells) + '</div>', unsafe_allow_html=True)


def move_step(key, step):
    st.session_state[key] = step
    st.rerun()

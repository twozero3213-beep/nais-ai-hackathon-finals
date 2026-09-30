# [작성: 0 이영 · Codex] 2026-09-30 23:48 KST — 사용자가 제공한 근거관문 HTML의 폭·글꼴·색상·카드·버튼을 실제 웹 화면에 적용한다.
"""Shared presentation tokens; no calculation or authorization decisions."""
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap');
:root{--canvas:#F9FAFB;--surface:#fff;--ink:#191F28;--sub:#66707A;--accent:#3182F6;--line:#E5E8EB;--action:#246FE0}
html,body,.stApp,[data-testid='stAppViewContainer'],[data-testid='stMain']{background:var(--canvas)!important;color:var(--ink)!important}
body,.stApp,p,li,label,input,textarea,select,button,h1,h2,h3,h4,[data-testid='stCaptionContainer']{
font-family:'IBM Plex Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif!important;word-break:keep-all}
.stMainBlockContainer{max-width:760px!important;padding:2rem 1.5rem 5rem!important}
.stMainBlockContainer p,.stMainBlockContainer li{font-size:16px;line-height:1.65}
h1{font-size:32px!important;line-height:1.3!important;font-weight:700!important;letter-spacing:-.035em!important;color:var(--ink)!important}
h2{font-size:30px!important;line-height:1.35!important;letter-spacing:-.035em!important;color:var(--ink)!important}
h3{font-size:22px!important;letter-spacing:-.025em!important;color:var(--ink)!important}
[data-testid='stCaptionContainer'] p{font-size:14px!important;color:var(--sub)!important;line-height:1.6!important}
a{color:#1C65CC}a:hover{text-decoration:underline}
[data-testid='stSidebar']{background:#fff!important;border-right:1px solid var(--line)!important}
[data-testid='stVerticalBlockBorderWrapper']>div,[data-testid='stVerticalBlockBorderWrapper']{border-color:var(--line)!important;border-radius:24px!important}
[data-testid='stVerticalBlockBorderWrapper']>div{background:var(--surface)!important;padding:1.35rem!important}
[data-testid='stButton'] button,[data-testid='stDownloadButton'] button,[data-testid='stFormSubmitButton'] button{
min-height:48px!important;border-radius:16px!important;border-color:var(--line)!important;font-weight:600!important;transition:background .16s ease}
button[kind='primary'],button[data-testid='stBaseButton-primary'],[data-testid='stFormSubmitButton'] button[kind='primary']{
background:var(--action)!important;color:#fff!important;border-color:var(--action)!important;min-height:56px!important}
button[kind='primary']:hover{background:#185EC8!important}
button:disabled{background:var(--line)!important;color:var(--sub)!important;border-color:var(--line)!important}
button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid var(--accent)!important;outline-offset:3px!important}
[data-testid='stTextInput'] input,[data-testid='stTextArea'] textarea{font-size:16px!important}
[data-testid='stTextInput']>div,[data-testid='stTextArea']>div,[data-baseweb='select']>div{border-radius:12px!important;background:#fff!important;border-color:var(--line)!important}
[data-testid='stExpander'] details{border:0!important;border-top:1px solid var(--line)!important;border-radius:0!important;background:transparent!important}
[data-testid='stTabs'] [role='tablist']{gap:22px;border-bottom:1px solid var(--line)}
[data-testid='stTabs'] button[role='tab']{min-height:48px;font-size:15px!important;color:var(--sub);white-space:nowrap}
[data-testid='stTabs'] button[aria-selected='true']{color:var(--ink)!important;font-weight:600}
[data-baseweb='tab-highlight']{background:var(--accent)!important}
[data-testid='stAlert']{border-radius:16px!important}
.eg-brand{display:flex;justify-content:space-between;align-items:center;margin:0 0 22px;gap:16px}
.eg-brand strong{font-size:18px;letter-spacing:-.04em;color:var(--ink)}.eg-brand span{font-size:13px;color:var(--sub)}
.eg-kicker{font-size:13px;font-weight:600;letter-spacing:.08em;color:#1C65CC;margin:0 0 20px}
.eg-intro{font-size:17px!important;color:var(--sub);line-height:1.75;max-width:34em;margin:14px 0 22px}
.eg-flow{display:flex;flex-wrap:wrap;gap:12px;font-size:15px;margin:0 0 18px}.eg-flow b{color:var(--sub);margin-right:7px}.eg-flow i{color:var(--sub);font-style:normal}
.eg-review-steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;border-bottom:1px solid var(--line);padding:12px 0 24px;margin:8px 0 24px}
.eg-review-step{display:flex;flex-direction:column;gap:6px;color:var(--sub);font-size:14px}.eg-review-step b{font-size:13px;font-variant-numeric:tabular-nums}.eg-review-step.current{color:#1C65CC;font-weight:700}.eg-review-step.done{color:var(--ink)}
.eg-footer{padding-top:3rem;color:var(--sub);font-size:13px;line-height:1.8}
.final-step{font-size:13px;letter-spacing:.07em;font-weight:600;color:#1C65CC;margin:0 0 10px}
.final-note{padding:14px 16px;border-left:3px solid var(--accent);background:#F5F8FF;border-radius:0 12px 12px 0;overflow-wrap:anywhere;line-height:1.65}
.final-summary{font-size:17px;line-height:1.7;color:var(--sub);margin:12px 0 24px}.final-kicker{font-size:13px;color:#1C65CC;font-weight:600;letter-spacing:.08em}.final-rule{display:none}
/* [수정: 0 이영] 참고 HTML의 회색 작은 글자와 파란 버튼은 읽기 대비를 높여 적용한다. */
@media(max-width:760px){.stMainBlockContainer{padding:1.5rem 1rem 4rem!important}h1{font-size:32px!important}h2{font-size:26px!important}.eg-brand{margin-bottom:32px}[data-testid='stHorizontalBlock']{flex-wrap:wrap;gap:1rem}[data-testid='stHorizontalBlock']>[data-testid='stColumn']{width:100%!important;flex:1 1 100%!important;min-width:0!important}[data-testid='stVerticalBlockBorderWrapper']>div{padding:1rem!important}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
</style>
"""


def render_theme():
    # [수정: 0 이영 · Codex] 2026-10-01 KST — 홍보 중심 카드 대신 검토 단계·목록, 왼쪽 탐색에 맞춘 폭과 중립 상태를 적용한다.
    st.markdown(CSS, unsafe_allow_html=True)


def render_brand():
    st.markdown('<div class="eg-brand"><strong>근거관문</strong><span>NAIS · 연구 데스크</span></div>', unsafe_allow_html=True)
    # [수정: 0 이영 · Codex] 2026-10-01 03:36 KST — main과 배포본의 불일치를 화면에서 대조할 수 있게 실제 Git 식별자만 노출한다.
    from core.source_revision import _git_sha
    with st.expander("실행정보"):
        st.caption("실행 Git · " + (_git_sha() or "식별자 미확인"))

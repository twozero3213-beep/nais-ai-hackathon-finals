"""case93-UI 화면 테마 — 블루·아이스블루·화이트, IBM Plex Sans KR.

[작성: UI/UX 담당 조지현] 2026-09-29 case93-UI
무엇: 팀 디자인 인계(색·글꼴)를 앱 전체에 적용하는 표시 전용 스타일 / 왜: 한 화면에서 현재 단계와 다음 행동이 보이고,
블루 중심으로 가독성을 높이며 주의 표시는 제한적으로 사용 / 입력·출력: 없음 → CSS 문자열 / 검증: tests/test_case105_uiux_theme.py.
core/ui.py의 기존 3색 팔레트(PALETTE·CSS)는 기존 시험 계약 때문에 그대로 두고, 이 파일이 그 위에 덮어 적용된다.
판정·계산·기록 로직과 무관하다.
[수정: UI/UX 담당 조지현] 2026-09-30 case105-UI / 연구 데스크 첫 화면 배너(.nais-hero)를 네이비→블루로 통일하고,
90초 체험의 세 장면 진행 표시(scene_progress)를 추가. 배너 HTML과 판정 로직은 바꾸지 않음.
"""

THEME = {
    "primary_blue": "#1766BD",
    "navy_text": "#123F71",
    "ice_blue_surface": "#F3FAFF",
    "soft_blue_surface": "#F6FBFF",
    "line": "#D7E9F9",
    "white": "#FFFFFF",
}
FONT_FAMILY = "'IBM Plex Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif"

THEME_CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap');
:root{--navy:#123F71;--teal:#1766BD;--line:#D7E9F9;--surface:#F6FBFF;--soft:#F3FAFF;--muted:rgba(18,63,113,.70);
 --gc-blue:#1766BD;--gc-navy:#123F71;--gc-ice:#F3FAFF;--gc-soft:#F6FBFF;--gc-line:#D7E9F9}
html,body,[data-testid="stAppViewContainer"],[data-testid="stSidebar"],.stMarkdown,p,li,label,h1,h2,h3,h4,h5,
button,input,textarea,select,[data-testid="stMetricValue"],[data-testid="stMetricLabel"],[data-testid="stCaptionContainer"]{
 font-family:'IBM Plex Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif}
[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:#FFFFFF}
h1,h2,h3,h4{color:#123F71!important;letter-spacing:-.01em}
[data-testid="stSidebar"]{background:#F3FAFF!important;border-right:1px solid #D7E9F9!important}
.stButton>button,[data-testid="stDownloadButton"]>button{border-radius:10px;border-color:#D7E9F9}
.stButton>button[kind="primary"],button[data-testid="stBaseButton-primary"]{background:#1766BD!important;border-color:#1766BD!important;color:white!important}
.stButton>button[kind="primary"]:hover,button[data-testid="stBaseButton-primary"]:hover{background:#123F71!important;border-color:#123F71!important}
[data-testid="stExpander"] details{border:1px solid #D7E9F9!important;border-radius:12px!important;background:#FFFFFF}
[data-testid="stExpander"] summary{color:#123F71;font-weight:600}
[data-testid="stVerticalBlockBorderWrapper"]{border-color:#D7E9F9!important;border-radius:14px!important}
[data-testid="stTabs"] button[role="tab"]{font-weight:600;color:rgba(18,63,113,.72)}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{color:#1766BD}
[data-testid="stTabs"] [data-baseweb="tab-highlight"]{background-color:#1766BD}
.eg-hero,.eg-panel,.eg-card,.eg-value,.eg-start,.eg-step,.eg-selected,.eg-result-hero{background:#F6FBFF!important;border-color:#D7E9F9!important}
.eg-step-no,.eg-result-arrow{color:#1766BD!important}
.eg-summary>div{background:#FFFFFF!important;border:1px solid #D7E9F9!important}
.eg-summary-v{color:#123F71!important}
.eg-summary .eg-attn{background:#F3FAFF!important;border:1px solid #1766BD!important}
.eg-summary .eg-attn .eg-summary-v{color:#1766BD!important}
/* 단계 머리표: 01 → 02 → 03 */
.gc-step{display:flex;align-items:center;gap:12px;margin:2px 0 6px}
.gc-step-no{flex:none;font-weight:700;font-size:.82rem;letter-spacing:.06em;color:#FFFFFF;background:#1766BD;border-radius:999px;padding:4px 12px}
.gc-step-title{font-weight:700;font-size:1.18rem;color:#123F71}
.gc-step-state{margin-left:auto;font-size:.8rem;font-weight:600;color:#1766BD;background:#F3FAFF;border:1px solid #D7E9F9;border-radius:999px;padding:3px 10px}
.gc-hero{border:1px solid #D7E9F9;background:#F3FAFF;border-radius:18px;padding:26px 30px;margin:4px 0 14px}
.gc-hero-kicker{font-size:.8rem;font-weight:700;letter-spacing:.08em;color:#1766BD}
.gc-hero-title{font-size:1.9rem;font-weight:700;color:#123F71;line-height:1.3;margin:6px 0 8px}
.gc-hero-sub{font-size:1rem;color:rgba(18,63,113,.78);line-height:1.6;max-width:820px}
.gc-flow{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.gc-flow span{font-size:.86rem;font-weight:600;color:#123F71;background:#FFFFFF;border:1px solid #D7E9F9;border-radius:999px;padding:5px 12px}
.gc-task{border:1px solid #D7E9F9;border-radius:12px;background:#FFFFFF;padding:12px 16px;margin:8px 0}
.gc-task-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.gc-task-pri{font-size:.75rem;font-weight:700;color:#1766BD;background:#F3FAFF;border:1px solid #D7E9F9;border-radius:999px;padding:2px 9px}
.gc-task-role{font-size:.85rem;font-weight:600;color:rgba(18,63,113,.75)}
.gc-task-title{font-weight:700;color:#123F71;margin-top:5px}
.gc-task-meta{font-size:.84rem;color:rgba(18,63,113,.70);margin-top:3px}
/* case105: 연구 데스크 첫 화면 배너 — 네이비→블루 (research_home.py의 청록 그라데이션 위에 덮어씀) */
.nais-hero{background:linear-gradient(115deg,#123F71 0%,#1766BD 100%)!important;box-shadow:0 12px 32px rgba(18,63,113,.14)!important}
.nais-hero h1,.nais-hero h1 *{color:#FFFFFF!important}
.nais-hero .eyebrow{color:#CFE6FA!important}
.nais-hero p{color:#E9F4FF!important}
.nais-steps span{border-color:rgba(255,255,255,.38)!important;background:rgba(255,255,255,.10)!important}
[data-testid="stAlert"]{border-radius:12px}
/* case105: 90초 체험 세 장면 진행 표시 */
.gc-scenes{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:4px 0 12px}
.gc-scene{font-size:.86rem;font-weight:600;color:rgba(18,63,113,.62);background:#FFFFFF;border:1px solid #D7E9F9;border-radius:999px;padding:5px 12px}
.gc-scene.done{color:#123F71;background:#F3FAFF}
.gc-scene.now{color:#FFFFFF;background:#1766BD;border-color:#1766BD}
.gc-scene-arrow{color:#1766BD;font-weight:700}
.gc-scene-next{font-size:.84rem;color:rgba(18,63,113,.75);margin-left:4px}
@media(max-width:640px){.gc-hero{padding:18px}.gc-hero-title{font-size:1.45rem}.gc-step-state{margin-left:0}}
</style>"""


def scene_progress(scenes, current):
    """90초 체험 진행 표시 HTML. scenes는 고정 장면 이름 튜플, current는 지금 장면. 사용자 입력은 넣지 않는다."""
    import html
    index = scenes.index(current)
    parts = []
    for number, name in enumerate(scenes):
        state = 'now' if number == index else ('done' if number < index else '')
        label = name.split('. ', 1)[-1]
        parts.append(f"<span class='gc-scene {state}'>{number + 1:02d} {html.escape(label)}</span>")
    hint = ("다음 장면: " + html.escape(scenes[index + 1].split('. ', 1)[-1])) if index + 1 < len(scenes) else "마지막 장면"
    joined = "<span class='gc-scene-arrow'>→</span>".join(parts)
    return f"<div class='gc-scenes'>{joined}<span class='gc-scene-next'>{hint}</span></div>"


def step_header(number, title, state=""):
    """01·02·03 단계 머리표 HTML. state는 오른쪽 작은 상태 표시(예: '완료', '대기')."""
    import html
    badge = f"<span class='gc-step-state'>{html.escape(state)}</span>" if state else ""
    return (f"<div class='gc-step'><span class='gc-step-no'>{html.escape(number)}</span>"
            f"<span class='gc-step-title'>{html.escape(title)}</span>{badge}</div>")

# [작성: 0 이영 · Codex] 2026-09-30 23:50 KST — 연구 발견·실제 검산·인증된 팀 작업을 한 사이트의 탐색으로 연결한다.
from pathlib import Path
import streamlit as st
ROOT=Path(__file__).resolve().parent
st.set_page_config(page_title="근거관문 · 연구 데스크",page_icon=":material/fact_check:",layout="wide",initial_sidebar_state="expanded")
# [수정: 3 조지현] 2026-10-01 08:25 KST — 사용자 요청으로 왼쪽 상단 근거관문 로고와 사이드바 강조 표시를 더한다. 이영의 페이지 구성·순서·계산·승인 로직은 그대로다.
st.logo(str(ROOT/"assets/brand/logo.svg"),size="large",icon_image=str(ROOT/"assets/brand/icon.svg"))
st.markdown("""<style>
[data-testid='stSidebar']{background:#fff!important;border-right:1px solid #E5E8EB!important}
[data-testid='stSidebarHeader'] img{height:40px!important;max-height:40px!important}
[data-testid='stSidebarNav'] a{border-radius:14px!important;padding:10px 14px!important;margin:2px 0!important}
[data-testid='stSidebarNav'] a span:not([data-testid='stIconMaterial']){font-size:16px!important;color:#333D4B!important}
[data-testid='stSidebarNav'] a[aria-current='page']{background:#EAF2FF!important}
[data-testid='stSidebarNav'] a[aria-current='page'] span:not([data-testid='stIconMaterial']){color:#1C65CC!important;font-weight:700!important}
[data-testid='stSidebarNav'] [data-testid='stIconMaterial']{color:#4E5968!important}
[data-testid='stSidebarNav'] a[aria-current='page'] [data-testid='stIconMaterial']{color:#1C65CC!important}
</style>""",unsafe_allow_html=True)
pages=[
    st.Page(str(ROOT/"0_이영_연구데스크.py"),title="연구 데스크",icon=":material/search:",default=True),
    st.Page(str(ROOT/"0_이영_연구연동.py"),title="원논문·원자료 검토",icon=":material/hub:",url_path="research"),
    st.Page(str(ROOT/"finals/app.py"),title="근거 검산",icon=":material/fact_check:",url_path="verify"),
    st.Page(str(ROOT/"0_이영_팀작업실.py"),title="팀 작업실",icon=":material/groups:",url_path="team"),
]
# [수정: 0 이영 · Codex] 2026-10-01 KST — 팀 공유 UI의 왼쪽 탐색을 유지하고 원자료 수신·검산을 같은 사이트에 연결한다.
st.navigation(pages,position="sidebar").run()

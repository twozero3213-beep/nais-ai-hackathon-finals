# [작성: 0 이영 · Codex] 2026-09-30 23:50 KST — 연구 발견·실제 검산·인증된 팀 작업을 한 사이트의 탐색으로 연결한다.
from pathlib import Path
import streamlit as st
ROOT=Path(__file__).resolve().parent
st.set_page_config(page_title="근거관문 · 연구 데스크",page_icon=":material/fact_check:",layout="wide",initial_sidebar_state="expanded")
pages=[
    st.Page(str(ROOT/"0_이영_연구데스크.py"),title="연구 데스크",icon=":material/search:",default=True),
    st.Page(str(ROOT/"0_이영_연구연동.py"),title="원논문·원자료 검토",icon=":material/hub:",url_path="research"),
    st.Page(str(ROOT/"finals/app.py"),title="근거 검산",icon=":material/fact_check:",url_path="verify"),
    st.Page(str(ROOT/"0_이영_팀작업실.py"),title="팀 작업실",icon=":material/groups:",url_path="team"),
]
# [수정: 0 이영 · Codex] 2026-10-01 KST — 팀 공유 UI의 왼쪽 탐색을 유지하고 원자료 수신·검산을 같은 사이트에 연결한다.
st.navigation(pages,position="sidebar").run()

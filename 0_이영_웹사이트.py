# [작성: 0 이영 · Codex] 2026-09-30 23:50 KST — 연구 발견·실제 검산·인증된 팀 작업을 한 사이트의 탐색으로 연결한다.
from pathlib import Path
import streamlit as st
ROOT=Path(__file__).resolve().parent
st.set_page_config(page_title="근거관문 · 연구 데스크",page_icon=":material/fact_check:",layout="wide",initial_sidebar_state="collapsed")
pages=[
    st.Page(str(ROOT/"0_이영_연구데스크.py"),title="연구 데스크",icon=":material/search:",default=True),
    st.Page(str(ROOT/"finals/app.py"),title="근거 검산",icon=":material/fact_check:",url_path="verify"),
    st.Page(str(ROOT/"0_이영_팀작업실.py"),title="팀 작업실",icon=":material/groups:",url_path="team"),
]
st.navigation(pages,position="top").run()

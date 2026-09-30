"""공개 연구 발견과 세션 과제, 출처별 관측 시각을 연결하는 연구 데스크."""
# [작성: 0 이영 · Codex] 2026-09-30 KST — 참고 화면의 흐름을 실제 공개 검색과 연결한다.
# 기존 계산·인증 코드는 변경하지 않으며, 실시간 조회/보관 목록/과제 저장을 구분한다.
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qsl
from uuid import uuid4

import streamlit as st

from core import paper_discovery, research_data_sources, research_digest, research_news, public_agent
from core.research_tasks import SECRET_PATTERN

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "data/0_이영_연구데스크_스냅샷.json"
KST = timezone(timedelta(hours=9))
EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
TABS = ["논문 둘러보기", "공공·위성 데이터", "연구 과제", "대학 연구 소식", "연구 관심 순위", "다른 AI와 연결"]
PROMPT = "첨부한 공개 설명·예제의 지원 범위와 미확인 조건을 먼저 설명해 주세요. 입력 변경이 재검산을 요구하는 주장과 영향받지 않은 주장을 구분해 주세요. 연구자가 최종 판단합니다."


def _clean(value, limit=1000):
    text = str(value or "")[:limit]
    if EMAIL.search(text) or SECRET_PATTERN.search(text):
        return "비공개 정보가 포함되어 표시하지 않았어요."
    return text


def _md(value):
    return re.sub(r"([\\`*_{}\[\]<>()!#|])", r"\\\1", _clean(value))


def _time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return "시각 미확인"
        return stamp.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    except (ValueError, TypeError):
        return "시각 미확인"


def _safe_url(value):
    if (not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 32 for c in value)
            or EMAIL.search(value) or SECRET_PATTERN.search(value)):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            return None
        if parts.hostname in {"localhost", "127.0.0.1", "::1"} or parts.port not in (None, 443):
            return None
        if any(re.search(r"key|token|password|secret", key, re.I) for key, _ in parse_qsl(parts.query)):
            return None
        return value
    except ValueError:
        return None


@st.cache_data(show_spinner=False)
def _snapshot(file_stamp):
    # 256KiB 상한과 고정 경로만 읽고 원본 참고 HTML을 실행하지 않는다.
    with SNAPSHOT.open("rb") as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError("SNAPSHOT_TOO_LARGE")
    return json.loads(raw)


@st.cache_data(show_spinner=False)
def _digest():
    try:
        return research_digest.load_digest(ROOT / "data/research_digest.json")
    except (OSError, ValueError, TypeError, KeyError):
        return {"entries": []}


@st.cache_data(ttl=300, max_entries=32, show_spinner=False)
def _papers(query, mode):
    return paper_discovery.search_papers(query, mode=mode, years=3 if mode == "cited" else 1, limit=8)


@st.cache_data(ttl=300, max_entries=32, show_spinner=False)
def _data(source, query):
    options = {"world_bank": {"mode": "observations"}, "usgs": {"region": "korea"}}
    return research_data_sources.search_research_data(source, query, limit=5, **options.get(source, {}))


@st.cache_data(ttl=300, max_entries=8, show_spinner=False)
def _news(source):
    return research_news.fetch_research_news(source)


@st.cache_data(show_spinner=False)
def _public_zip():
    return public_agent.public_download_zip()


def _verify_link():
    if (ROOT / "finals/app.py").is_file():
        st.page_link(str(ROOT / "finals/app.py"), label="90초 근거 검증 체험 해볼게요", icon=":material/play_arrow:")
    else:
        st.info("본선 검산은 공개 검산 페이지에서 실행할 수 있어요.")


def _save_task(question, query="", doi=""):
    if not question.strip() or len(question) > 1000 or EMAIL.search(question) or SECRET_PATTERN.search(question):
        st.error("공개 연구 질문을 1~1,000자로 적어 주세요. 연락처와 비밀값은 저장하지 않아요.")
        return
    if query and (len(query) > 300 or EMAIL.search(query) or SECRET_PATTERN.search(query)):
        st.error("검색어에서 연락처와 비밀값을 제거해 주세요.")
        return
    tasks = st.session_state["desk_tasks"]
    if len(tasks) >= 20:
        st.info("이 세션에서는 과제를 20개까지 보관해요. 내려받은 뒤 정리해 주세요.")
        return
    tasks.insert(0, {"id": uuid4().hex, "question": question.strip(), "query": query.strip(), "doi": doi,
                     "status": "실행 대기 · 저장만 완료", "saved_at": datetime.now(KST).isoformat()})
    st.toast("연구 과제로 담았어요.")


def _paper_rows(items, prefix, ranked=False):
    if not items:
        st.info("조건에 맞는 논문이 없어요. 검색어를 바꾸거나 보관된 분야 목록을 살펴보세요.")
    for i, paper in enumerate(items[:8]):
        with st.container(border=True):
            st.markdown((f"**{i + 1}.** " if ranked else "") + "**" + _md(paper.get("title")) + "**")
            count = paper.get("citations")
            citations = f"누적 인용 {count:,}회" if type(count) is int else "인용 수 미확인"
            st.caption(_clean(paper.get("journal") or "학술지 미확인") + " · 발행 " + _clean(paper.get("published") or "미확인") + " · " + citations)
            link = _safe_url(paper.get("url"))
            if link:
                st.link_button("논문 출처 열기", link, key=f"{prefix}_link_{i}")
            if st.button("과제로 담아둘게요", key=f"{prefix}_save_{i}"):
                _save_task("이 논문의 내용과 한계를 공개 근거로 검토해 주세요: " + _clean(paper.get("title"), 800), doi=_clean(paper.get("doi"), 200))


def _paper_screen(snapshot):
    st.header("어떤 연구가 궁금하세요?")
    topics = {k: v for k, v in snapshot["topics"].items() if "penguin" not in k.lower() and "펭귄" not in v.get("label", "")}
    topic = st.selectbox("관심 분야", list(topics), format_func=lambda k: topics[k]["label"], key="desk_topic")
    field = st.selectbox("다른 분야", [None] + list(range(len(snapshot["fields"]))),
                         format_func=lambda i: "세부 분야 30개 중 고르기" if i is None else snapshot["fields"][i]["label"])
    chosen = topics[topic] if field is None else snapshot["fields"][field]
    with st.form("desk_paper_search"):
        query = st.text_input("논문 검색어", value=chosen["query"], max_chars=300, key=f"desk_query_{topic}_{field}")
        mode = st.radio("어떤 논문부터 볼까요?", ["latest", "cited"], horizontal=True,
                        format_func=lambda k: "최근 발행" if k == "latest" else "최근 3년 · 누적 인용 많은 순")
        submitted = st.form_submit_button("논문 찾아볼게요", type="primary", use_container_width=True)
    st.caption("버튼을 누르면 검색어를 무료 공개 Crossref API로 보내요. 개인정보·비공개 자료는 적지 마세요.")
    if submitted:
        try:
            if EMAIL.search(query):
                raise ValueError("PRIVATE_QUERY")
            with st.spinner("공개 논문 목록을 찾고 있어요…"):
                st.session_state["desk_paper_live"] = _papers(query, mode)
        except Exception:
            st.session_state.pop("desk_paper_live", None)
            st.error("논문을 불러오지 못했어요. 검색어를 확인하고 다시 시도해 주세요. 아래는 보관된 목록이에요.")
    result = st.session_state.get("desk_paper_live")
    if result:
        st.caption("실시간 API 조회 결과 · " + _time(result.get("checked_at")) + " · " + _clean(result.get("query")))
        _paper_rows(result.get("items", []), "desk_live")
    else:
        st.caption("보관된 검색 스냅샷 · " + _time(chosen.get("checked_at")) + " · 현재 선택 분야")
        _paper_rows(chosen.get(mode, chosen.get("items", [])), "desk_snapshot")
    st.caption("목록은 공개 서지 표본이에요. 전체 문헌 범위·원문 확보·논문 품질은 아직 확인하지 않았어요.")


def _data_screen(snapshot):
    st.header("연구에 쓸 공개 데이터 찾기")
    catalog = research_data_sources.source_catalog()
    sources = {x["id"]: x for x in catalog}
    source = st.selectbox("자료 출처", list(sources), index=list(sources).index("world_bank"),
                          format_func=lambda s: sources[s]["name"], key="desk_data_source")
    with st.form("desk_data_search"):
        query = st.text_input("자료 검색어 · 선택", max_chars=300, key="desk_data_query", help="World Bank 한국 인구 관측과 USGS 지진은 검색어를 비워 주세요.")
        submitted = st.form_submit_button("이 출처에서 찾아볼게요", type="primary", use_container_width=True,
                                         disabled=sources[source]["status"] == "NEEDS_KEY")
    if sources[source]["status"] == "NEEDS_KEY":
        st.info("이 출처는 팀의 연결 설정이 필요해요. 키를 입력하거나 업로드할 필요는 없어요.")
    if submitted:
        try:
            if EMAIL.search(query):
                raise ValueError("PRIVATE_QUERY")
            with st.spinner("원래 제공처에서 목록을 찾고 있어요…"):
                st.session_state["desk_data_" + source] = _data(source, query)
        except Exception:
            st.session_state.pop("desk_data_" + source, None)
            st.error("자료를 불러오지 못했어요. 검색 조건을 확인하고 다시 시도해 주세요.")
    live = st.session_state.get("desk_data_" + source)
    result = live or snapshot["data"].get(source)
    if result:
        st.caption(("실시간 API 조회 결과 · " if live else "보관된 자료 스냅샷 · ") + _time(result.get("checked_at")))
        if result.get("status") not in {"OK", "EMPTY"}:
            st.info("이 조건의 조회는 완료되지 않았어요. 원래 제공처를 확인하거나 다시 시도해 주세요.")
        elif not result.get("items"):
            st.info("조회했지만 조건에 맞는 기록이 없었어요.")
        for item in result.get("items", [])[:5]:
            with st.container(border=True):
                st.markdown("**" + _md(item.get("title")) + "**")
                if item.get("value") is not None:
                    st.write(str(item["value"]) + " " + _clean(item.get("unit") or "단위 미확인"))
                st.caption("자료 시점 · " + _clean(item.get("temporal") or "미확인"))
                if link := _safe_url(item.get("url")):
                    st.link_button("원래 제공처에서 보기", link)
    st.caption("데이터 설명과 일부 관측값이에요. 원자료 다운로드·이용 승인·연구 결론의 검증은 별도로 확인해요.")


def _task_screen():
    st.header("연구 질문을 과제로 남기기")
    st.write("궁금한 내용을 저장하고, 공개 검산 체험이나 로그인한 팀 작업실에서 이어가세요.")
    with st.form("desk_task_form", clear_on_submit=True):
        question = st.text_area("궁금한 연구 질문", max_chars=1000, key="desk_task_question", placeholder="예: 공개 펭귄 자료의 행 수를 논문의 보고값과 비교해 주세요.")
        query = st.text_input("근거 검색어 · 선택", max_chars=300, key="desk_task_query")
        save = st.form_submit_button("과제로 저장할게요", type="primary", use_container_width=True)
    if save:
        _save_task(question, query)
    st.caption("현재 브라우저 세션에만 보관해요. 저장은 연구 실행·AI 성공·사람 승인을 뜻하지 않아요.")
    for task in list(st.session_state["desk_tasks"]):
        with st.container(border=True):
            st.markdown(_md(task["question"]))
            st.caption(task["status"] + " · " + _time(task["saved_at"]))
            if st.button("과제 지우기", key="desk_delete_" + task["id"]):
                st.session_state["desk_tasks"].remove(task)
                st.rerun()
    if st.session_state["desk_tasks"]:
        payload = {"version": 0, "execution_performed": False, "tasks": st.session_state["desk_tasks"]}
        st.download_button("저장한 과제 내려받기", json.dumps(payload, ensure_ascii=False, indent=2),
                           file_name="0_이영_연구과제.json", mime="application/json", on_click="ignore")
    _verify_link()


def _news_screen(snapshot):
    st.header("대학 연구 소식")
    source = st.selectbox("대학 소식 출처", list(research_news.SOURCES),
                          format_func=lambda k: research_news.SOURCES[k]["label"], key="desk_news_source")
    if st.button("최신 연구 소식 불러오기", key="desk_news_load", type="primary", use_container_width=True):
        try:
            with st.spinner("대학 공식 RSS/API를 확인하고 있어요…"):
                st.session_state["desk_news_" + source] = _news(source)
        except Exception:
            st.session_state.pop("desk_news_" + source, None)
            st.error("소식을 불러오지 못했어요. 아래는 보관된 소식이에요.")
    live = st.session_state.get("desk_news_" + source)
    saved = next((e["data"] for e in _digest()["entries"] if e["id"] == "news:" + source and e.get("data")), None)
    result = live or saved or next((n for n in snapshot["news"] if n["id"] == source), {})
    st.caption(("실시간 RSS/API 조회 결과 · " if live else "보관된 소식 · 실시간 갱신 아님 · ") + _time(result.get("as_of")))
    if not result.get("articles"):
        st.info("표시할 소식이 없어요. 공식 출처를 확인하거나 다시 불러와 주세요.")
    for article in result.get("articles", [])[:8]:
        with st.container(border=True):
            st.markdown("**" + _md(article.get("title")) + "**")
            st.caption("소식 발행 · " + _clean(article.get("published") or "미확인"))
            if link := _safe_url(article.get("link")):
                st.link_button("대학 공식 소식 열기", link)


def _rank_screen(snapshot):
    st.header("어떤 연구에 관심이 모였을까요?")
    st.write("최근 3년 안에 발행된 논문의 조회 시점 누적 인용 수예요. 최근 1년 인용 수나 연구 품질 점수가 아니에요.")
    topics = {k: v for k, v in snapshot["topics"].items() if "penguin" not in k.lower() and "펭귄" not in v.get("label", "")}
    topic = st.selectbox("관심 순위 분야", list(topics), format_func=lambda k: topics[k]["label"])
    selected = topics[topic]
    st.caption("보관된 Crossref 검색 스냅샷 · " + _time(selected.get("checked_at")))
    rows = sorted(selected.get("cited", []), key=lambda p: p.get("citations") if type(p.get("citations")) is int else -1, reverse=True)
    _paper_rows(rows, "desk_rank", ranked=True)


def _ai_screen():
    st.header("다른 AI와 함께 근거를 확인하세요")
    st.write("공개 설명과 고정 예제 4개를 내려받아 파일 첨부를 지원하는 AI에 전달하세요.")
    try:
        st.download_button("공개 설명·예제 ZIP 내려받기", _public_zip(), file_name="0_이영_공개설명예제.zip",
                           mime="application/zip", type="primary", use_container_width=True, on_click="ignore")
    except (OSError, ValueError, KeyError, TypeError):
        st.error("공개 파일 검증을 완료하지 못해 다운로드를 중단했어요. 본선 검산 페이지의 공개 결과를 확인해 주세요.")
    st.code(PROMPT, language=None, wrap_lines=True)
    st.caption("코드 오른쪽 복사 버튼으로 요청 문구를 가져갈 수 있어요.")
    st.write("프로젝트를 설치한 PC에서는 MCP를 지원하는 AI 도구에 stdio 서버를 등록할 수 있어요.")
    st.code("python -m tools.research_mcp", language=None)
    st.caption("공개 웹 주소의 외부 파일 조회와 원격 MCP 실행은 확인되지 않았어요. ZIP 전달과 로컬 MCP를 구분해요.")


def main():
    try:
        theme = importlib.import_module("core.0_이영_웹테마")
        theme.render_theme()
        theme.render_brand()
    except ModuleNotFoundError as exc:
        if exc.name != "core.0_이영_웹테마":
            raise
    st.session_state.setdefault("desk_tasks", [])
    try:
        # [수정: 0 이영] 2026-10-01 00:02 KST — 선별 목록 갱신 때 캐시도 파일 관측 키로 갱신한다.
        snapshot = _snapshot(SNAPSHOT.stat().st_mtime_ns)
    except (OSError, ValueError, TypeError):
        st.error("보관된 연구 목록을 읽지 못했어요. 본선 검산 페이지에서 공개 사례를 확인해 주세요.")
        _verify_link()
        return
    # [수정: 0 이영 · Codex] 2026-10-01 KST — 팀 공유 UI대로 짧은 작업 제목과 검토 예제 목록을 먼저 제공한다.
    st.title("확인할 수치를 고르고, 근거부터 검토하세요")
    st.caption("원논문과 자료를 연결한 뒤 조건을 확인하고, 계산과 검토 기록을 남깁니다.")
    st.page_link(str(ROOT / "0_이영_연구연동.py"), label="원논문·원자료 찾아 검토하기", icon=":material/hub:")
    with st.expander("검토 예제"):
        for title, description in (("근거 위치 누락", "발행사 원문과 근거 위치가 없는 주장"), ("집계 조건 차이", "행 누락·결측 처리·필터 차이"), ("같은 자료, 바뀐 조건", "조건이나 파일이 바뀌면 이전 결과 재사용 차단")):
            st.markdown("**" + title + "** · " + description)
        _verify_link()
    with st.expander("자료와 검토 범위"):
        st.caption("아래는 수집 시각을 보존한 논문 목록과 등록 검토 사례입니다. 새 자료 검색·다운로드·재계산은 실행한 단계별로 표시하며, 수치 일치를 논문 전체 승인으로 처리하지 않습니다.")
    for tab, render in zip(st.tabs(TABS), [_paper_screen, _data_screen, _task_screen, _news_screen, _rank_screen, _ai_screen]):
        with tab:
            # Streamlit magic가 조건식의 반환 None을 본문으로 쓰지 않게 명시적으로 호출한다.
            if render in {_paper_screen, _data_screen, _news_screen, _rank_screen}:
                render(snapshot)
            else:
                render()
    st.caption("근거관문 · AI는 제안하고, 규칙 엔진이 계산하고, 연구자가 판단해요.")


if __name__ == "__main__":
    main()

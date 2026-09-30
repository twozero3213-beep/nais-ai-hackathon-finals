"""Research discovery to bounded bytes, deterministic calculation and review."""
# [작성: 0 이영 · Codex] 2026-10-01 KST — 전체 연동 지시와 조지현 UI를 같은 네 단계 동선에 구현한다.
from __future__ import annotations
import hashlib
import importlib
import json
from urllib.parse import urlsplit

import streamlit as st

from core.review_steps_ui import move_step, render_steps
from core.scholar_discovery import scholar_discovery
from core.team_workspace import MEMBERS, member_role
from evidence_gate.spec import empty_spec
from finals.finals_privacy import sensitive_kinds


def _url(value):
    if not isinstance(value, str) or len(value) > 2000 or sensitive_kinds(value):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme == "https" and parts.hostname and not parts.username and not parts.password and parts.port in (None, 443):
            return value
    except ValueError:
        pass
    return None


def _public(value):
    # 외부 텍스트는 실행하지 않고 표시하며 인증값·연락처를 내보내지 않는다.
    if isinstance(value, str):
        return "[비공개 형태 제외]" if sensitive_kinds(value) else value
    if isinstance(value, dict):
        return {k: _public(v) for k, v in value.items() if k not in {"raw_bytes", "api_key", "token", "authorization", "password"}}
    if isinstance(value, list):
        return [_public(v) for v in value]
    return value


def _reset_result():
    state = st.session_state.setdefault("ri_state", {})
    for name in ("report", "approval"):
        state.pop(name, None)
    st.session_state["ri_step"] = min(st.session_state.get("ri_step", 1), 2)
    state["conditions_confirmed"] = False
    st.session_state["ri_conditions_confirmed"] = False
    st.session_state["ri_confirm"] = False
    st.session_state["ri_reason"] = ""


def _discovery(router, state):
    with st.form("ri_search_form"):
        query = st.text_input("제목·DOI·연구 질문", max_chars=300)
        names = list(router.SEARCH_PROVIDERS)
        selected = st.multiselect("검색 출처", names, default=[n for n in ("crossref", "zenodo") if n in names])
        submitted = st.form_submit_button("출처 찾기")
    if submitted:
        with st.spinner("선택한 출처를 조회합니다…"):
            state["search"] = router.search(query, providers=selected, limit=5)
        state["scholar"] = scholar_discovery(query)
    scholar = state.get("scholar", {})
    if scholar.get("ok"):
        st.link_button("Google Scholar에서 논문 버전 찾기", scholar["search_url"])
        st.caption("Scholar의 순위·인용 수는 발견 정보입니다. 아래에는 실제 원출처와 고정 버전을 연결합니다.")
    search = state.get("search", {})
    if search.get("error") and not search.get("results"):
        st.warning("검색 요청을 확인해 주세요 · " + str(search["error"]))
    for result in search.get("results", []):
        if not result.get("ok"):
            st.warning(str(result.get("provider")) + " · " + str(result.get("status") or result.get("error")))
        elif not result.get("items"):
            st.caption(str(result.get("provider")) + " · 조회 성공, 결과 없음")
    for index, item in enumerate(search.get("items", [])[:20]):
        with st.container():
            st.write(_public(item.get("title") or item.get("name") or item.get("id")))
            st.caption(str(item.get("provider")) + " · " + str(item.get("doi") or item.get("id") or "식별자 미확인"))
            link = _url(item.get("source_url") or item.get("official_url") or item.get("url"))
            if link:
                st.link_button("원출처 열기", link)
            doi = item.get("doi")
            if doi and st.button("이 논문 확인", key=f"ri_paper_{index}"):
                state["selected_paper_doi"] = doi
                state["publication"] = router.publication(doi)
            st.divider()


def _source(router, intake, state):
    st.subheader("원논문과 원자료 연결")
    with st.expander("원출처가 등록된 자료로 동선 확인"):
        st.caption("이 예제는 고정 저자 저장소의 실제 CSV를 다시 받고, 등록한 발행사 인용·자료 지문과 비교합니다. 조건은 사용자가 직접 확인해야 합니다.")
        if st.button("등록 원자료 받기", key="ri_registered_acquire"):
            with st.spinner("고정 저자 자료와 등록 지문을 대조합니다…"):
                downloaded = intake.acquisition_registered("PENG-RAW-ROWS")
            state["download"] = downloaded
            if downloaded.get("success"):
                state["paper_context"] = downloaded["paper_context"]
                state["source_location"] = downloaded["source_location"]
                state["record"] = None
                state["conditions_confirmed"] = False
                state.pop("report", None)
                st.session_state["ri_spec"] = json.dumps(downloaded["suggested_spec"], ensure_ascii=False, indent=2)
                move_step("ri_step", 2)
            st.warning("자료를 받지 못했습니다 · " + str(downloaded.get("error")))
    _discovery(router, state)
    doi = st.text_input("원논문 DOI", value=state.get("selected_paper_doi", ""), key="ri_paper_doi", on_change=_reset_result)
    if st.button("논문 버전·정정 관계 확인", key="ri_publication", disabled=not doi.strip()):
        with st.spinner("원출처와 정정 관계를 확인합니다…"):
            state["publication"] = router.publication(doi)
    if state.get("publication"):
        with st.expander("원논문 확인 결과", expanded=True):
            st.json(_public(state["publication"]))
    st.caption("정정 관계 미검출과 조회 실패를 구분합니다. 프리프린트·출판본은 다른 버전으로 기록합니다.")
    provider = st.selectbox("원자료 저장소", ["zenodo", "figshare", "dataverse"], key="ri_repository")
    identifier = st.text_input("고정 자료 DOI 또는 레코드 ID", key="ri_identifier", help="Figshare는 버전 DOI, Dataverse는 DOI@1.0처럼 고정 버전을 입력합니다.")
    if st.button("원자료 버전·이용 조건 확인", key="ri_record_load", disabled=not identifier.strip()):
        response = router.repository(provider, identifier)
        state["repository_response"] = response
        state.pop("download", None)
        st.session_state.pop("ri_spec", None)
        _reset_result()
        if response.get("ok") and response.get("items"):
            state["record"] = response["items"][0]
            state["record_provider"] = provider
        else:
            state.pop("record", None)
            st.warning("원자료 조회 실패 · " + str(response.get("error") or response.get("status")))
        st.session_state["ri_step"] = 1
    record = state.get("record")
    if record:
        st.write(_public(record.get("title")))
        st.json(_public({k: record.get(k) for k in ("id", "doi", "concept_doi", "version", "license", "access", "provenance")}))
        files = record.get("files", [])
        if files:
            selected_file = st.selectbox("받을 자료 파일", files, format_func=lambda item: str(item.get("name")), key="ri_file")
            st.caption("공급자 체크섬 · " + json.dumps(selected_file.get("checksum"), ensure_ascii=False))
            if st.button("허용된 CSV 자료 받기", key="ri_acquire"):
                with st.spinner("접근·라이선스·파일 크기를 검사하고 자료를 받습니다…"):
                    state["download"] = intake.acquisition(state["record_provider"], record, selected_file)
                    _reset_result()
                    st.session_state["ri_step"] = 1
    downloaded = state.get("download", {})
    if downloaded:
        if downloaded.get("success"):
            st.success("파일 수신 완료 · 검산과 사람 검토는 다음 단계입니다")
        else:
            st.warning("자료를 받지 못했습니다 · " + str(downloaded.get("error")))
        with st.expander("수신 바이트·파일 지문"):
            st.json(_public(downloaded.get("receipt", {})))
    with st.expander("원문 위치와 논문 버전", expanded=True):
        # [수정: 0 이영 · Codex] 2026-10-01 03:28 KST — 되돌아와도 확인된 등록 사본 지문을 보존하되 원문 수정은 기존 검토를 해제한다.
        prior_paper = state.get("paper_context", {})
        prior_location = state.get("source_location", {})
        for key, value in (("ri_source_url", prior_paper.get("source_url", "")),
                           ("ri_paper_version", prior_paper.get("paper_version", "")),
                           ("ri_locator", prior_location.get("locator", "")),
                           ("ri_quote", prior_location.get("quote", ""))):
            if key not in st.session_state:
                st.session_state[key] = value
        paper_url = st.text_input("원논문·저자 저장소 URL", key="ri_source_url", on_change=_reset_result)
        paper_version = st.text_input("확인한 논문 버전", key="ri_paper_version", placeholder="예: 출판본 또는 arXiv 식별자와 버전", on_change=_reset_result)
        locator = st.text_input("원문 근거 위치", key="ri_locator", placeholder="표·절·페이지·문단", on_change=_reset_result)
        quote = st.text_area("보고값과 조건이 있는 원문 인용", key="ri_quote", on_change=_reset_result)
    state["paper_context"] = {**prior_paper, "paper_doi": doi.strip() or prior_paper.get("paper_doi"), "source_url": paper_url, "paper_version": paper_version}
    state["source_location"] = {"source_id": doi.strip() or "USER-SOURCE", "locator": locator, "quote": quote}
    ready = downloaded.get("success") and _url(paper_url) and paper_version.strip() and locator.strip() and quote.strip() and not sensitive_kinds(quote + locator + paper_version)
    if st.button("조건 확인으로", key="ri_source_next", type="primary", disabled=not ready):
        move_step("ri_step", 2)


def _conditions(state):
    st.subheader("계산 대상과 여섯 조건 확인")
    downloaded = state.get("download", {})
    if not downloaded.get("success"):
        st.info("먼저 원자료 파일을 연결해 주세요.")
        return
    if "ri_spec" not in st.session_state:
        spec = empty_spec("USER-CLAIM")
        spec["data_fingerprint"] = hashlib.sha256(downloaded["raw_bytes"]).hexdigest()
        spec["source_location"] = state.get("source_location")
        st.session_state["ri_spec"] = json.dumps(spec, ensure_ascii=False, indent=2)
    st.caption("분모 · 포함·제외 조건 · 단위 · 결측 · 계산 방법 · 원문 위치. 모르는 항목은 추정하지 않습니다.")
    with st.expander("행 수·평균 조건 입력"):
        method = st.selectbox("계산 방법", ["row_count", "mean"], format_func=lambda v: "전체 행 수" if v == "row_count" else "선택 열 평균", key="ri_method")
        variable = st.text_input("평균을 계산할 열", key="ri_variable", disabled=method == "row_count")
        reported = st.number_input("원문 보고값", value=None, key="ri_reported", help="원문에 없는 값은 채우지 않습니다.")
        denominator = st.text_input("분모·계산 대상의 기준", key="ri_denominator")
        unit = st.text_input("원문의 단위", key="ri_unit")
        missing = st.selectbox("결측 처리", ["error", "complete_case", "not_applicable"], key="ri_missing")
        filter_column = st.text_input("포함 조건 열 · 없으면 비움", key="ri_filter_column")
        filter_value = st.text_input("포함할 값", key="ri_filter_value")
        tolerance = st.number_input("원문 반올림 허용 오차", min_value=0.0, value=0.0, key="ri_tolerance")
        if st.button("입력한 조건을 명세에 담기", key="ri_build_spec", disabled=reported is None or not denominator.strip() or not unit.strip() or method == "mean" and not variable.strip()):
            spec = empty_spec("USER-CLAIM")
            spec.update(method=method, variable=variable.strip() if method == "mean" else None, reported_value=reported,
                        filters=[{"column": filter_column.strip(), "operator": "eq", "value": filter_value}] if filter_column.strip() else [],
                        missing_policy=missing, missing_tokens=["NA", ""], denominator=denominator, unit=unit,
                        data_fingerprint=hashlib.sha256(downloaded["raw_bytes"]).hexdigest(), tolerance=tolerance,
                        source_location=state["source_location"])
            st.session_state["ri_spec"] = json.dumps(spec, ensure_ascii=False, indent=2)
            _reset_result()
            st.rerun()
    with st.expander("받은 파일과 원문 근거"):
        st.json(_public(downloaded.get("receipt", {})))
        st.json(_public(state.get("source_location", {})))
    text = st.text_area("분석 명세 JSON", key="ri_spec", height=360, on_change=_reset_result)
    state["spec_text"] = text
    try:
        from core.research_corpus import strict_json
        state["spec"] = strict_json(text.encode("utf-8"))
        from evidence_gate.spec import validate
        checked = validate(state["spec"])
        if not checked["ready"]:
            st.info("보완할 조건 · " + json.dumps(_public(checked), ensure_ascii=False))
    except (ValueError, TypeError):
        state.pop("spec", None)
        checked = {"ready": False}
        st.error("명세의 JSON 형식을 확인해 주세요.")
    state["conditions_confirmed"] = st.checkbox("여섯 조건을 원문과 직접 대조했습니다", key="ri_conditions_confirmed")
    if st.button("지원 계산으로", key="ri_conditions_next", type="primary", disabled=not checked["ready"] or not state["conditions_confirmed"]):
        move_step("ri_step", 3)


def _calculate(intake, state):
    st.subheader("받은 바이트로 다시 계산")
    # [수정: 0 이영 · Codex] 2026-10-01 03:16 KST — 원문 실제 취득과 선언된 위치의 차이를 계산 전에 드러낸다.
    if state.get("download", {}).get("receipt", {}).get("provider") == "registered":
        st.caption("원문은 연락처를 제거한 등록 공개 사본입니다. 발행사 원응답 바이트의 지문은 미확보입니다.")
    else:
        st.info("원논문 바이트는 아직 확보하지 않았습니다. 아래 결과는 받은 자료와 직접 확인한 계산 조건의 범위입니다.")
    if st.button("결정적 재계산", key="ri_compute", type="primary", disabled=not state.get("spec")):
        data = state.get("download", {})
        with st.spinner("파일·조건·원문 지문을 대조하고 계산합니다…"):
            state["report"] = intake.verify_download(data.get("raw_bytes"), data.get("receipt"), state["spec"], paper_context=state["paper_context"], conditions_confirmed=state.get("conditions_confirmed", False), current_record=state.get("record"))
    report = state.get("report")
    if report:
        st.write("계산 상태 · " + str(report.get("state") or report.get("action")))
        calculation = report.get("calculation")
        if calculation:
            st.write(_public(calculation))
        with st.expander("조건·계산·입력 지문 상세"):
            st.json(_public(report))
        if st.button("검토 기록으로", key="ri_result_next", disabled=not report.get("can_approve", report.get("success", False))):
            move_step("ri_step", 4)


def _review(intake, state):
    st.subheader("사람의 검토 기록")
    report = state.get("report")
    if not report:
        st.info("계산한 결과가 없습니다. 조건을 확인하고 재계산해 주세요.")
        return
    st.write("검토 상태 · " + str(report.get("state")))
    if report.get("action") == "BLOCK":
        st.error("현재 입력으로 검토를 저장할 수 없습니다 · " + str(report.get("error") or "입력·조건을 다시 확인해 주세요"))
        return
    with st.expander("검토할 계산과 근거"):
        st.json(_public(report))
    st.caption("자료 수신이나 수치 일치만으로 논문 전체를 승인하지 않습니다. 불러온 기록은 읽기 전용입니다.")
    actor = st.session_state.get("authenticated_member")
    role = member_role(actor) if actor in MEMBERS else "VIEWER"
    confirmed = st.checkbox("원문·원자료·계산 조건을 직접 확인했습니다", key="ri_confirm")
    reason = st.text_area("확인 근거와 남은 한계", key="ri_reason")
    if st.button("사람 검토 기록 저장", key="ri_approve", disabled=role not in {"ADMIN", "APPROVER"} or not confirmed or not reason.strip()):
        if actor not in MEMBERS or member_role(actor) not in {"ADMIN", "APPROVER"}:
            st.error("팀 로그인과 승인 역할을 확인해 주세요.")
            return
        data = state["download"]
        state["report"] = intake.approve_download(report, raw_bytes=data["raw_bytes"], receipt=data["receipt"], spec=state["spec"], paper_context=state["paper_context"], actor=actor, actor_role=role, confirmed=confirmed, reason=reason, current_record=state.get("record"))
        st.rerun()
    try:
        payload = intake.export_report(state["report"])
    except (ValueError, TypeError):
        st.error("보고서 지문을 확인하지 못했습니다. 근거와 조건을 다시 확인해 재계산해 주세요.")
        return
    st.download_button("검토 기록 JSON 내려받기", payload, file_name="0_이영_원자료_검토기록.json", mime="application/json", key="ri_export")
    if actor in MEMBERS and st.button("팀 작업실에도 기록", key="ri_team_save"):
        from core.team_workspace import Workspace, settings
        try:
            config = settings()
            store = Workspace(repo=config.get("repo", ""), token=config.get("token", ""), branch=config.get("branch", "team-data"))
            saved_id = store.save(actor, "원자료 검산 · " + str(state["spec"].get("claim_id", ""))[:80],
                                  "검토 요청", note="원자료 수신·결정적 계산의 범위만 기록합니다. 논문 전체 재현과 최종 연구 판단은 별도입니다.",
                                  files=[("0_이영_원자료_검토기록.json", payload.encode("utf-8"))])
            st.success("팀 검토 기록을 저장했습니다 · " + saved_id)
            if not store.remote:
                st.caption("현재 배포 서버의 저장소입니다. 재배포 전에 JSON을 내려받아 보관해 주세요.")
        except (ValueError, RuntimeError):
            st.error("공용 저장을 확인하지 못했습니다. JSON 초안을 내려받아 보존하고 팀 작업실 설정을 확인해 주세요.")
    with st.expander("외부 공유용 계산 요약"):
        result = state["report"]
        st.json(_public({k: result.get(k) for k in ("state", "action", "calculation", "bindings", "approved", "limitations")}))
        st.caption("요약은 계산 결과와 한계를 그대로 옮깁니다. 원문 보고값·조건을 자동 수정하지 않습니다.")


def render():
    theme = importlib.import_module("core.0_이영_웹테마")
    theme.render_theme()
    theme.render_brand()
    from core import research_integration_router as router, research_integration_intake as intake
    from core.research_integration_feeds import get_integration_feed, list_feed_providers
    st.title("원논문에서 검토 기록까지")
    st.caption("출처를 찾고, 허용된 자료를 받은 뒤 실제 바이트와 조건으로 계산합니다.")
    state = st.session_state.setdefault("ri_state", {})
    with st.expander("저장한 검토 기록 불러오기"):
        saved = st.text_area("검토 기록 JSON", key="ri_import_text")
        if st.button("기록 다시 열기", key="ri_import", disabled=not saved.strip()):
            try:
                reopened = intake.reopen_report(saved)
                if reopened.get("action") == "BLOCK":
                    st.error("기록을 확인하지 못했습니다 · " + str(reopened.get("error")))
                else:
                    state["reopened"] = reopened
            except (ValueError, TypeError):
                st.error("기록의 형식·지문을 확인하지 못했습니다. 내려받은 파일을 그대로 사용해 주세요.")
        if state.get("reopened"):
            st.json(_public(state["reopened"]))
            st.caption("다시 연 기록은 새로운 검산이나 현재 승인으로 처리하지 않습니다.")
    step = st.session_state.setdefault("ri_step", 1)
    render_steps(step)
    if step > 1 and st.button("근거 연결로 돌아가기", key="ri_back"):
        move_step("ri_step", 1)
    if step == 1:
        _source(router, intake, state)
    elif step == 2:
        _conditions(state)
    elif step == 3:
        _calculate(intake, state)
    else:
        _review(intake, state)
    with st.expander("새 연구 피드"):
        providers = list_feed_providers()
        feed = st.selectbox("피드 출처", [p["provider"] for p in providers], key="ri_feed_source")
        if st.button("지금 피드 확인", key="ri_feed_load"):
            state["feed"] = get_integration_feed(feed, refresh=True)
        if state.get("feed"):
            result = state["feed"]
            st.caption("마지막 성공 · " + str(result.get("last_success_at") or "미확인") + " · " + str(result.get("status")))
            if result.get("stale") or not result.get("ok"):
                st.warning("현재 조회 실패 · " + str(result.get("error")) + (" · 아래는 이전 성공 자료입니다" if result.get("items") else ""))
            for item in result.get("items", [])[:8]:
                st.write(_public(item.get("title")))
                st.caption("발행 · " + str(item.get("published") or "시각 미확정") + " · 버전 " + str(item.get("version") or "미확정"))
                link = _url(item.get("link") or item.get("source_url"))
                if link:
                    st.link_button("피드 원문 열기", link)
            with st.expander("피드 관측·출처 상세"):
                st.json(_public(result))
        st.caption("요청할 때 수집합니다. 실패하면 마지막 성공 자료에 오래된 자료 표시를 유지합니다.")
    with st.expander("연결 상태와 검토 범위"):
        st.json(_public(router.status_catalog()))
        st.caption("코드·설정·실제 호출·배포 확인은 별도 상태입니다. Cloud는 PC의 로컬 MCP에 연결되었다고 가정하지 않습니다.")

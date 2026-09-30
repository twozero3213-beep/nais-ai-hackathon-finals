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
    # [수정: 0 이영] 2026-10-01 04:22 KST — 내부 원문 바이트는 화면·JSON·모델에 전파하지 않는다.
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "[바이트 본문 제외]"
    if isinstance(value, str):
        return "[비공개 형태 제외]" if sensitive_kinds(value) else value
    if isinstance(value, dict):
        return {k: _public(v) for k, v in value.items() if str(k).lower() not in {"raw_bytes", "source_bytes", "api_key", "token", "authorization", "password"}}
    if isinstance(value, list):
        return [_public(v) for v in value]
    return value


def _reset_result(clear_widgets=True):
    state = st.session_state.setdefault("ri_state", {})
    for name in ("report", "approval", "candidate_previews", "source_agreement", "proposal", "blind_review"):
        state.pop(name, None)
    st.session_state["ri_step"] = min(st.session_state.get("ri_step", 1), 2)
    state["conditions_confirmed"] = False
    if clear_widgets:
        st.session_state["ri_conditions_confirmed"] = False
        st.session_state["ri_confirm"] = False
        st.session_state["ri_reason"] = ""
    else:
        st.session_state["_ri_pending_reset"] = True


def _relations(state, doi):
    """Only explicit requests fetch relations and licensed original XML."""
    from core.research_integration_relations import datacite_relations, jats_data_availability
    with st.expander("논문과 자료의 관계·원문 자료 공개 절"):
        st.caption("인용 관계는 원자료 사용 증거가 아닙니다. 방향·버전·라이선스를 따로 확인합니다.")
        if st.button("DataCite 자료 관계 찾기", key="ri_datacite", disabled=not doi.strip()):
            state["relations"] = datacite_relations(doi.strip())
        if st.button("허용된 JATS 원문과 자료 공개 절 받기", key="ri_jats", disabled=not doi.strip()):
            state["jats"] = jats_data_availability(doi.strip(), include_source_bytes=True)
            state.pop("_jats_context_cache", None)
            _reset_result()
            st.session_state["ri_step"] = 1
        for name in ("relations", "jats"):
            if state.get(name):
                result = state[name]
                st.write("조회 상태 · " + str(result.get("status")))
                st.json(_public(result))
        received = state.get("jats", {})
        items = received.get("items", [])
        if isinstance(received.get("source_bytes"), bytes):
            from core.research_integration_source_spans import jats_contexts
            try:
                # [수정: 0 이영] 2026-10-01 05:00 KST — 동일한 불변 bytes 객체의 문단 파싱만 재사용하고 새 수신본은 실제 SHA 확인 후 다시 파싱한다.
                raw = received["source_bytes"]
                cached = state.get("_jats_context_cache", {})
                if cached.get("raw_bytes") is raw and cached.get("sha256") == received.get("response_sha256"):
                    contexts = cached["contexts"]
                else:
                    actual_sha = hashlib.sha256(raw).hexdigest()
                    if actual_sha != received.get("response_sha256"):
                        raise ValueError("SOURCE_BYTES_CHANGED")
                    contexts = jats_contexts(raw)
                    state["_jats_context_cache"] = {"raw_bytes": raw, "sha256": actual_sha, "contexts": contexts}
                items = [{"location": {"xpath": item["locator"]}, "text": item["text"]} for item in contexts] or items
            except ValueError:
                items = []
        if isinstance(received.get("source_bytes"), bytes) and items:
            selected = st.selectbox("연결할 원문 근거 문단", items,
                                    format_func=lambda item: item.get("location", {}).get("xpath", "위치 미확인"), key="ri_jats_item")
            if st.button("받은 원문 문단 연결", key="ri_jats_bind"):
                from core.research_integration_source_spans import jats_spans
                from core.research_integration_candidates import source_receipt_for_spans
                locator = selected["location"]["xpath"]
                raw = received["source_bytes"]
                info = received["public_source_receipt"]
                version = "JATS " + info["pmcid"] + " @ " + info["sha256"]
                try:
                    receipt = source_receipt_for_spans(raw, source_url=info["url"], paper_version=version,
                                spans=jats_spans(raw, [locator]), source_kind="LICENSED_JATS_RECEIVED")
                except ValueError:
                    st.error("받은 원문의 실제 문단 위치를 확인하지 못했습니다. 조건 근거로 연결하지 않았습니다.")
                else:
                    _reset_result()
                    st.session_state["ri_step"] = 1
                    previous_receipt = state.get("source_receipt", {})
                    if previous_receipt.get("actual_sha256") == receipt["actual_sha256"] and previous_receipt.get("paper_version") == version:
                        receipt["locations"] = {**previous_receipt.get("locations", {}), **receipt["locations"]}
                    state["source_bytes"], state["source_receipt"] = raw, receipt
                    state["paper_context"] = {"paper_doi": info["doi"], "paper_version": version,
                                              "source_url": info["url"], "source_sha256": info["sha256"],
                                              "source_kind": "LICENSED_JATS_RECEIVED"}
                    state["source_location"] = {"source_id": info["doi"], "locator": locator, "quote": selected["text"]}
                    for key in ("ri_source_url", "ri_paper_version", "ri_locator", "ri_quote"):
                        st.session_state.pop(key, None)
                    st.rerun()
        st.caption("원문 수신·위치 결속과 계산 조건의 의미 판단은 별도입니다. 공개 절만으로 분모·결측 처리까지 채우지 않습니다.")


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
            _reset_result()
            state.pop("download", None)
            with st.spinner("고정 저자 자료와 등록 지문을 대조합니다…"):
                downloaded = intake.acquisition_registered("PENG-RAW-ROWS")
            state["download"] = downloaded
            if downloaded.get("success"):
                state["paper_context"] = downloaded["paper_context"]
                state["source_location"] = downloaded["source_location"]
                state["record"] = None
                state.pop("source_bytes", None)
                state.pop("source_receipt", None)
                state.pop("candidate_set", None)
                state.pop("candidate_inputs", None)
                for key in ("ri_source_url", "ri_paper_version", "ri_locator", "ri_quote", "ri_contract"):
                    st.session_state.pop(key, None)
                state["conditions_confirmed"] = False
                state.pop("report", None)
                st.session_state["ri_spec"] = json.dumps(downloaded["suggested_spec"], ensure_ascii=False, indent=2)
                move_step("ri_step", 2)
            else:
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
    _relations(state, doi)
    provider = st.selectbox("원자료 저장소", ["zenodo", "figshare", "dataverse"], key="ri_repository")
    identifier = st.text_input("고정 자료 DOI 또는 레코드 ID", key="ri_identifier", help="Figshare는 버전 DOI, Dataverse는 DOI@1.0처럼 고정 버전을 입력합니다.")
    state["pending_repository"] = {"provider": provider, "identifier": identifier.strip()}
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
            state["selected_file"] = selected_file
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
    source_id = prior_location.get("source_id") if not doi.strip() or doi.strip() == prior_paper.get("paper_doi") else doi.strip()
    state["source_location"] = {"source_id": source_id or doi.strip() or "USER-SOURCE", "locator": locator, "quote": quote}
    ready = downloaded.get("success") and _url(paper_url) and paper_version.strip() and locator.strip() and quote.strip() and not sensitive_kinds(quote + locator + paper_version)
    if st.button("조건 확인으로", key="ri_source_next", type="primary", disabled=not ready):
        move_step("ri_step", 2)


def _proposal(state):
    from core.research_integration_proposals import propose_conditions, ALLOWED_TOOLS, _digest
    from finals import finals_provider
    with st.expander("AI로 누락 조건과 다음 확인 대상 제안"):
        st.caption("선택한 인용과 공개 메타데이터만 보냅니다. 받은 CSV 행·원문 전체·과거 계산 결과는 보내지 않습니다.")
        ready = finals_provider.paid_call_allowed(st.session_state) and finals_provider.availability()["available"] and finals_provider.live_allowed()
        if not ready:
            st.info("팀 로그인·모델 연결·실호출 설정을 확인해야 AI 제안을 요청할 수 있습니다.")
        opted = st.checkbox("인용과 메타데이터를 모델에 보내 조건 후보를 받겠습니다", key="ri_ai_opted")
        if st.button("AI 조건 후보 받기", key="ri_ai_propose", disabled=not ready or not opted):
            location = state.get("source_location", {})
            context = {**state.get("paper_context", {}), "source_id": location.get("source_id"), "source_location": location}
            received = state.get("download", {}).get("receipt", {})
            metadata = {k: received.get(k) for k in ("provider", "actual_sha256", "actual_size", "license_policy")}
            snapshot_sha = _digest({"excerpt": location.get("quote", ""), "paper_context": context,
                                    "dataset_metadata": metadata, "allowed_tools": list(ALLOWED_TOOLS)})
            attempts = st.session_state.setdefault("ri_proposal_attempts", {})
            # [수정: 0 이영] 2026-10-01 05:24 KST — 입력별 1회 예약은 전역 유료 한도와 분리하고 실패에도 재시도하지 않아 리런 중 중복 비용을 막는다.
            if snapshot_sha in attempts:
                st.info("같은 인용·자료 입력의 제안은 이미 요청했습니다. 새 근거를 연결한 뒤 다시 요청해 주세요.")
            elif len(attempts) >= 128:
                st.warning("이 세션의 제안 기록이 가득 찼습니다. 기존 결과를 먼저 검토해 주세요.")
            else:
                attempts[snapshot_sha] = {"attempt_started": True}
                state["proposal"] = propose_conditions(location.get("quote", ""), context, metadata,
                                                        opted_in=opted, session=st.session_state)
                attempts[snapshot_sha] = {"attempt_started": True, "usage": state["proposal"].get("usage")}
        result = state.get("proposal")
        if result:
            st.json(_public(result))
            st.caption("빈 조건은 빈 상태로 남습니다. 다음 도구는 아래에서 직접 요청할 때 한 번만 실행합니다.")
            # [수정: 0 이영] 2026-10-01 05:23 KST — 제안 입력과 선택 파일을 실행 직전에 재대조하며 내부 바이트 patch를 표시하지 않는다.
            action_opted = st.checkbox("현재 선택한 자료에 제안된 다음 확인을 한 번 실행하겠습니다", key="ri_action_opted")
            if st.button("제안된 다음 확인 실행", key="ri_action_execute", disabled=not result.get("success") or not action_opted):
                from core.research_integration_actions import execute_next_tool
                # [수정: 0 이영] 2026-10-01 05:32 KST — 같은 클릭의 현재 위젯값을 읽어 앞선 리런의 확인·명세를 도구에 넘기지 않는다.
                from core.research_corpus import strict_json
                state["conditions_confirmed"] = st.session_state.get("ri_conditions_confirmed") is True
                try:
                    state["spec"] = strict_json(st.session_state.get("ri_spec", "").encode("utf-8"))
                except (ValueError, TypeError):
                    state.pop("spec", None)
                outcome = execute_next_tool(result, state, opted_in=action_opted)
                state.update(outcome.get("state_patch", {}))
                state["action_observation"] = {k: outcome.get(k) for k in ("success", "status", "error", "next_action", "receipt")}
                if outcome.get("success") and outcome.get("tool_executed"):
                    acquisition_action = outcome["receipt"].get("tool") in ("repository_record", "acquisition")
                    if acquisition_action:
                        st.session_state["_ri_pending_reset"] = True
                        st.session_state.pop("ri_spec", None)
                        for name in ("candidate_inputs", "selected_candidate"):
                            state.pop(name, None)
                        for name in ("ri_contract", "ri_candidate_choice"):
                            st.session_state.pop(name, None)
                    st.session_state["ri_step"] = 1 if acquisition_action else 3
                    st.rerun()
            if result.get("success") and st.button("미확인 조건 후보로 가져오기", key="ri_ai_adopt"):
                st.session_state["ri_spec"] = json.dumps(result["suggested_spec"], ensure_ascii=False, indent=2)
                _reset_result()
                st.rerun()


def _candidate_kwargs(state):
    return {"source_bytes": state.get("source_bytes"), "source_receipt": state.get("source_receipt"),
            "paper_context": state.get("paper_context", {}),
            "data_sha256": hashlib.sha256(state["download"]["raw_bytes"]).hexdigest()}


def _agreement(state):
    from core.research_integration_candidates import compare_source_conditions
    pool = state.get("candidate_set", {})
    selected = state.get("selected_candidate")
    current = next((c for c in pool.get("candidates", []) if c["candidate_id"] == selected), None)
    if current is None:
        return {"agreement": "UNRESOLVED", "can_preview": False, "semantic_ready": False, "error": "SOURCE_CONDITIONS_NOT_FROZEN"}
    return compare_source_conditions(current, state.get("spec", {}), candidate_set=pool, **_candidate_kwargs(state))


def _blind_review(state, pool, choice):
    """Explicit source re-extraction without previous candidate or result text."""
    from finals import finals_provider
    with st.expander("앞선 해석을 가린 원문 재검토"):
        st.caption("받은 원문의 중립 문단을 직접 선택합니다. 앞선 후보값·후보 인용 묶음·계산·승인은 모델 입력에서 제외합니다.")
        locations = list(state.get("source_receipt", {}).get("locations", {}))
        selected = st.multiselect("재검토할 실제 원문 위치 · 최대 3개", locations, key="ri_blind_locations", max_selections=3)
        row_dictionary = st.text_input("공개 자료 사전의 한 행 의미 · 모르면 비움", key="ri_row_dictionary")
        opted = st.checkbox("선택한 원문 문단과 열 이름으로 가림 재추출을 한 번 요청하겠습니다", key="ri_blind_opted")
        ready = isinstance(state.get("source_bytes"), bytes) and bool(selected) and finals_provider.paid_call_allowed(st.session_state) and finals_provider.availability()["available"] and finals_provider.live_allowed()
        if st.button("원문에서 독립 조건 재추출", key="ri_blind_request", disabled=not ready or not opted):
            # [수정: 0 이영] 2026-10-01 05:23 KST — 열 이름만 명시 요청 시 읽고 실제 서버 세션에 시도를 예약해 같은 후보의 반복 호출을 막는다.
            import csv
            import io
            from core.research_integration_blind_review import blind_review_conditions
            try:
                with io.TextIOWrapper(io.BytesIO(state["download"]["raw_bytes"]), encoding="utf-8-sig", newline="") as stream:
                    columns = next(csv.reader(stream))
                metadata = {"columns": columns, "public_dictionary": {},
                            "actual_sha256": hashlib.sha256(state["download"]["raw_bytes"]).hexdigest()}
                if row_dictionary.strip():
                    metadata["row_dictionary"] = row_dictionary.strip()
                candidate = next(c for c in pool["candidates"] if c["candidate_id"] == choice)
                state["blind_review"] = blind_review_conditions(candidate, pool,
                    source_bytes=state["source_bytes"], source_receipt=state["source_receipt"],
                    paper_context=state["paper_context"], dataset_metadata=metadata, review_locations=selected,
                    opted_in=opted, session=st.session_state, prior_proposal_receipt=state.get("proposal"),
                    previous_review=state.get("blind_review"))
            except (ValueError, UnicodeError, StopIteration, csv.Error):
                st.error("공개 열 이름과 원문 위치를 확인하지 못했습니다. 모델 요청을 시작하지 않았습니다.")
        review = state.get("blind_review")
        if review:
            st.json(_public(review))
            st.caption("모델의 동의는 과학적 의미의 확정이나 사람 승인이 아닙니다. 다른 분석·문맥 누락·자료 연결을 직접 검토해야 합니다.")


def _candidate_conditions(state):
    from core.research_integration_candidates import FIELDS, freeze_candidates
    from core.research_corpus import strict_json
    with st.expander("원문 조건을 먼저 고정하고 다른 해석 비교"):
        st.caption("원문 조건과 계산 명세를 별도로 적습니다. 사실 후보·가정·누락을 구분하고, 결과를 보기 전에 최대 3개 해석을 고정합니다.")
        st.caption("문자·위치·지문 대조는 의미의 자동 인증이 아닙니다. 조건의 근거가 없는 숫자는 산술 미리보기로만 남습니다.")
        if "ri_contract" not in st.session_state:
            draft = {"contract_version": 1, "paper_version": state["paper_context"]["paper_version"],
                     "source_location": state.get("source_location"),
                     "fields": {name: {"status": "missing", "value": None, "evidence": None} for name in FIELDS}}
            st.session_state["ri_contract"] = json.dumps(draft, ensure_ascii=False, indent=2)
        contract = st.text_area("원문 여섯 조건의 근거 · 고급 JSON", key="ri_contract", height=320, on_change=_reset_result)
        st.caption("각 조건은 status(fact/hypothesis/missing), value, evidence(locator/quote)를 가집니다. 누락을 명세 값으로 자동 채우지 않습니다.")
        st.info("여기서는 원문 위치와 선언 조건을 대조합니다. 목표 표·분석군의 동일성, 필수 문맥, 논문과 자료의 관계, 한 행의 의미는 아직 자동 검증하지 않습니다.")
        if st.button("현재 해석 추가·계산 전 고정", key="ri_candidate_freeze", disabled=not state.get("spec") or len(state.get("candidate_inputs", [])) >= 3):
            try:
                source_contract = strict_json(contract.encode("utf-8"))
                items = list(state.get("candidate_inputs", []))
                items.append({"candidate_id": "candidate-" + str(len(items) + 1),
                              "source_condition_contract": source_contract, "candidate_spec": state["spec"]})
                history = state.get("candidate_history", [])
                previous = state.get("candidate_set") or (history[-1] if history else None)
                pool = freeze_candidates(items, previous_set=previous, **_candidate_kwargs(state))
                if pool.get("success"):
                    _reset_result(clear_widgets=False)
                    state["candidate_inputs"], state["candidate_set"] = items, pool
                    state["selected_candidate"] = items[-1]["candidate_id"]
                    st.rerun()
                else:
                    st.warning("조건 후보를 고정하지 못했습니다 · " + str(pool.get("error")))
            except (ValueError, TypeError):
                st.error("원문 조건 JSON의 형식과 실제 위치를 확인해 주세요.")
        pool = state.get("candidate_set")
        if pool:
            st.caption("고정한 후보 · " + str(len(pool.get("candidates", []))) + " · " + pool["candidate_set_sha256"])
            options = [c["candidate_id"] for c in pool.get("candidates", [])]
            choice = st.selectbox("직접 확인할 해석", options, key="ri_candidate_choice", on_change=_reset_result)
            state["selected_candidate"] = choice
            if st.button("선택 해석을 현재 명세로", key="ri_candidate_use"):
                row = next(c for c in pool["candidates"] if c["candidate_id"] == choice)
                st.session_state["_ri_next_spec"] = json.dumps(row["candidate_spec"], ensure_ascii=False, indent=2)
                _reset_result(clear_widgets=False)
                st.rerun()
            if st.button("현재 원문 조건·지문 대조", key="ri_candidate_check"):
                state["source_agreement"] = _agreement(state)
            if state.get("source_agreement"):
                st.caption("마지막 명시 대조의 관측 결과입니다. 재계산·검토 저장 전에 현재 입력을 다시 검사합니다.")
                st.json(_public(state["source_agreement"]))
            st.caption("각 해석의 계산 결과를 함께 표시합니다. 보고값에 가장 가까운 해석을 자동 선택하지 않습니다.")
            _blind_review(state, pool, choice)
            if st.button("근거를 보완해 새 후보 묶음 시작", key="ri_candidate_restart"):
                state["previous_candidate_set_sha256"] = pool["candidate_set_sha256"]
                state.setdefault("candidate_history", []).append(pool)
                state.pop("candidate_inputs", None)
                state.pop("candidate_set", None)
                _reset_result(clear_widgets=False)
                st.rerun()


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
    _proposal(state)
    with st.expander("행 수·평균 조건 입력", expanded=downloaded.get("receipt", {}).get("provider") != "registered"):
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
    with st.expander("고급 계산 명세"):
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
    spec = state.get("spec", {})
    st.write("계산 방법 · " + str(spec.get("method") or "미확정") + " · 원문 보고값 · " + str(spec.get("reported_value") if spec.get("reported_value") is not None else "미확정"))
    st.dataframe([{"확인할 조건": label, "현재 명세": str(_public(spec.get(key))) if spec.get(key) is not None else "미확정"}
                  for label, key in (("분모·대상", "denominator"), ("포함·제외", "filters"), ("단위", "unit"),
                                     ("결측 처리", "missing_policy"), ("계산 열", "variable"), ("원문 위치", "source_location"))],
                 hide_index=True, width="stretch")
    state["conditions_confirmed"] = st.checkbox("여섯 조건을 원문과 직접 대조했습니다", key="ri_conditions_confirmed")
    _candidate_conditions(state)
    if st.button("지원 계산으로", key="ri_conditions_next", type="primary", disabled=not checked["ready"] or not state["conditions_confirmed"]):
        move_step("ri_step", 3)


def _calculate(intake, state):
    st.subheader("받은 바이트로 다시 계산")
    # [수정: 0 이영 · Codex] 2026-10-01 03:16 KST — 원문 실제 취득과 선언된 위치의 차이를 계산 전에 드러낸다.
    if state.get("download", {}).get("receipt", {}).get("provider") == "registered":
        st.caption("원문은 연락처를 제거한 등록 공개 사본입니다. 발행사 원응답 바이트의 지문은 미확보입니다.")
    elif isinstance(state.get("source_bytes"), bytes):
        st.caption("허용된 JATS 원문 바이트와 문단 위치를 받았습니다. 원문 조건의 해석·논문 전체 재현은 별도 검토 대상입니다.")
    else:
        st.info("원논문 바이트는 아직 확보하지 않았습니다. 아래 결과는 받은 자료와 직접 확인한 계산 조건의 범위입니다.")
    if st.button("결정적 재계산", key="ri_compute", type="primary", disabled=not state.get("spec")):
        data = state.get("download", {})
        pool = state.get("candidate_set")
        if pool:
            from core.research_integration_candidates import preview_candidate
            state["source_agreement"] = _agreement(state)
            state["candidate_previews"] = [preview_candidate(c, data["raw_bytes"],
                source_bytes=state.get("source_bytes"), source_receipt=state.get("source_receipt"),
                paper_context=state["paper_context"], candidate_set=pool) for c in pool["candidates"]]
        if pool and state["source_agreement"].get("agreement") != "EXACT":
            state.pop("report", None)
            st.warning("원문 조건이 미확정·불일치·변경 상태입니다. 후보 미리보기와 차이를 확인하고 원문에서 해소해 주세요.")
        else:
            with st.spinner("파일·조건·원문 지문을 대조하고 계산합니다…"):
                state["report"] = intake.verify_download(data.get("raw_bytes"), data.get("receipt"), state["spec"], paper_context=state["paper_context"], conditions_confirmed=state.get("conditions_confirmed", False), current_record=state.get("record"))
    if state.get("candidate_previews"):
        for i, preview in enumerate(state["candidate_previews"], 1):
            st.write("조건 후보 " + str(i) + " · " + str(preview.get("agreement")))
            st.json(_public(preview))
        st.caption("후보 수치와 숫자 거리로 원문 해석을 확정하지 않습니다. 후보 미리보기는 승인 가능한 결과가 아닙니다.")
    report = state.get("report")
    if report:
        st.write("계산 상태 · " + str(report.get("state") or report.get("action")))
        calculation = report.get("calculation")
        if calculation:
            st.write(_public(calculation))
        with st.expander("조건·계산·입력 지문 상세"):
            st.json(_public(report))
        st.caption("수치 대조는 선언한 조건의 산술 범위입니다. 수치 일치가 원문 의미의 자동 입증은 아닙니다.")
        # [수정: 0 이영] 2026-10-01 05:11 KST — 표시 리런은 마지막 관측만 보여 주고 단계 이동·계산·승인 직전 fresh 검사는 유지한다.
        agreement = state.get("source_agreement") if state.get("candidate_set") else None
        semantic_block = agreement is not None and agreement.get("agreement") != "EXACT"
        if st.button("검토 기록으로", key="ri_result_next", disabled=semantic_block or not report.get("can_approve", report.get("success", False))):
            if state.get("candidate_set") and _agreement(state).get("agreement") != "EXACT":
                state.pop("report", None)
                st.error("현재 원문 조건·지문이 달라져 검토로 이동하지 않았습니다.")
            else:
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
        if state.get("candidate_set") and _agreement(state).get("agreement") != "EXACT":
            state.pop("report", None)
            st.error("원문 조건·후보·입력 지문이 달라졌습니다. 이전 결과로 검토를 저장하지 않았습니다.")
            return
        state["report"] = intake.approve_download(report, raw_bytes=data["raw_bytes"], receipt=data["receipt"], spec=state["spec"], paper_context=state["paper_context"], actor=actor, actor_role=role, confirmed=confirmed, reason=reason, current_record=state.get("record"))
        st.rerun()
    try:
        payload = intake.export_report(state["report"])
    except (ValueError, TypeError):
        st.error("보고서 지문을 확인하지 못했습니다. 근거와 조건을 다시 확인해 재계산해 주세요.")
        return
    st.download_button("검토 기록 JSON 내려받기", payload, file_name="0_이영_원자료_검토기록.json", mime="application/json", key="ri_export")
    if state.get("candidate_set"):
        extra = {"candidate_set": state["candidate_set"], "source_agreement": state.get("source_agreement"),
                 "source_receipt": state.get("source_receipt"), "semantic_ready": False}
        st.download_button("원문 조건・후보 지문 내려받기", json.dumps(_public(extra), ensure_ascii=False, indent=2),
                           file_name="0_이영_원문조건_후보.json", mime="application/json", key="ri_candidates_export")
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
    # [수정: 0 이영] 2026-10-01 04:22 KST — 생성된 위젯을 같은 실행 중 덮어쓰지 않고 다음 렌더 시작에 확인 상태를 해제한다.
    if st.session_state.pop("_ri_pending_reset", False):
        _reset_result()
    pending_spec = st.session_state.pop("_ri_next_spec", None)
    if pending_spec is not None:
        st.session_state["ri_spec"] = pending_spec
    with st.expander("저장한 검토 기록 불러오기"):
        saved = st.text_area("검토 기록 JSON", key="ri_import_text")
        if st.button("기록 다시 열기", key="ri_import", disabled=not saved.strip()):
            state.pop("reopened", None)
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
    if state.get("action_observation"):
        with st.expander("마지막 명시 도구 실행 관측"):
            st.json(_public(state["action_observation"]))
    from core.research_integration_trace_ui import render_trace
    actor = st.session_state.get("authenticated_member")
    if actor in MEMBERS:
        render_trace(state, actor)
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

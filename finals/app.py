"""[0 이영] 2026-09-30 KST: 원문·검산·직접 승인·재열기를 하나의 본선 동선으로 연결한다."""
from __future__ import annotations

import html
import json
import logging
import os
from pathlib import Path
import re
import sys

import pandas as pd
import streamlit as st

AGENT_ROOT = Path(__file__).resolve().parent
# 수정 이유: Desktop 통합 저장소의 core/data와 본선 전용 모듈을 함께 사용한다.
for module_root in (AGENT_ROOT.parent, AGENT_ROOT):
    if str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))

from finals_explain import calculation_summary, change_summary, reason_text, reasons
from finals_notice import APPROVAL_PRIVACY_NOTICE, DOCUMENT_REFERENCE, LIVE_TRANSFER_NOTICE, NOTICE_POINTS, NOTICE_TITLE
from finals_privacy import describe, sensitive_kinds
from finals_provider import ProviderError, availability, complete_json, paid_call_allowed

# [수정: 0 이영 · Claude] 2026-10-01 01:05 KST — 실행 기록(finals.pipeline)과 모듈 불러오기 오류를 서버 로그(Cloud 콘솔)로 내보낸다. 스크립트가 다시 실행돼도 핸들러는 한 번만 붙인다.
_log = logging.getLogger("finals")
if not _log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    _log.addHandler(_handler)
_log.setLevel(logging.INFO)


def _int_env(name, default):
    try:
        return max(-1, int(os.environ.get(name, default)))
    except ValueError:
        return default

st.set_page_config(page_title="근거관문 · 근거 검산", page_icon=":material/fact_check:", layout="wide", initial_sidebar_state="expanded")

# [수정: 0 이영] 2026-09-30 23:50 KST — 사용자 HTML 참고 공통 테마로 검산 화면을 맞추며 계산·확인 정책은 유지한다.
from importlib import import_module
web_theme = import_module("core.0_이영_웹테마")
web_theme.render_theme()
web_theme.render_brand()

CATEGORIES = {"normal":"정상", "mismatch":"수치 불일치", "evidence_missing":"근거 부족", "data_changed":"자료 변경"}
STATE_NAMES = {"ARITHMETIC_MATCH":"수치 일치", "MATCH":"수치 일치", "ARITHMETIC_MISMATCH":"수치 불일치", "MISMATCH":"수치 불일치", "BLOCK":"보류", "BLOCKED":"보류", "INPUT_CHANGED":"변경 후 재사용 차단", "APPROVED":"사람 확인 완료", "PROPOSED":"후보 접수", "NOT_RUN":"미실행", "SUPPORTED_PREVIEW":"조건 검산 완료", "CONFLICT_PREVIEW":"수치 불일치", "MISSING":"근거 부족", "BLOCKED_CHANGED_INPUT":"변경 후 재사용 차단", "MODEL_BLOCKED":"AI 요청 중단", "IMPORTED_REVIEW":"불러온 기록(읽기 전용)", "GENERAL_AI_MATCH":"일반 AI 단독 응답: 일치(검산 아님)", "GENERAL_AI_MISMATCH":"일반 AI 단독 응답: 불일치(검산 아님)", "GENERAL_AI_BLOCK":"일반 AI 단독 응답: 보류(검산 아님)", "GENERAL_AI_STALE_BLOCK":"일반 AI 단독 응답: 변경 차단(검산 아님)"}
MODES = {"수동 작성":"manual", "실시간 AI":"live", "저장 응답 재생":"replay"}
SENSITIVE = {"api_key", "apikey", "authorization", "password", "secret", "access_token", "refresh_token", "credential", "credentials"}


def public_snapshot(value):
    """수정 이유: 원출력·보고서를 표시하거나 내려받을 때 인증 값이 함께 남는 경로를 막는다."""
    if isinstance(value, dict):
        return {str(key):public_snapshot(item) for key,item in value.items() if str(key).lower() not in SENSITIVE}
    if isinstance(value, (list,tuple)):
        return [public_snapshot(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"sk-[A-Za-z0-9_\-]{12,}", "[인증 값 제외]", value)
    if value is None or isinstance(value, (bool,int,float)):
        return value
    return str(value)


def state_of(report):
    return str(report.get("state", report.get("status", report.get("action", "NOT_RUN"))))


def approved(report):
    approval = report.get("human_approval") if report else None
    return approval is True or isinstance(approval, dict) and approval.get("status") == "APPROVED"


def invalidate_review():
    # 수정 이유: 후보·작성 경로가 바뀐 뒤 검산이나 사람 승인을 재사용하지 않는다.
    st.session_state.pop("fin_report", None)
    st.session_state.pop("fin_exported_report", None)
    st.session_state["fin_human_confirm"] = False
    st.session_state["fin_reason"] = ""
    st.session_state["fin_step"] = 1 if "fin_source_locator" in st.session_state and not st.session_state["fin_source_locator"].strip() else 2


def notice_error(error):
    code = str(error) if isinstance(error, ProviderError) else str(getattr(error, "code", "INPUT_OR_CONNECTION_ERROR"))
    if code in {"credit_balance_exhausted", "insufficient_quota", "RATE_LIMITED", "INSUFFICIENT_QUOTA", "MODEL_HTTP_429"}:
        st.error("AI 생성 요청이 사용 한도 문제로 중단됐습니다. 수동 작성으로 계속할 수 있습니다.")
    elif str(error) == "REPORT_INTEGRITY_MISMATCH":
        st.error("보고서 검증 지문이 맞지 않습니다. 화면에서 내려받은 파일을 그대로 다시 열어 주세요.")
    elif reason_text(str(error)) != str(error):
        # [수정: 0 이영 · Claude] 작성 시각 미확인; 03 검토 2026-10-01T02:08:17+09:00 — 개인정보 차단 같은 알려진 오류 코드는 원인을 구별해 알린다(이전에는 모두 '입력 또는 연결을 확인하지 못했습니다'였다).
        code = str(error)
        st.error(reason_text(code))
    else:
        st.error("입력 또는 연결을 확인하지 못했습니다. 조건과 공개 원문을 다시 확인하세요.")
    st.session_state["fin_action_error"] = code


def reset_case(case_id):
    # 수정 이유: 사례·입력이 바뀌면 후보, 검산, 직접 확인과 승인 사유를 함께 초기화한다.
    for key in ("fin_report", "fin_candidate_text", "fin_human_confirm", "fin_reason", "fin_action_error", "fin_reopened", "fin_exported_report", "fin_source_locator"):
        st.session_state.pop(key, None)
    st.session_state["fin_case_id"] = case_id
    st.session_state["fin_step"] = 1


def health_record():
    try:
        data = json.loads((AGENT_ROOT.parent / "docs/0_이영_AI연결점검.json").read_text(encoding="utf-8"))
        return {"status":data.get("status"),"checked_at_kst":data.get("checked_at_kst"),"code":data.get("generation_check",{}).get("error_code")}
    except (OSError,ValueError,TypeError):
        return {}


st.markdown('<div class="final-kicker">EVIDENCE GATE · 근거 검산</div>', unsafe_allow_html=True)
st.title("확인할 수치를 고르고, 근거부터 검토하세요")
st.caption("원문 · 분석 조건 · 자료 지문 · 사람 확인")
# [수정: 0 이영 · Claude] 작성 시각 미확인; 03 검토 2026-10-01T02:08:17+09:00 — 모의 심사 피드백: AI 윤리 원칙(편향·공정성·투명성)과 개인정보 처리를 화면에 명시한다. 문장은 finals_notice 한 곳에서 관리한다.
with st.expander(NOTICE_TITLE):
    for notice_title, notice_body in NOTICE_POINTS:
        st.markdown(f"**{notice_title}** — {notice_body}")
    st.caption(DOCUMENT_REFERENCE)

try:
    import finals_cases as cases
    import finals_pipeline as pipeline
except ImportError as error:
    # [수정: 0 이영 · Claude] 2026-10-01 01:05 KST — 실제 원인(예: 배포 환경에 빠진 패키지)을 서버 로그에 남긴다. 화면에는 안내만 보인다.
    logging.getLogger("finals.app").error("본선 분석 모듈 불러오기 실패: %s", error)
    st.error("본선 분석 모듈을 준비 중입니다. 연결이 완료되면 사례 검토를 시작할 수 있습니다.")
    st.stop()

catalog = cases.list_cases()
# [수정: 0 이영] 2026-09-30 23:54 KST — 사례와 작성 방법을 읽기 흐름에 보여 모바일에서도 바로 검토를 시작할 수 있게 한다.
with st.container(border=True):
    st.caption("본선 작업 · 담당 0 · 이영")
    st.subheader("검토할 사례")
    category = st.selectbox("사례 유형", ["전체",*CATEGORIES.values()], key="fin_category")
    selected = [item for item in catalog if category == "전체" or CATEGORIES.get(item.get("category")) == category]
    if not selected:
        st.info("이 유형에 등록된 사례가 없습니다.")
        st.stop()
    case_id = st.selectbox("등록 사례", [item["id"] for item in selected], format_func=lambda cid:next(item["label"] for item in selected if item["id"] == cid), key="fin_case_select")
    if st.session_state.get("fin_case_id") != case_id:
        reset_case(case_id)
    mode_label = st.radio("후보 작성 방법", list(MODES), key="fin_mode",on_change=invalidate_review)
    st.divider()
    status = availability()
    st.markdown("**AI 연결**")
    if status.get("available"):
        st.caption("인증 설정 있음 · " + str(status.get("model", "모델 확인 필요")))
        previous = health_record()
        if previous.get("status") == "GENERATION_BLOCKED":
            # [수정: 0 이영 · Claude] 2026-10-01 01:05 KST — 점검 기록 파일은 과거 사실이다. 시각을 함께 보여 현재 상태로 오해하지 않게 한다.
            st.warning("가장 최근 생성 요청은 사용 한도 문제로 중단됐습니다." + (f" (점검 기록 {previous['checked_at_kst']})" if previous.get("checked_at_kst") else ""))
            st.caption("실제 응답이 생성되기 전에는 AI 분석을 완료로 표시하지 않습니다.")
    else:
        st.info("AI 연결 설정이 없습니다. 수동 작성으로 검토할 수 있습니다.")
    st.markdown("<kbd>Tab</kbd> 이동 · <kbd>Enter</kbd> 실행", unsafe_allow_html=True)

with st.expander("저장한 보고서 다시 열기"):
    uploaded = st.file_uploader("검산 보고서 JSON 파일",type=["json"],key="fin_report_upload")
    pasted = st.text_area("보고서 JSON 붙여넣기",key="fin_reopen_text",height=140)
    if st.button("보고서 다시 열기",key="fin_reopen",disabled=uploaded is None and not pasted.strip()):
        # [수정: 0 이영 · Codex] 2026-10-01T02:56:24+09:00 — 새 파일 검증이 실패하면 이전 기록이 이번 성공처럼 남지 않도록 먼저 비운다.
        st.session_state.pop("fin_reopened", None)
        try:
            text = uploaded.getvalue().decode("utf-8") if uploaded is not None else pasted
            st.session_state["fin_reopened"] = public_snapshot(pipeline.reopen_report(text))
        except Exception as exc:
            notice_error(exc)
    if st.session_state.get("fin_reopened"):
        st.json(st.session_state["fin_reopened"])
        st.caption("불러온 기록은 새로운 사람 승인으로 처리하지 않습니다.")

context = cases.load_case(case_id)
report = st.session_state.get("fin_report")
summary = st.columns([1.3,1,1])
summary[0].caption("선택 사례")
summary[0].write(next(item["label"] for item in catalog if item["id"] == case_id))
summary[1].caption("검산 상태")
summary[1].write(STATE_NAMES.get(state_of(report), state_of(report)) if report else "미실행")
summary[2].caption("사람 확인")
summary[2].write("직접 승인 완료" if approved(report) else "미승인")
st.divider()

# [수정: 0 이영 · Codex] 2026-10-01 KST — 조지현 UI의 네 단계와 입력 변경 시 검토 해제를 실제 동선에 연결한다.
from core.review_steps_ui import render_steps, move_step
step = st.session_state.setdefault("fin_step", 1)
render_steps(step)
with st.expander("1 근거 연결", expanded=step == 1):
    with st.container():
        st.markdown('<div class="final-step">01 / SOURCE</div>', unsafe_allow_html=True)
        st.subheader("원문과 자료")
        st.caption(str(context.get("source_location", "원문 위치 확인 필요")))
        quote = str(context.get("source_quote", ""))
        st.markdown('<div class="final-note">' + html.escape(quote or "확인 가능한 인용이 없습니다.") + '</div>', unsafe_allow_html=True)
        if context.get("paper_url"):
            st.link_button("공개 원문 열기", context["paper_url"])
        st.caption("등록된 자료 미리보기 · 상위 8행")
        frame = context.get("dataframe")
        if frame is not None:
            if not isinstance(frame,pd.DataFrame):
                frame = pd.DataFrame(frame)
            st.dataframe(frame.head(8), width="stretch", hide_index=True)
            st.caption(f"등록 자료 {len(frame):,}행 · {len(frame.columns)}열")
        else:
            st.info("원자료 미리보기가 제공되지 않았습니다.")

    locator = st.text_input("확인한 원문 위치", value=str(context.get("source_location") or ""), key="fin_source_locator", on_change=invalidate_review)
    if st.button("조건 확인으로", key="fin_source_next", type="primary", disabled=not locator.strip()):
        move_step("fin_step", 2)

with st.expander("2 조건 확인", expanded=step == 2):
    with st.container(border=True):
        st.markdown('<div class="final-step">02 / CONDITIONS</div>', unsafe_allow_html=True)
        st.subheader("분석 조건 검토")
        st.caption("원문이 말하는 대상·분모·단위와 실제 계산 조건을 대조합니다.")
        candidate = {}
        try:
            candidate = json.loads(st.session_state.get("fin_candidate_text", "{}"))
        except (ValueError,TypeError):
            pass
        fields = [("분석 방법","method"),("사용 열","column"),("포함·제외 조건","filters"),("분모","denominator"),("결측 처리","missing_policy"),("단위","unit")]
        rows = [{"검토 항목":label,"후보 조건":json.dumps(candidate.get(key),ensure_ascii=False) if candidate.get(key) is not None else "미확인","원문 확인":"직접 대조 필요"} for label,key in fields]
        st.dataframe(pd.DataFrame(rows),width="stretch",hide_index=True)
        if report and report.get("validation"):
            with st.expander("조건 검사 상세"):
                st.json(public_snapshot(report["validation"]))

    # 후보 작성은 같은 조건 확인 단계에 둔다.
    with st.container():
        st.markdown('<div class="final-step">03 / CANDIDATE</div>', unsafe_allow_html=True)
        st.subheader("계산 후보")
        mode = MODES[mode_label]
        if mode == "manual":
            st.caption("등록된 조건을 불러온 뒤 JSON 후보를 수정할 수 있습니다. 불러오기만으로 실행하거나 승인하지 않습니다.")
            if st.button("수동 후보 불러오기", key="fin_manual_load", width="stretch"):
                invalidate_review()
                st.session_state["fin_candidate_text"] = json.dumps(context["manual_proposal"],ensure_ascii=False,indent=2)
                st.rerun()
        elif mode == "live":
            # [수정: 0 이영 · Codex] 2026-10-01T01:38:27+09:00 — 사용자가 횟수 상한 제거를 승인했다. 기본값은 무상한이며 명시적 운영 제한·팀 로그인·전송 동의를 유지한다.
            st.caption("선택한 공개 원문과 자료 정보로 후보·비평을 요청합니다. 회당 최대 두 번의 API 요청이 발생합니다.")
            allowed_paid = paid_call_allowed()
            if not allowed_paid:
                st.info("실시간 AI는 팀 작업실에서 로그인한 팀원이 사용할 수 있습니다.")
                st.markdown("[팀 로그인으로 이동](/team)")
            send_consent = st.checkbox("선택한 공개 원문과 자료 정보를 OpenAI로 보내는 데 동의합니다", key="fin_send_consent")
            live_runs = int(st.session_state.get("fin_live_runs", 0))
            live_max = _int_env("NAIS_LIVE_MAX_RUNS", -1)
            live_ready = bool(status.get("available", False)) and bool(status.get("live_allowed", False)) and (live_max < 0 or live_runs < live_max) and allowed_paid and send_consent
            if status.get("available") and not status.get("live_allowed"):
                st.info("실시간 AI는 운영자가 켜지 않았습니다. 수동 작성이나 저장 응답 재생으로 검토할 수 있습니다.")
            elif live_max >= 0 and live_runs >= live_max:
                st.info(f"이 화면에서 실시간 AI를 {live_max}회 모두 사용했습니다. 수동 작성으로 계속할 수 있습니다.")
            st.caption(LIVE_TRANSFER_NOTICE)   # 누르기 전에 전송 범위를 보여 준다
            if st.button("실시간 AI로 후보 생성", key="fin_live_generate", disabled=not live_ready, width="stretch"):
                if not paid_call_allowed() or not send_consent or not availability().get("live_allowed") or (live_max >= 0 and int(st.session_state.get("fin_live_runs", 0)) >= live_max):
                    st.error("팀 로그인, 자료 전송 동의와 실행 허용을 다시 확인하세요.")
                    st.stop()
                try:
                    st.session_state["fin_live_runs"] = live_runs + 1  # 호출 전에 센다: 실패해도 횟수는 소모된다
                    invalidate_review()
                    with st.spinner("공개 원문에서 조건 후보를 요청하고 있습니다…"):
                        fresh = pipeline.run_case(case_id,mode="live",provider=complete_json)
                    st.session_state["fin_report"] = public_snapshot(fresh)
                    proposed = fresh.get("candidate",fresh.get("proposal"))
                    if proposed is not None:
                        st.session_state["fin_candidate_text"] = json.dumps(proposed,ensure_ascii=False,indent=2)
                    st.rerun()
                except Exception as exc:
                    notice_error(exc)
        else:
            replays = pipeline.list_replays() if hasattr(pipeline,"list_replays") else []
            replays = [item for item in replays if Path(item["path"]).is_file()]
            if not replays:
                st.info("저장된 실제 AI 응답이 없습니다. 수동 작성 또는 실시간 AI를 선택하세요.")
            replay_path = st.selectbox("실제 응답 파일",[item["path"] for item in replays],format_func=lambda path:Path(path).name,key="fin_replay_file",disabled=not replays) if replays else None
            if st.button("저장 응답으로 검토",key="fin_replay_run",disabled=not replays,width="stretch"):
                try:
                    st.session_state["fin_report"] = public_snapshot(pipeline.run_case(case_id,mode="replay",replay_path=replay_path))
                    st.rerun()
                except Exception as exc:
                    notice_error(exc)
        candidate_text = st.text_area("후보 JSON", key="fin_candidate_text",height=240,on_change=invalidate_review,help="원문 보고값과 자료 지문을 유지하고, 알 수 없는 조건은 추측하지 않습니다.")
        if st.button("지원 계산으로", key="fin_conditions_next", type="primary", disabled=not candidate_text.strip() or not locator.strip()):
            move_step("fin_step", 3)

with st.expander("3 지원 계산", expanded=step == 3):
    st.caption("원문 대상·분모와 선택한 조건을 대조한 뒤 계산합니다. 계산 가능한 범위 밖의 조건은 보류합니다.")
    if st.button("조건 검산",key="fin_compute",type="primary",disabled=step != 3 or not candidate_text.strip() or not locator.strip(),width="stretch"):
        try:
            if st.session_state.get("fin_step") != 3 or not locator.strip() or cases.text_key(locator) != cases.text_key(context.get("source_location")):
                raise ValueError("SOURCE_OR_STAGE_REQUIRED")
            with st.spinner("조건과 원문을 대조하고 다시 계산하고 있습니다…"):
                st.session_state["fin_report"] = public_snapshot(pipeline.run_case(case_id,mode="manual",proposal_text=candidate_text))
            st.session_state["fin_human_confirm"] = False
            st.session_state["fin_reason"] = ""
            st.rerun()
        except Exception as exc:
            notice_error(exc)

    report = st.session_state.get("fin_report")
    if report:
        with st.container(border=True):
            st.markdown('<div class="final-step">04 / RESULT</div>', unsafe_allow_html=True)
            st.subheader("검산 결과")
            state = state_of(report)
            if state in {"ARITHMETIC_MATCH","MATCH","APPROVED","SUPPORTED_PREVIEW"}:
                st.success(STATE_NAMES.get(state,state))
            elif "MISMATCH" in state or state in {"BLOCK","BLOCKED","INPUT_CHANGED","MISSING","BLOCKED_CHANGED_INPUT","MODEL_BLOCKED"}:
                st.warning(STATE_NAMES.get(state,state))
            else:
                st.info(STATE_NAMES.get(state,state))
            # [수정: 0 이영 · Claude] 2026-10-01 01:05 KST — 판정 이유가 JSON 안의 영문 코드로만 보였다. 한 문장 요약과 이유 목록을 먼저 보여 주고 JSON은 그대로 둔다.
            summary_line = calculation_summary(report.get("calculation"))
            # [수정: 0 이영 · Claude] 작성 시각 미확인; 03 검토 2026-10-01T02:13:04+09:00 — 배포본 직접 확인: 자료 변경 뒤에도 "허용오차 안에서 일치합니다"가 그대로 남아 차단 판정과 모순돼 보였고
            # 무엇이 바뀌었는지는 어디에도 없었다. 변경이 있으면 변경 설명을 먼저 쓰고, 변경 전 계산은 '사용 불가' 참고용으로만 보여 준다.
            what_changed = change_summary(report)
            if what_changed:
                st.markdown("**무엇이 바뀌었나**")
                for line in what_changed:
                    st.write("· " + line)
                if summary_line:
                    st.caption("변경 전 계산(참고용 · 다시 쓸 수 없음): " + summary_line)
            elif summary_line:
                st.write(summary_line)
            explained = reasons(report)
            if explained:
                st.markdown("**판정 이유**")
                for line in explained:
                    st.write("· " + line)
            if report.get("calculation"):
                if what_changed:
                    with st.expander("변경 전 계산 상세(참고용)"):
                        st.json(public_snapshot(report["calculation"]))
                else:
                    st.json(public_snapshot(report["calculation"]))
            if report.get("reason"):
                st.write(str(report["reason"]))
            critique = report.get("critique")
            if critique:
                with st.expander("검토 의견",expanded=True):
                    # [수정: 0 이영] 2026-10-01 00:52 KST — 검토 의견 호출의 반환 객체가 화면에 출력되는 현상을 방지한다.
                    if isinstance(critique, (dict, list)):
                        st.json(public_snapshot(critique))
                    else:
                        st.write(str(critique))
            if st.button("자료 변경 후 재검산",key="fin_change",width="stretch"):
                try:
                    st.session_state["fin_report"] = public_snapshot(pipeline.recheck_changed_input(report))
                    st.session_state["fin_step"] = 2
                    st.session_state["fin_human_confirm"] = False
                    st.session_state["fin_reason"] = ""
                    st.rerun()
                except Exception as exc:
                    notice_error(exc)

        if st.button("검토 기록으로", key="fin_result_next", disabled=not report.get("can_approve")):
            move_step("fin_step", 4)

with st.expander("4 검토 기록", expanded=step == 4):
    report = st.session_state.get("fin_report")
    if report:
        with st.container(border=True):
            st.markdown('<div class="final-step">05 / HUMAN REVIEW</div>', unsafe_allow_html=True)
            st.subheader("사람의 최종 확인")
            st.caption("수치 일치는 연구 내용의 타당성을 증명하지 않습니다. 원문과 여섯 조건을 직접 확인한 사람이 사유를 남깁니다.")
            # [수정: 3 조지현 · 2026-10-01T02:06:18+09:00] 승인 대상의 세 입력 지문을 표시해 변경된 근거에 대한 확인을 돕는다.
            with st.expander("승인에 연결된 자료·원문·분석 조건"):
                bindings = report.get("input_bindings", {})
                for label, field in (("자료", "data_sha256"), ("원문", "source_sha256"), ("분석 조건", "proposal_sha256")):
                    st.caption(label)
                    st.code(bindings.get(field, "지문 없음: 새 검산 필요"), language=None)
            confirmed = st.checkbox("원문 근거와 분석 조건을 직접 확인했습니다",key="fin_human_confirm")
            reason = st.text_area("승인 사유",key="fin_reason",height=100,placeholder="어떤 근거와 조건을 확인했는지 적어 주세요.")
            st.caption(APPROVAL_PRIVACY_NOTICE)
            # [수정: 0 이영 · Claude] 작성 시각 미확인; 03 검토 2026-10-01T02:08:17+09:00 — 승인 사유의 개인정보 형태를 누르기 전에 알리고 승인 버튼을 막는다(파이프라인도 같은 검사로 거부한다).
            reason_kinds = sensitive_kinds(reason)
            if reason_kinds:
                st.warning(f"승인 사유에 {describe(reason_kinds)} 형태가 있습니다. 보고서 파일에 그대로 저장되므로 지우고 다시 적어 주세요.")
            can_approve = step == 4 and report.get("can_approve") is True and not approved(report) and not reason_kinds
            # [01 이채우][작업번호 1] 승인 완료 후의 중복 승인 방지를 오류·근거 부족 안내와 구분한다.
            if approved(report):
                st.success("이미 직접 승인한 보고서입니다. 아래에서 보고서를 저장할 수 있습니다. 중복 승인은 막습니다.")
            elif reason_kinds:
                st.caption("승인 사유의 개인정보·인증 값 형태를 지운 뒤 다시 확인해 주세요.")
            elif not can_approve:
                st.caption("현재 상태에서는 승인할 수 없습니다. 근거·검산·변경 상태를 먼저 확인하세요.")
            if st.button("직접 확인하고 승인",key="fin_approve",disabled=not(can_approve and confirmed and reason.strip()),width="stretch"):
                try:
                    if st.session_state.get("fin_step") != 4:
                        raise ValueError("REVIEW_STAGE_REQUIRED")
                    st.session_state["fin_report"] = public_snapshot(pipeline.approve_report(report,reason=reason,confirmed=confirmed))
                    st.rerun()
                except Exception as exc:
                    notice_error(exc)

    # [수정: 0 이영 · Codex] 계산 영수증은 미승인 상태도 내보내며 검토 완료와 구분한다.
    st.divider()
    st.subheader("보고서 저장과 다시 열기")
    st.caption("실제 실행 상태, 확인 사유와 입력 지문을 보고서로 저장합니다. 다시 연 보고서는 현재 입력과의 연결을 재검사합니다.")
    report = st.session_state.get("fin_report")
    if report:
        payload = pipeline.export_report(public_snapshot(report))
        st.session_state["fin_exported_report"] = payload
        st.download_button("검산 보고서 JSON 내려받기",payload,file_name=f"0_이영_{case_id}_검산보고서.json",mime="application/json",key="fin_report_download")
        with st.expander("보고서 상세 보기"):
            st.json(public_snapshot(report))

with st.expander("검토 초기화"):
    reset_confirm = st.checkbox("현재 세션의 작성 내용과 검산 결과를 초기화합니다", key="fin_reset_confirm")
    if st.button("초기화", key="fin_reset", disabled=not reset_confirm):
        reset_case(case_id)
        st.rerun()
# [수정: 0 이영 · Codex] 2026-10-01 03:21 KST — 새 main 승인 안내·세 입력 지문은 보존하고 불러오기는 위, 저장은 검토 뒤로 통합한다.
# [수정: 3 조지현 · 2026-10-01T02:08:17+09:00] 기준 커밋보다 뒤인 주석 시각은 원작성 시각으로 확인할 수 없어 미확인으로 표시했다. 원표기는 별도 검토 기록에 보존한다.
# [3 조지현 · 2026-10-01T02:13:04+09:00] 통합 후 추가 주석의 원작성 시각을 확인할 수 없어 미확인 표시; 실제 검토 시각과 원표기를 분리 기록한다.

# [작성: 0 이영 · Codex] 2026-09-30 23:32 KST — 공개 본선 페이지와 별도로 기존 인증된 연구팀 기능을 한 웹사이트에 연결한다.
"""Evidence Gate — public evidence snapshots, Korea search and bounded follow-up."""
# [수정: 0 이영] 2026-09-30 21:05 KST — 본선 레인 0 편입. 제품 표기에서 사전 버전 번호(case105) 제거; 버전은 VERSION 파일(0.1.0)과 아래 상수로만 표시.
from __future__ import annotations
import json
import io
import hashlib
import html
import pandas as pd
import streamlit as st
from core.activity_privacy import activity_view, activity_detail
from core.models import Claim,Status
from core.pdf_claims import extract_pdf_pages,extract_html_blocks,extract_numeric_claims
from core.semantic import decompose_claim,build_plan
from core.verifier import verify,verify_reported_claim,refresh_reported_status,auto_verify
from core.statistics import DESCRIPTIVE_METHODS
from core.audit import AuditDB
from core.workflow import revise_and_reverify,approve_reverified,refresh_audited_approval
from tools.reproduce_horse import audit_horse
from tools.reproduce_monarch import audit_monarch
from tools.mutation_demo import run_demo
from tools.case_registry import audit_registry
from core.provenance import dataframe_hash
from core.logging_utils import get_logger
from core.ui import CSS,LANDING_HTML
from core.typed_contracts import build_typed_contract,check_evidence_sufficiency,contract_summary,ContractType
from core.presentation import contract_view,human_missing,queue_detail,fmt_number,provenance_label
from core.executor import execute_contract
from core.analysis_spec import AnalysisSpecification,build_analysis_spec,check_analysis_spec,validate_multiplicity_family
from core.structured_logging import get_event_logger,event
from core.audit_store import AuditStore
from core.decision_provenance import proposed, DecisionProvenance, is_confirmed
event_logger=get_event_logger()
from core.gates import interpretation_gate,inferential_reproduction_gate
from core.decision_provenance import proposed as candidate, DecisionProvenance as ProvenanceRecord
from core.public_pdf_benchmark import run_public_pdf_pipeline

from core.paths import AUDIT_DB_PATH,CHANGE_DB_PATH,RUNTIME_LOG_PATH,PROJECT_ROOT
from core.team_workspace import require_member, render_workspace, member_role
from core.rbac import can
from core.reproducibility import hash_json
from tools.independent_replay import make_packet,replay_packet
# [수정: 전문가1/4] 2026-09-26 case63: 버전 기록과 페이지 제목을 변경 영향 검증실 배포에 맞춤.
# [수정: 전문가4] 2026-09-26 case64: 무엇/왜: 배포 버전과 실제 소스 결속 수정 일치 / 입출력: 버전 상수 -> 감사 기록·페이지 제목 / 검증: VERSION·앱 상수 대조.
# [수정: 전문가9] 2026-09-26 case65
# 종류: 오류수정 / 재현 방법: 이전 버전 식별자로 새 코드를 실행 / 변경 전: case64 / 변경 후: case65 / 왜: 실행 기록과 배포 식별 일치 / 영향: 과거 승인은 현재 소스와 구분.
# [수정: 전문가4] 2026-09-27 case66: 공개 논문 수집 릴리스 식별만 갱신; 분석·승인 동작은 유지.
# [수정: 전문가4] 2026-09-27 case70 / 종류: 효율화 / 재현: 인계자료 분산 / 전후: case69 기능 유지·case70 공유 이력 표시 / 영향: 버전 표기만, 재계산·검색 로직 불변.
from core.input_security import validate_csv_bytes,safe_csv_export_bytes
# [수정: 전문가9] 2026-09-29 case92
# 종류: 효율화 / 재현 방법: 릴리스 버전 점검 / 변경 전: case91 / 변경 후: VERSION과 case92 일치 / 왜: 로컬/배포 식별 / 영향: 계산 불변; test_case38.
# case105: reuse release markers; snapshots and partial evidence never approve claims.
# [수정: 0 이영] 2026-09-30 21:05 KST — 사전 제품 번호가 본선 실행의 감사 기록·화면·내려받기 파일명에 찍히던 문제 수정. VERSION(0.1.0)과 일치(test_case38·case73·case74가 대조).
# [수정: 0 이영] 2026-09-30 22:01 KST — AGENTS.md 결정으로 VERSION=0(0.1.0 아님). page_title은 test_case38·case73·case74가 리터럴 "Evidence Gate V{major}"로 대조하므로 f-string 대신 리터럴.
APP_VERSION="0";ENGINE_VERSION="rule-engine-v0";logger=get_logger(str(RUNTIME_LOG_PATH))
st.set_page_config(page_title="Evidence Gate V0",page_icon="◈",layout="wide");st.markdown(CSS,unsafe_allow_html=True)
# [수정: UI/UX 조지현] 2026-09-30 case105-UI / 팀 디자인(블루·IBM Plex Sans KR)을 기존 CSS 위에 덮어 적용. 표시 전용.
from core.theme import THEME_CSS;st.markdown(THEME_CSS,unsafe_allow_html=True)
# [수정: 0 이영] 2026-09-30 23:50 KST — 공개 연구데스크와 같은 참고 테마를 인증 화면에도 적용한다.
from importlib import import_module
import_module("core.0_이영_웹테마").render_theme()
# case105: public delivery validates four release snapshots before member login; no private exports.
with st.sidebar.expander("다른 AI에서 공개 근거 읽기"):
    from core.public_agent import render_public_delivery
    render_public_delivery(key_prefix='public_before_login')
reviewer=require_member()
reviewer_role=member_role(reviewer)
st.sidebar.caption(f"권한 역할: {reviewer_role}")
for key,default in [("claims",[]),("df",None),("db",None),("audit_store",None),("dataset_hash",""),("dataset_name",""),("selected_claim",""),("audit_event_keys",set()),("snapshotted_runs",set()),("public_benchmark_mode",False),("horse_audit_mode",False),("monarch_audit_mode",False),("mutation_demo_mode",False),("csv_bytes",b'')]:
    if key not in st.session_state:
        if key=="db": st.session_state[key]=AuditDB(str(CHANGE_DB_PATH))
        elif key=="audit_store": st.session_state[key]=AuditStore(str(AUDIT_DB_PATH))
        else: st.session_state[key]=default

# [수정: 전문가4] 2026-09-25 case39
# 종류: 오류수정 | 재현 방법: 서로 다른 검토자가 같은 사건 기록.
# 변경 전: demo_reviewer / 변경 후: 인증된 팀원 이름.
# 왜: 검토 책임 추적 / 영향: 개인별 사건과 provenance 보존.
def record_event(name, *, claim_id="", actor="SYSTEM", detail="", source="", **fields):
    """Write one canonical event to JSONL + persistent SQLite audit ledger.

    case29 AUDIT CHANGE — WHY: lifecycle evidence must survive browser/session restarts and all
    execution/revision/approval paths must carry the current app/engine provenance.
    """
    # case30 AUDIT SAFETY — SQLite is canonical; JSONL is only an operational projection.
    msg=str(detail or fields.get("message", ""))
    key=st.session_state.audit_store.append(claim_id,name,actor=actor,actor_id=(reviewer if actor=="HUMAN" else actor),detail=msg,source=source,
        app_version=APP_VERSION,engine_version=ENGINE_VERSION,dataset_hash=st.session_state.dataset_hash)
    try:
        event(event_logger,name,message=msg,claim_id=claim_id,dataset_hash=st.session_state.dataset_hash,engine_version=ENGINE_VERSION,app_version=APP_VERSION,actor=actor,source=source,**{k:v for k,v in fields.items() if k!="message"})
    except Exception:
        logger.exception("audit_jsonl_projection_failed canonical_key=%s",key)
    return key

def emit_once(name,claim=None,**fields):
    """Avoid duplicate lifecycle events caused by Streamlit reruns.

    case25 AUDIT CHANGE — WHY: Streamlit reruns the script on every interaction. Logging lifecycle
    events without an idempotency key would manufacture duplicate audit records.
    """
    cid=getattr(claim,'claim_id','') if claim is not None else fields.get('claim_id','')
    # [수정: 전문가4] 2026-09-23 case38
    # 종류: 오류수정
    # 재현 방법: 새 PDF/CSV에서도 C-01 같은 Claim ID가 재사용되면 이전 데이터셋의 session idempotency key가 새 이벤트를 억제할 수 있었다.
    # 변경 전: (event, claim_id, state, message)만으로 세션 중복 방지.
    # 변경 후: dataset_hash를 키에 포함해 데이터셋 경계를 분리.
    # 왜: Claim ID는 문서별 로컬 식별자이며 서로 다른 데이터셋의 동일 ID는 별개 사건이다.
    # 영향: 같은 데이터셋 rerun은 계속 멱등이고, 새 데이터셋은 독립적인 계보를 기록한다.
    key=(st.session_state.dataset_hash,reviewer if fields.get("actor")=="HUMAN" else "SYSTEM",name,cid,fields.get('state',''),fields.get('message',''))
    if key in st.session_state.audit_event_keys:return
    st.session_state.audit_event_keys.add(key)
    actor=fields.get("actor","SYSTEM"); detail=str(fields.get("message",fields.get("state",""))); source=fields.get("source","")
    # case29 AUDIT CHANGE — WHY: case28's visible lifecycle lived only in Streamlit session state.
    # Persist the same Claim event before rendering it so a new browser session can reconstruct it.
    record_event(name,claim_id=cid,actor=actor,detail=detail,source=source,**{k:v for k,v in fields.items() if k not in {'claim_id','actor','source','message'}})

def enrich(c):
    if st.session_state.df is None:return
    c.decomposition=decompose_claim(c.text,c.original_value);plan=build_plan(c.text,c.decomposition,st.session_state.df)
    c.evidence_candidates=plan["candidates"];c.filters=plan["filters"]
    if not c.column:c.column=plan["recommended_column"]
    c.aggregation=plan["aggregation"] if plan["aggregation"] in DESCRIPTIVE_METHODS else "mean"
    # case27 PROVENANCE CHANGE
    # FAILURE: case26 displayed a heuristic method (e.g. Welch t-test) like a confirmed paper method.
    # RISK: a proposed method can silently become the reproduction specification.
    # WHY: every AI/heuristic proposal must remain a candidate until a human or direct PDF evidence confirms it.
    # CHANGE: store method_candidate separately; promote it only in the explicit confirmation workflow.
    if plan["aggregation"] not in DESCRIPTIVE_METHODS:
        c.method_candidate=plan["aggregation"];c.method_candidate_source="system_candidate"
        c.method_provenance=candidate(c.method_candidate, source="system_candidate", source_location=f"원문 #{c.source_page or '?'}").to_dict()
        if not c.method_confirmed:c.analysis_method=""
    else:
        c.analysis_method=plan["aggregation"];c.method_confirmed=True;c.method_candidate=plan["aggregation"];c.method_candidate_source="deterministic_descriptive";c.method_provenance=candidate(c.method_candidate,source="deterministic_descriptive",source_location=f"원문 #{c.source_page or '?'}").confirm("SYSTEM").to_dict()
    c.x_column=plan.get("x_column","") or c.x_column;c.group_column=plan.get("group_column","") or c.group_column;c.group_a=plan.get("group_a","") or c.group_a;c.group_b=plan.get("group_b","") or c.group_b

# [수정: 전문가4] 2026-09-25 case39
# 종류: 오류수정 | 재현 방법: 다른 세션 기록 후 예시 클릭.
# 변경 전: 전체 원장 삭제 / 변경 후: 화면 상태만 갱신.
# 왜: 팀원 감사기록 보존 / 영향: 과거 원장은 유지된다.
def load_demo():
    # [수정: 전문가2] 2026-09-25 case59
    # 종류: 오류수정 | 재현 방법: 말 논문 화면에서 예시 버튼을 누르면 말 화면이 유지됨 / 변경 전: horse_audit_mode 잔존 / 변경 후: 다른 화면 모드 해제 / 왜: 선택한 분석을 보여주기 위해 / 영향: 감사 자료 값 불변.
    st.session_state.horse_audit_mode=False;st.session_state.monarch_audit_mode=False;st.session_state.mutation_demo_mode=False;st.session_state.public_benchmark_mode=False
    # [수정: 전문가4] 2026-09-23 case38
    # 종류: 오류수정
    # 재현 방법: 같은 세션에서 예시 데이터를 다시 불러오면 audit_store는 비워져도 audit_event_keys가 남아 새 계보 기록이 생략될 수 있었다.
    # 변경 전: DB와 execution snapshot만 초기화.
    # 변경 후: session idempotency key도 함께 초기화.
    # 왜: 새 분석 작업은 독립된 audit lifecycle을 가져야 한다.
    # 영향: 단순 Streamlit rerun 중복 방지는 유지하면서 새 작업 시작 시 필요한 사건은 다시 기록된다.
    st.session_state.audit_event_keys=set();st.session_state.snapshotted_runs=set();st.session_state.csv_bytes=(PROJECT_ROOT/"data/demo.csv").read_bytes();df=pd.read_csv(io.BytesIO(st.session_state.csv_bytes));st.session_state.df=df;st.session_state.dataset_name="demo.csv";st.session_state.dataset_hash=hash_json({"data":dataframe_hash(df),"source":"builtin-demo"})
    st.session_state.claims=[Claim("C-01","처리군 평균 개선율은 14.8%였다.",14.8,source_page=1,source_quote="처리군 평균 개선율은 14.8%였다."),Claim("C-02","처리군 평균 개선율은 18.4%였다.",18.4,source_page=2,source_quote="처리군 평균 개선율은 18.4%였다."),Claim("C-03","모든 조건에서 효과가 확인되었다.",None,source_page=3,source_quote="모든 조건에서 효과가 확인되었다."),Claim("C-04","처리군과 대조군의 평균 개선율은 유의하게 달랐다.",None,source_page=4,source_quote="처리군과 대조군의 평균 개선율은 유의하게 달랐다.",method_candidate="welch_t",method_candidate_source="system_candidate",column="outcome_pct",group_column="group",group_a="처리군",group_b="대조군")]
    for c in st.session_state.claims:enrich(c)
    # case26 DEMO CHANGE — WHY: case25 demo showed only descriptive blocking, so the new Analysis
    # Specification gate was invisible to judges. C-04 intentionally demonstrates BLOCKED →
    # specification confirmation → deterministic Welch execution.
    c4=next(c for c in st.session_state.claims if c.claim_id=="C-04")
    c4.analysis_method="";c4.method_candidate="welch_t";c4.method_candidate_source="system_candidate";c4.method_confirmed=False;c4.method_provenance=candidate("welch_t",source="system_candidate",source_location="PDF p.4").to_dict();c4.column="outcome_pct";c4.group_column="group";c4.group_a="처리군";c4.group_b="대조군"
    st.session_state.selected_claim="C-02"

def contract_for(c):return build_typed_contract(c,st.session_state.dataset_name,st.session_state.dataset_hash)

def issue_meta(c):
    if st.session_state.df is not None:refresh_reported_status(c,st.session_state.df)
    contract=contract_for(c);check=check_evidence_sufficiency(contract,st.session_state.df)
    if contract.contract_type==ContractType.SCOPE:return (0,"범위 검토","BLOCKED")
    if not c.semantic_confirmed:return (1,"근거 확인","PENDING")
    run=execute_contract(contract,st.session_state.df,build_analysis_spec(c))
    if run["state"]=="BLOCKED":return (0,"근거 부족","BLOCKED")
    if contract.contract_type==ContractType.DESCRIPTIVE:
        # [수정: 전문가5] 2026-09-25 case40
        # 종류: 오류수정
        # 재현 방법: C-02의 18.4를 14.8로 바꾸면 목록에서 논문 재현 성공으로 변했다.
        # 변경 전: 사후 정정값을 논문 원값 판정에 재사용.
        # 변경 후: 원문 original_value에 대한 별도 판정을 목록과 요약에 사용.
        # 왜: 정정 승인이 원 논문 Claim의 재현 실패를 지우면 안 된다.
        # 영향: 정정 후에도 원문 충돌은 FAIL로 남는다.
        s,_,_=verify_reported_claim(c,st.session_state.df)
        if s==Status.CONFLICT:return (0,"수치 불일치","FAIL")
        if s==Status.SUPPORTED:return (4,"재현 성공","PASS")
    if contract.contract_type in {ContractType.ASSOCIATION,ContractType.REGRESSION,ContractType.COMPARATIVE}:
        rg=inferential_reproduction_gate(c,run["result"])
        # [수정: 전문가6] 2026-09-25 case43
        # 종류: 오류수정 / 재현 방법: 추론 원문 판정이 화면에는 표시되어도 공유 모델에 남지 않음 / 변경 전: 반환값만 갱신 / 변경 후: 원문 상태와 이유를 별도 보존 / 왜: 정정안과 공유 기록 분리 / 영향: 원문 판정이 사후 정정으로 바뀌지 않음.
        c.reported_status=Status.SUPPORTED if rg.status=="PASS" else Status.CONFLICT if rg.status=="FAIL" else Status.REVIEW
        c.reported_reason=rg.detail
        if rg.status=="FAIL":return (0,"추론 재현 실패","FAIL")
        return (2,"방법/해석 검토","REVIEW")
    return (3,"검토 필요","REVIEW")

def gate_html(name,status,title):
    cls={"PASS":"pass","FAIL":"fail","BLOCKED":"blocked","REVIEW":"review","PENDING":"review","NA":"na","APPLICABLE":"pass"}.get(status,"review")
    return f'<div class="eg-gate eg-{cls}"><div class="eg-gate-name">{name} · {status}</div><div class="eg-gate-title">{title}</div></div>'

def audit(action,c,before_status,after_status,reason,before_value=None,after_value=None,evidence_value=None,actor="SYSTEM"):
    st.session_state.db.add(c.claim_id,reviewer if actor=="HUMAN" else actor,action,before_status,after_status,reason,before_value,after_value,evidence_value)

# [수정: 전문가6·7] 2026-09-28 case81
# 종류: 오류수정 / 재현: 화면 승인과 실행 기록 미결속 / 변경 후: 검증서명·계산자료 지문 보존 / 검증: test_case81_audit.py.
def claim_snapshot(c):
    return {"claim_id":c.claim_id,"text":c.text,"original_value":c.original_value,"current_value":c.current_value,"reported_status":c.reported_status.value,"amendment_status":c.amendment_status.value,"source_page":c.source_page,"source_quote":c.source_quote,"reported_p_value":c.reported_p_value,"reported_effect":c.reported_effect,"reported_ci95":c.reported_ci95,"verification_signature":c.verification_signature(),"dataframe_hash":dataframe_hash(st.session_state.df)}

# [수정: 전문가6·7] 2026-09-28 case81
# 종류: 오류수정 / 재현: 저장 실패 후에도 중복으로 생략 / 변경 후: 서명별 기록 성공 후 중복표시 / 검증: 화면 회귀.
def persist_execution_snapshot(c,contract,run):
    """Persist the exact scientific execution, not just an 'executed' event.

    case30 REPRODUCIBILITY — WHY: later contract edits must not rewrite history.
    """
    if run.get("state")!="EXECUTED":return None
    spec=build_analysis_spec(c).to_dict(); key=(c.claim_id,st.session_state.dataset_hash,c.verification_signature(),json.dumps(contract.to_dict(),sort_keys=True,default=str),json.dumps(run.get("result"),sort_keys=True,default=str))
    if key in st.session_state.snapshotted_runs:return None
    meta=st.session_state.audit_store.record_execution(claim_id=c.claim_id,claim_snapshot=claim_snapshot(c),contract_snapshot=contract.to_dict(),analysis_spec_snapshot=spec,result_snapshot=run.get("result"),dataset_hash=st.session_state.dataset_hash,app_version=APP_VERSION,engine_version=ENGINE_VERSION)
    record_event("EXECUTION_SNAPSHOT",claim_id=c.claim_id,detail=json.dumps(meta,ensure_ascii=False),contract_type=contract.contract_type.value,state="EXECUTED",rows_used=run.get("rows_used"))
    st.session_state.snapshotted_runs.add(key)
    return meta


# [작성: 전문가4] 2026-09-25 case45
# 무엇을: PDF·HTML·TXT와 CSV의 같은 검증 시작 경로 / 왜: 공개 논문 전체 본문도 앱의 근거 확인·계약·감사 경로로 처리 / 입력·출력: 파일명·원본 bytes -> 세션 Claim 목록 / 검증: tests/test_case45.py와 Streamlit 시작·공개 사례 수동 동선.
def start_analysis(source_name,source_bytes,csv_name,csv_bytes):
    # [수정: 전문가2] 2026-09-25 case59
    # 종류: 오류수정 | 재현 방법: 말 논문 화면에서 새 자료를 올리면 이전 화면 유지 / 변경 전: 화면 모드 잔존 / 변경 후: 새 분석으로 전환 / 왜: 업로드 동작과 결과 일치 / 영향: 실행 게이트 불변.
    st.session_state.horse_audit_mode=False;st.session_state.monarch_audit_mode=False;st.session_state.mutation_demo_mode=False;st.session_state.public_benchmark_mode=False
    validate_csv_bytes(csv_bytes)
    df=pd.read_csv(io.BytesIO(csv_bytes))
    ext=source_name.lower().rsplit('.',1)[-1]
    if ext=='pdf':blocks=extract_pdf_pages(source_bytes)
    elif ext in {'html','htm'}:blocks=extract_html_blocks(source_bytes)
    elif ext=='txt':blocks=list(enumerate(source_bytes.decode('utf-8-sig').splitlines(),1))
    else:raise ValueError('지원하지 않는 원문 형식')
    raw=extract_numeric_claims(blocks,limit=500)
    st.session_state.df=df;st.session_state.dataset_name=csv_name
    st.session_state.source_bytes=source_bytes;st.session_state.csv_bytes=csv_bytes
    st.session_state.dataset_hash=hash_json({'data':dataframe_hash(df),'source_sha256':hashlib.sha256(source_bytes).hexdigest()})
    st.session_state.source_name=source_name
    st.session_state.audit_event_keys=set();st.session_state.snapshotted_runs=set();st.session_state.claims=[]
    for x in raw:
        c=Claim(x['claim_id'],x['text'],x['value'],source_page=x.get('page'),source_quote=x['text'],claim_type=x.get('claim_type','percentage'),reported_p_value=x.get('p_value'),reported_p_operator=x.get('p_operator',''),reported_effect=x.get('reported_effect'),effect_kind=x.get('effect_kind',''),reported_ci95=x.get('ci95'))
        enrich(c);st.session_state.claims.append(c);emit_once('CLAIM_EXTRACTED',c,contract_type='');emit_once('EVIDENCE_PROPOSED',c,contract_type='')
    st.session_state.selected_claim=st.session_state.claims[0].claim_id if st.session_state.claims else ''
    record_event('ANALYSIS_STARTED',detail=f'claims={len(raw)} source={source_name}')
    return len(raw)

# [작성: UX 통합] 2026-09-29 case93
# 목적: 쉬운 화면에서 기존 체험을 눌러도 해당 작업으로 이동; 입력: 버튼 콜백; 검증: test_case93_navigation.
def open_detailed_review():
    st.session_state.workspace_view="논문 검증"

# [수정: UX 교차검수] 2026-09-29 case93
# 새 자료가 들어오면 기존 검증 작업으로 이동. 같은 자료에서 사용자가 쉬운 화면을 선택하면 유지한다.
# 입력: Claim ID·자료지문·df 존재 / 검증: test_case39, test_case62_ui, test_case93_navigation.
loaded_analysis=(tuple(c.claim_id for c in st.session_state.claims),st.session_state.dataset_hash,st.session_state.df is not None)
if loaded_analysis != st.session_state.get("last_loaded_analysis"):
    if loaded_analysis[0] and loaded_analysis[2]:
        st.session_state.workspace_view="논문 검증"
    st.session_state.last_loaded_analysis=loaded_analysis

with st.sidebar:
    # [수정: 전문가1/4] 2026-09-26 case63: 고정 등록 주장의 변경·확장 검증실 진입점.
    st.markdown("## NAIS · 연구 데스크")
    st.caption("논문을 찾고, 근거를 확인하고, 기록으로 남기세요.")
    with st.expander("전문가 작업실 · 기존 검증 도구", expanded=st.session_state.get("workspace_view", "쉬운 연구 도우미")!="쉬운 연구 도우미"):
        workspace_view=st.radio("작업 화면",["쉬운 연구 도우미","논문 검증","팀 공동 작업실","평가 준비실","변경·확장 검증실","논문 근거 검색"],key="workspace_view")
    with st.expander("상세 검증 · 파일 업로드 · 기존 체험", expanded=workspace_view!="쉬운 연구 도우미"):
        st.markdown("### 입력");pdf=st.file_uploader("보고서 PDF·HTML·TXT",type=["pdf","html","htm","txt"]);csv=st.file_uploader("원자료 CSV",type=["csv"])
        if st.button("원문·CSV 분석 시작",on_click=open_detailed_review,type="primary",width="stretch",disabled=not(pdf and csv)):
            try:
                start_analysis(pdf.name,pdf.getvalue(),csv.name,csv.getvalue());st.rerun()
            except Exception as exc:logger.exception("case38_analysis_failed");record_event("ANALYSIS_FAILED",detail=str(exc));st.error(f"분석 시작 오류: {exc}")
        # [수정: 전문가1] 2026-09-25 case45
        # 종류: 효율화 / 재현 방법: 공개 논문 재현 시 원문과 CSV를 매번 따로 내려받아 업로드 / 변경 전: 업로드 2회 / 변경 후: 묶인 공개 사례를 동일 분석 경로에 원클릭 로드 / 왜: 5분 시연 / 영향: 분석 조건은 여전히 사람 확인 전 차단.
        if st.button("실제 공개 논문 사례 불러오기",on_click=open_detailed_review,width="stretch"):
            try:
                src=PROJECT_ROOT/'data/evaluation/penguin_article_text.txt';data=PROJECT_ROOT/'data/penguins_public_benchmark.csv'
                start_analysis(src.name,src.read_bytes(),data.name,data.read_bytes())
                # [수정: 전문가1] 2026-09-25 case52
                # 종류: 효율화 / 재현 방법: 공개 연습 버튼이 항상 범위 충돌 C-01을 열어 16개 후보 중 검산 후보를 수동 탐색 / 변경 전: 첫 추출 후보 선택 / 변경 후: 이 고정 연습 자료의 결측 19 Claim을 첫 화면에 선택 / 왜: 5분 시연에서 차단→사람 확인→재계산을 따라가기 쉽게 함 / 영향: 일반 업로드·추출·채점 규칙 불변, 이 선택은 사람 정답이 아님.
                practice_claim=next((c for c in st.session_state.claims if c.aggregation=="missing_cells" and c.original_value==19 and "penguins dataset" in c.text.lower()),None)
                if practice_claim:st.session_state.selected_claim=practice_claim.claim_id
                st.session_state.public_benchmark_mode=False;st.rerun()
            except Exception as exc:logger.exception('case45_public_paper_load_failed');st.error(f'공개 사례 불러오기 오류: {exc}')
        st.caption('공개 연습 사례는 결측 19 Claim을 먼저 보여줍니다. 자동 정확도 평가나 사람 승인 정답은 아닙니다.')
        # [수정: 전문가1] 2026-09-25 case58
        # 종류: 효율화 / 재현 방법: 말 논문 자료 대조가 명령줄에만 존재 / 변경 전: 앱에서 확인 불가 / 변경 후: 출처·관측 합계·결측·모형 차단을 같은 화면에 표시 / 왜: 부분 재현과 미실행을 5분 시연에서 구분 / 영향: 일반 Claim 파이프라인·승인 상태 불변.
        if st.button("말 논문 원자료 대조 보기",on_click=open_detailed_review,width="stretch"):
            st.session_state.horse_audit_mode=True;st.session_state.monarch_audit_mode=False;st.session_state.mutation_demo_mode=False;st.session_state.public_benchmark_mode=False;st.rerun()
        # [작성: 전문가1] 2026-09-25 case59
        # 무엇을: 두 번째 저자 원자료의 범위 한정 PCA 대조 진입 / 왜: 재현 가능한 단계와 논문 전체 승인을 화면에서 구분 / 입력·출력: 버튼 -> 저자 코드 범위 수치 및 BLOCK / 검증: tests/test_case59_monarch_ui.py.
        if st.button("왕나비 논문 원자료 대조 보기",on_click=open_detailed_review,width="stretch"):
            st.session_state.monarch_audit_mode=True;st.session_state.horse_audit_mode=False;st.session_state.mutation_demo_mode=False;st.session_state.public_benchmark_mode=False;st.rerun()
        # [작성: 전문가1] 2026-09-25 case60
        # 무엇을: 합성 Claim의 자료·필터·방법 변경 승인 무효화 실험 진입 / 왜: 검증 인프라의 강제 절차를 짧게 시연 / 입력·출력: 버튼 -> 세 재승인 사유 / 검증: tests/test_case60_mutation_ui.py.
        if st.button("승인 후 변경 감지 실험",on_click=open_detailed_review,width="stretch"):
            st.session_state.mutation_demo_mode=True;st.session_state.horse_audit_mode=False;st.session_state.monarch_audit_mode=False;st.session_state.public_benchmark_mode=False;st.rerun()
        st.divider()
        if st.button("블라인드 공개 연구 벤치마크",on_click=open_detailed_review,width="stretch"):
            st.session_state.public_benchmark_mode=True;st.session_state.horse_audit_mode=False;st.session_state.monarch_audit_mode=False;st.session_state.mutation_demo_mode=False;st.rerun()
        if st.button("예시 데이터로 체험하기",on_click=open_detailed_review,width="stretch"):st.session_state.public_benchmark_mode=False;load_demo();st.rerun()
        if st.button("초기화",on_click=open_detailed_review,width="stretch"):st.session_state.claims=[];st.session_state.audit_event_keys=set();st.session_state.df=None;st.session_state.dataset_hash="";st.session_state.dataset_name="";st.session_state.selected_claim="";st.session_state.snapshotted_runs=set();st.session_state.public_benchmark_mode=False;st.session_state.horse_audit_mode=False;st.session_state.monarch_audit_mode=False;st.session_state.mutation_demo_mode=False;st.session_state.source_bytes=b'';st.session_state.csv_bytes=b'';st.rerun()
    st.caption(f"V{APP_VERSION} · {ENGINE_VERSION}")

# [작성: 전문가1/4] 2026-09-26 case63: 일반 검증과 분리된 개발자 등록 자료 비교 화면.
# [작성:전문가1·4] 2026-09-27 case68 목적: 논문 읽기 검색 진입; 입력: 화면 선택; 출력: 검색 UI; 검증: 기존 Claim 실행·승인 경로와 분리.
# [작성: UX 통합] 2026-09-29 case93 / 쉬운 기본 화면; 기존 검산 게이트는 그대로 유지.
if workspace_view=="쉬운 연구 도우미":
    # 2026-09-29 case95: discovery-first navigation; external metadata never becomes verified evidence.
    # Pending navigation is consumed before widgets to avoid Streamlit state mutation errors.
    from core.research_tasks_ui import render_research_tasks, scoped_key
    from core.research_home import render_home_header
    if not st.session_state.get(scoped_key(reviewer, 'guided_demo_open')):
        render_home_header()
    from core.research_demo_ui import render_guided_demo
    if render_guided_demo(reviewer):
        st.stop()
    home_key=scoped_key(reviewer,"home_view")
    next_view=st.session_state.pop(scoped_key(reviewer,"home_next"),None)
    if next_view in {"논문 둘러보기","공공·위성 데이터 찾기","예시·내 연구 과제","대학 연구 소식","연구 관심 순위","다른 AI와 연결"}:
        st.session_state[home_key]=next_view
    home=st.radio("시작할 작업",["논문 둘러보기","공공·위성 데이터 찾기","예시·내 연구 과제","대학 연구 소식","연구 관심 순위","다른 AI와 연결"],horizontal=True,key=home_key,label_visibility="collapsed")
    if home=="논문 둘러보기":
        from core.paper_discovery_ui import render_paper_discovery
        render_paper_discovery(reviewer)
        from core.research_digest_ui import render_digest
        render_digest(reviewer,kind="papers")
    elif home=="공공·위성 데이터 찾기":
        # case100: same actor-scoped UI and read-only adapters as the MCP data tools.
        from core.ntis_ui import render_ntis
        render_ntis(reviewer)
        from core.research_data_ui import render_research_data
        render_research_data(reviewer)
    elif home=="다른 AI와 연결":
        from core.public_agent import render_public_agent
        render_public_agent()
    elif home=="연구 관심 순위":
        from core.paper_rankings import render_rankings
        render_rankings(reviewer)
    elif home=="대학 연구 소식":
        from core.research_news import render_research_news
        render_research_news(reviewer)
        from core.research_digest_ui import render_digest
        render_digest(reviewer,kind="news")
    else:
        from core.team_materials_ui import render_team_materials
        render_team_materials()
        render_research_tasks(reviewer)
        with st.expander("고급 도구 · 선택 근거로 AI 초안 작성 / 개별 검사", expanded=False):
            from core.research_assistant_ui import render_research_assistant
            render_research_assistant()
    st.stop()

if workspace_view=="논문 근거 검색":
    from core.paper_library_ui import render_paper_library
    render_paper_library()
    st.stop()
if workspace_view=="변경·확장 검증실":
    from core.portfolio_workspace import render_portfolio_workspace
    render_portfolio_workspace()
    st.stop()

if workspace_view=="팀 공동 작업실":
    render_workspace(reviewer)
    st.stop()

# [수정: UX·통합 담당] 2026-09-28 case85
# 종류: 오류수정 / 재현: 평가 준비실은 사람 라벨만 안내 / 변경 전: 자동검산 진입 없음 / 변경 후: 기존 검산기·보관 비교 연결 / 왜: 가능한 평가와 의미승인 구분 / 영향: 자동 승인 없음.
# [작성: 전문가1·7] 2026-09-26 case61
# 무엇을: 팀 내부 평가의 다음 행동과 빈 양식을 한 화면에 연결 / 왜: 외부 전문가 없이 진행 가능한 절차와 실제 증거의 차이를 명시 / 입력·출력: 작업 화면 선택 -> 문서·빈 양식 / 검증: tests/test_case61_evaluation_ui.py.
if workspace_view=="평가 준비실":
    st.title("평가 준비실")
    from core.portfolio_workspace import render_machine_evaluation
    render_machine_evaluation()
    st.divider()
    st.subheader("선택 사항: 사람이 참여할 때의 별도 평가")
    st.warning("사람 판정 대기 · 실제 비교 점수 없음")
    st.markdown("팀원이 직접 판정한 **내부 탐색 평가**를 준비합니다. 개발 참여 편향을 공개하며 **외부 독립 검증**과 구분합니다.")
    st.markdown("1. 입력·프롬프트·판정 기준을 먼저 고정합니다.\n2. 실제 사람이 출력에 영향을 받지 않고 정답을 판정합니다.\n3. 같은 조건으로 양쪽 시스템을 실행하고 원출력을 보관합니다.\n4. 같은 모든 사례의 검토시간을 기록한 뒤 비교합니다.")
    st.caption("사전 고정 → 사람 라벨 → 양쪽 실행 → 사람 검토시간의 순서를 검사합니다. 신원과 시각은 자기신고 기록이며 외부 인증이 아닙니다.")
    st.download_button("빈 평가 양식 내려받기",data=(PROJECT_ROOT/"docs/team_evaluation_template.json").read_bytes(),file_name="team_evaluation_template.json",mime="application/json")
    st.download_button("평가 실행 절차 내려받기",data=(PROJECT_ROOT/"docs/internal_evaluation.md").read_bytes(),file_name="internal_evaluation.md",mime="text/markdown")
    st.info("현재 실행은 내려받은 절차의 Python 명령을 사용합니다. 이 화면은 사람 라벨을 자동으로 채우거나 비교 모델을 유료 호출하지 않습니다. 작성한 기록은 팀 공동 작업실에 저장할 수 있습니다.")
    st.subheader("이전 버전에서 확보한 원자료와 검증 범위")
    st.markdown("[Skylark·Callan(2021) 공식 논문](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0259711)의 원자료와 저자 분석 코드를 확보했습니다.")
    pending=audit_registry(PROJECT_ROOT/"docs/evidence_acquisition_proposal.json")["results"][0]
    st.warning("이전 버전에서 확보한 독립 원자료 1쌍 · 이번 신규 확보 0쌍 · 논문 전체 재현 0건 · 사람 승인 0건")
    st.caption("모집단·조건 승인 대기: 원자료 383명에 저자의 결측·중복·연령·주의력 검사 제외 규칙을 적용합니다. 아래 계산은 개발자 평가이며 제품 검증 승인을 대신하지 않습니다.")
    from tools.cohort_replay import run_cohort
    try:
        cohort=run_cohort(PROJECT_ROOT/"data/evaluation/paper_pairs/deprivation/cohort_manifest.json")
        st.subheader("저자 표본 제외 절차 재계산")
        st.dataframe(pd.DataFrame(cohort["stages"]).replace({"raw_rows":"원자료", "complete_cases_all_columns":"결측 제외", "sss_sum_equals_1":"주관적 지위 응답 합계 1", "duplicate_equals_0":"중복 제외", "age_18_through_100":"18~100세", "attention_ENV_5_equals_2":"주의력 검사 통과"}).rename(columns={"name":"단계", "input_rows":"입력 인원", "excluded_rows":"제외 인원", "remaining_rows":"남은 인원"}),hide_index=True)
        st.write(f"최종 표본 {cohort['final_rows']}명 · 보고값 {cohort['reported_value']}명 · 산술 차이 {cohort['arithmetic_difference']}")
        st.caption("개발자 평가: 명시적으로 옮긴 제외 규칙의 산술 재실행입니다. 저자 R 전체 실행·논문 전체 재현·사람 승인·제품 게이트 승인이 아닙니다.")
    except (ValueError, OSError) as error:
        st.error(f"원자료 재계산 차단: {error}")
    st.download_button("원자료 출처·확보 기록 내려받기",data=(PROJECT_ROOT/"docs/evidence_acquisition.md").read_bytes(),file_name="evidence_acquisition.md",mime="text/markdown")
    st.stop()

if st.session_state.horse_audit_mode:
    st.title("말 논문: 원자료 대조와 실행 차단")
    st.caption("Carmo 등(2023), PLOS ONE 10.1371/journal.pone.0286045 · 저자 Figshare v1 원자료·Rmd 해시 확인")
    result=audit_horse()
    if not result['integrity_ok']:
        st.error("원자료 또는 저자 분석 코드가 누락·변경되어 모든 대조를 차단했습니다.")
    else:
        table=result['table3_elevated_neck']
        if table['status']=='MATCH_DESCRIPTIVE_ONLY':
            a=table['groups']['Experimental'];b=table['groups']['Controle']
            st.success(f"Table 3 관측 합계 일치: 보상 단계 1건, 대조 단계 4건. 원자료의 기록된 사건 수만 검산했습니다.")
            st.info(f"결측은 보상 단계 {a['missing']}건, 대조 단계 {b['missing']}건입니다. 0으로 대체하지 않았습니다.")
        else:st.error("Table 3 관측 합계 불일치: 일치 판정을 내리지 않습니다.")
        st.warning("낮은 목 자세 혼합모형의 승산비·신뢰구간·유의확률: 실행하지 않아 차단. 관측 합계가 모형 재현을 뜻하지 않습니다.")
        st.caption("모형 후보 집단 52행 중 결측 제외 50행·13마리. 실제 모형 실행·진단과 사람 검토가 필요합니다.")
    if st.button("논문 검증 화면으로 돌아가기"):
        st.session_state.horse_audit_mode=False;st.rerun()
    st.stop()

if st.session_state.monarch_audit_mode:
    st.title("왕나비 논문: 저자 코드 범위의 원자료 대조")
    st.caption("Freedman 등(2020), PNAS 10.1073/pnas.2001283117 · 저자 공개 코드 440–461행, 공통환경 성체 자료")
    result=audit_monarch()
    if not result['integrity_ok']:
        st.error("저자 원자료·분석 코드의 파일 지문이 맞지 않아 대조를 차단했습니다.")
    else:
        pc=result['size_pc1']
        if pc['status']=='MATCH_SCOPED_PCA':
            st.info(f"저자 코드의 공통환경 성체 {pc['denominator_rows']:,}행에서 PC1 설명분산 {pc['computed_percent']:.6f}%를 계산했습니다. 보고 96.4%와 한 자리 반올림 범위에서 일치합니다.")
        else:
            st.error("저자 코드 범위의 PC1 설명분산과 보고 96.4%가 일치하지 않습니다.")
        st.warning("논문 문단은 이 PCA의 모집단을 명시하지 않습니다. 저자 R 전체 스크립트는 실행하지 않았으며 논문 전체 재현·사람 승인 결론은 차단합니다.")
        st.caption("자료·코드 SHA-256을 검사했습니다. 우연히 비슷한 다른 모집단의 99.178%를 96.4%와 비교하지 않습니다.")
    if st.button("논문 검증 화면으로 돌아가기",key="monarch_return"):
        st.session_state.monarch_audit_mode=False;st.rerun()
    st.stop()

if st.session_state.mutation_demo_mode:
    st.title("승인 후 변경 감지 실험")
    st.caption("합성 4행 원자료와 가상 사람 승인을 사용합니다. 실제 논문 재현이나 검토자 신원 확인 결과가 아닙니다.")
    try:
        result=run_demo()
        st.info(f"기준 상태: A군 평균 {result['baseline']['calculated_value']:.0f}, 승인 {result['baseline']['engine_status']}.")
        labels={'csv_bytes':'원자료 바이트 변경','filter':'분석집단 필터 변경','method':'계산 방법 변경'}
        rows=[{'변경':labels[key],'다시 계산한 값':part['calculated_value'],'결정':'재승인 필요' if part['action']=='REAPPROVAL_REQUIRED' else part['action'],'바뀐 조건':', '.join(part['changed_inputs']),'엔진 상태':part['engine_status']} for key,part in result['mutations'].items()]
        st.table(rows)
        st.warning("세 경우 모두 과거 승인을 재사용하지 않습니다. 이 실험은 범용 AI 대비 오류 감소율이나 실제 연구자 검토 시간을 측정하지 않습니다.")
        # [작성: 전문가1] 2026-09-25 case60
        # 무엇을: 선언형 등록에서 실행·차단 분모를 함께 표시 / 왜: 논문 참조 수를 재현 성공 수로 오해하지 않기 위해 / 입력·출력: 현재 등록 명세 -> 산술 일치·차단 표 / 검증: tests/test_case60_registry_ui.py.
        # [작성:전문가4] 2026-09-27 case69 목적: 별도 원자료 부분재계산 선택; 입력: 명세 선택; 출력: 검증표; 검증: UI 회귀, 기존 기본사례 보존.
        from pathlib import Path
        # [수정:전문가4] 2026-09-27 case69 종류: 등록명세 선택 UI / 재현: 신규 사례 진입 없음 / 전후: 기존4건만→별도2주장 선택 / 왜: 기존계약 보존 / 영향: 선택 영역만, 자동승인 없음.
        case_selection=st.selectbox("선택 사례 범위", ["기존 등록 사례", "새 공개 원자료 부분재계산"], key="reproduction_case_selection")
        expanded=case_selection=="새 공개 원자료 부분재계산"
        registered=audit_registry(Path(__file__).resolve().parent / 'data/evaluation/registered_reproduction_cases.json')['results'] if expanded else audit_registry()['results']
        matched=sum(item['action']=='ARITHMETIC_MATCH' for item in registered)
        blocked=sum(item['action']=='BLOCK' for item in registered)
        st.subheader("선언형 사례 등록 범위")
        if expanded:
            st.info(f"2개 주장 · 1개 논문 · {matched}건 산술 일치 · {blocked}건 차단 · 이전 버전에서 확보한 원자료 1쌍")
            st.caption("URL별 FAIR 평가자료의 명시적 부분 산술 재구현입니다. 저자 코드 실행 없음 · 논문 전체 재현 아님 · 사람 승인 없음. 지원 전처리 계약의 원자료·코드 변경은 변경·확장 검증실에서 추적합니다.")
            st.table([{'Claim':item['claim_id'],'원문 보고값':item.get('reported_value'),'재계산값':item.get('value'),'분석 행':item.get('rows_used'),'전체 논문 재현':item['full_paper_reproduced']} for item in registered])
        else:
            st.info(f"{len(registered)}개 논문 참조 · {matched}건 산술 일치 · {blocked}건 차단 · 새 독립 원자료 0쌍")
            st.caption("이번 등록은 기존 원자료 3쌍을 재사용했습니다. 산술 일치는 논문 전체 재현이나 사람 정답이 아닙니다.")
        st.table([{'Claim':item['claim_id'],'결과':item['action'],'이유':item.get('reason','')} for item in registered])
    except Exception as exc:
        logger.exception('case60_mutation_demo_failed');st.error(f'합성 변경 감지 실험 오류: {exc}')
    if st.button("논문 검증 화면으로 돌아가기",key="mutation_return"):
        st.session_state.mutation_demo_mode=False;st.rerun()
    st.stop()

if st.session_state.public_benchmark_mode:
    # [수정: 전문가4] 2026-09-23
    # 종류: 검증방법추가
    # 변경 전: case33 공개 benchmark는 사람이 미리 고른 curated Claim 4개를 입력으로 사용.
    # 변경 후: 사용자가 제공한 실제 공개 논문 PDF 전체를 production PDF parser부터 처리.
    # 왜: Claim extraction을 포함하지 않으면 End-to-End benchmark라고 부를 수 없음.
    # 영향: 공식 PDF가 없으면 결과를 생성하지 않으며 hidden gold는 production ZIP에 포함하지 않음.
    st.markdown('<div class="eg-hero"><div class="eg-title">블라인드 공개 PDF 벤치마크</div><div class="eg-sub">실제 공개 논문 PDF 전체 → Claim 추출 → 근거·방법 후보 → 검증계약 → 안전 차단까지 일반 production 경로로 실행합니다. 정답 라벨은 이 앱에 포함되어 있지 않습니다.</div></div>',unsafe_allow_html=True)
    bench_pdf=st.file_uploader("공개 논문 PDF",type=["pdf"],key="public_pdf_benchmark_upload")
    st.caption("권장 검증 자료: Horst, Hill & Gorman (2022), The R Journal, RJ-2022-020. 공식 PDF는 출처 페이지에서 직접 내려받아 넣으세요.")
    if bench_pdf is None:
        st.info("PDF를 넣기 전에는 benchmark 결과를 만들지 않습니다. Gold 정답은 별도 evaluator 패키지에만 존재합니다.")
    else:
        try:
            b=run_public_pdf_pipeline(bench_pdf.getvalue(),PROJECT_ROOT/'data/public_benchmark/penguins.csv')
            reviewable=sum(x.get('support_state')=='REVIEWABLE' for x in b['extracted_claims']); unsupported=sum(x.get('support_state')=='UNSUPPORTED' for x in b['extracted_claims']); executed=sum(x['action']=='EXECUTE' for x in b['extracted_claims'])
            st.markdown(f'<div class="eg-summary"><div><div class="eg-summary-k">추출 Claim 후보</div><div class="eg-summary-v">{len(b["extracted_claims"])}</div></div><div><div class="eg-summary-k">확인 후 진행 가능</div><div class="eg-summary-v">{reviewable}</div></div><div><div class="eg-summary-k">현재 엔진 미지원</div><div class="eg-summary-v">{unsupported}</div></div></div>',unsafe_allow_html=True)
            if executed: st.warning(f"사람 확인 전 실행된 Claim이 {executed}건 있습니다. False Execution 여부는 외부 evaluator에서 확인해야 합니다.")
            # [작성: 전문가2] 2026-09-23
            # 무엇을: 외부 hidden-gold evaluator에 넘길 production 결과 JSON 다운로드 제공.
            # 왜: production과 evaluator를 물리적으로 분리하면서도 현장 평가 흐름을 끊지 않기 위함.
            # 검증: JSON 직렬화는 Python 표준 json.dumps로 수행하며 앱 실행 시 다운로드 버튼으로 확인.
            st.download_button("Production benchmark 결과 JSON 저장",data=json.dumps(b,ensure_ascii=False,indent=2),file_name=f"v{APP_VERSION.split('.')[0]}_public_pdf_prediction.json",mime="application/json",width="stretch")
            for x in b['extracted_claims']:
                state=x.get('support_state','REVIEWABLE'); mark='⊘' if state=='UNSUPPORTED' else ('△' if state=='REVIEWABLE' else '!'); cls='eg-blockpill' if state=='UNSUPPORTED' else 'eg-warnpill'; label='현재 엔진 미지원' if state=='UNSUPPORTED' else ('확인 후 진행 가능' if state=='REVIEWABLE' else '실행 가능')
                st.markdown(f'<div class="eg-selected"><span class="eg-pill {cls}">{mark} {label}</span><div class="eg-claim">{x["claim_id"]} · p.{x["page"] or "?"} · {x["text"]}</div><div class="eg-muted">계약 {x["contract_type"]} · 방법 후보 {x["method_candidate"] or "미식별"}</div></div>',unsafe_allow_html=True)
                st.caption('다음 단계/차단 사유: '+str(x['blocked_reason']))
            with st.expander("Benchmark 설계와 한계"):
                st.write("이 화면은 PDF 전체 Claim extraction을 실제 production parser에서 시작합니다.")
                st.write("Recall·False Execution·False Blocking은 별도 evaluator 패키지의 hidden gold와 비교해야만 계산됩니다.")
                st.write("production 앱 자체는 gold label에 접근하지 않습니다.")
        except Exception as exc:
            logger.exception("case38_public_pdf_benchmark_failed"); st.error(f"공개 PDF benchmark 오류: {exc}")
    st.stop()

if not st.session_state.claims:
    st.markdown(LANDING_HTML,unsafe_allow_html=True);c1,c2,c3=st.columns([1,1.35,1])
    with c2:
        if st.button("▶ 예시 데이터로 검증 체험",type="primary",width="stretch",key="landing_demo"):load_demo();st.rerun()
    st.stop()

st.markdown('<div class="eg-hero"><div class="eg-title">근거관문</div><div class="eg-sub">검증 조건이 완성되기 전에는 계산하지 않습니다. 부족한 조건은 사람이 확인해 안전하게 다시 실행합니다. Claim → 근거 → 방법 → 재현 결과 → 사람 판단을 하나의 검증 계보로 남깁니다.</div></div>',unsafe_allow_html=True)
# [수정: 전문가7] 2026-09-25 case58
# 종류: 오류수정 / 재현 방법: 승인 뒤 CSV 원시 바이트 또는 방법을 바꿔도 요약의 승인 수 유지 / 변경 전: 렌더 전 승인 재검증 없음 / 변경 후: 모든 승인 Claim을 현재 입력으로 확인·해제 / 왜: 낡은 승인 표시 방지 / 영향: 입력 변경 시 사람 재승인 필요.
for reviewed_claim in st.session_state.claims:
    if reviewed_claim.status==Status.VALIDATED:
        # [수정: 전문가2·6] 2026-09-28 case81: 화면 승인을 최신 영속 실행과 대조; 취소도 원장에 남김.
        refresh_audited_approval(reviewed_claim,st.session_state.df,audit_store=st.session_state.audit_store,dataset_hash=st.session_state.dataset_hash,csv_bytes=st.session_state.csv_bytes,app_version=APP_VERSION,engine_version=ENGINE_VERSION)
metas=[(c,*issue_meta(c)) for c in st.session_state.claims];metas.sort(key=lambda x:(x[1],x[0].claim_id))
# case22 UX CHANGE — WHY: case21 mixed blocked/review/fail into one number. Judges need pipeline states.
# [수정: 전문가2] 2026-09-25 case45
# 종류: 오류수정 / 재현 방법: 공개 논문 14개 모두 근거 미확정인데 상단은 '실행 차단 0' / 변경 전: BLOCKED만 집계 / 변경 후: 실행 불가인 PENDING도 포함하고 라벨을 대기·차단으로 명시 / 왜: 안전 관문 상태를 화면과 일치 / 영향: 성공·실패·승인 값 불변.
blocked=sum(m[3] in {"BLOCKED","PENDING"} for m in metas);failed=sum(m[3]=="FAIL" for m in metas);passed=sum(m[3]=="PASS" for m in metas);approved=sum(m[0].status==Status.VALIDATED for m in metas)
st.markdown(f'<div class="eg-summary eg-summary-five"><div><div class="eg-summary-k">전체 Claim</div><div class="eg-summary-v">{len(metas)}</div></div><div><div class="eg-summary-k">실행 대기·차단</div><div class="eg-summary-v">{blocked}</div></div><div><div class="eg-summary-k">원문 재현 실패</div><div class="eg-summary-v">{failed}</div></div><div><div class="eg-summary-k">원문 재현 성공</div><div class="eg-summary-v">{passed}</div></div><div><div class="eg-summary-k">사람 판단 승인</div><div class="eg-summary-v">{approved}</div></div></div>',unsafe_allow_html=True)
left,right=st.columns([0.32,0.68],gap="large")
with left:
    st.markdown("### 검증 목록")
    filter_label=st.selectbox("상태 필터",["전체","문제","차단","검토","재현 성공"],label_visibility="collapsed",key="queue_filter")
    search_q=st.text_input("주장 검색",placeholder="문장 또는 Claim ID",key="queue_search")
    type_options={"전체":"전체","기술통계":"DESCRIPTIVE","집단 비교":"COMPARATIVE","연관성":"ASSOCIATION","회귀":"REGRESSION","범위 주장":"SCOPE"}; type_label=st.selectbox("주장 유형",list(type_options),key="queue_type"); type_filter=type_options[type_label]
    page_values=sorted({c.source_page for c in st.session_state.claims if c.source_page is not None})
    page_filter=st.selectbox("원문 위치",["전체"]+page_values,key="queue_page")
    def include_meta(m):
        state=m[3]
        if filter_label=="전체": return True
        if filter_label=="문제": return state in {"FAIL","BLOCKED","REVIEW"}
        if filter_label=="차단": return state=="BLOCKED"
        if filter_label=="검토": return state in {"REVIEW","PENDING"}
        return state=="PASS"
    shown=[m for m in metas if include_meta(m)]
    if search_q.strip(): shown=[m for m in shown if search_q.casefold() in (m[0].claim_id+" "+m[0].text).casefold()]
    if type_filter!="전체": shown=[m for m in shown if contract_for(m[0]).contract_type.value==type_filter]
    if page_filter!="전체": shown=[m for m in shown if m[0].source_page==page_filter]
    # [수정: 전문가1] 2026-09-25 case57
    # 종류: 오류수정 / 재현 방법: 검색 또는 상태 필터 결과 0건에서 전체 Claim이 다시 표시 / 변경 전: 빈 결과를 metas로 대체 / 변경 후: 빈 목록 안내 후 선택 화면 중단 / 왜: 필터 밖 Claim을 잘못 선택하지 않도록 / 영향: 조건을 지우면 기존 목록 재표시.
    if not shown:
        st.info("검색·필터 조건에 맞는 Claim이 없습니다. 조건을 바꿔 다시 검색하세요.")
        st.stop()
    ids=[m[0].claim_id for m in shown]
    labels={}
    for m in shown:
        c,_,lab,_=m; ctr=contract_for(c); chk=check_evidence_sufficiency(ctr,st.session_state.df); rr=execute_contract(ctr,st.session_state.df,build_analysis_spec(c)) if chk.executable else None
        labels[c.claim_id]=f"{c.claim_id} · {lab} | {queue_detail(lab,c,rr)} | {c.text[:30]}"
    current=st.session_state.selected_claim if st.session_state.selected_claim in ids else ids[0]
    selected=st.radio("문제 우선순위",ids,index=ids.index(current),format_func=labels.get,label_visibility="collapsed",key="claim_queue")
    st.session_state.selected_claim=selected;st.caption("문제·차단 → 검토 → 대기 → 재현 성공")
claim=next(c for c in st.session_state.claims if c.claim_id==st.session_state.selected_claim);contract=contract_for(claim);check=check_evidence_sufficiency(contract,st.session_state.df);run=execute_contract(contract,st.session_state.df,build_analysis_spec(claim));_,label,state=issue_meta(claim)
# [수정: UX·통합 담당] 2026-09-28 case83
# 종류: 검증방법추가 / 재현: AI 자유답변과 실행명세 경계 불명확 / 변경 전: 접수 없음 / 변경 후: 미확정 후보 검토 / 왜: 모델 독립 계약 / 영향: 원문·정정·승인 불변.
with st.expander('AI 분석 제안 검토 · 실행하지 않음'):
    from core.proposal_ui import render_proposal_review
    render_proposal_review(claim, st.session_state.df, st.session_state.dataset_hash)
emit_once("CONTRACT_CREATED",claim,contract_type=contract.contract_type.value)
emit_once("CONTRACT_EXECUTED" if run["state"]=="EXECUTED" else "CONTRACT_BLOCKED",claim,contract_type=contract.contract_type.value,state=run["state"])
if run["state"]=="EXECUTED":
    emit_once("REPRODUCTION_RESULT",claim,contract_type=contract.contract_type.value,state=state)
    persist_execution_snapshot(claim,contract,run)
with right:
    # [수정: 전문가4] 2026-09-23 case37
    # 종류: 오류수정
    # 재현 방법: Streamlit 위젯 조작 때마다 동일 Claim의 CONTRACT_BLOCKED가 Audit Trail에 반복 기록됨.
    # 변경 전: 상단 emit_once() 기록 뒤 right panel에서 record_event()를 다시 무조건 호출.
    # 변경 후: lifecycle 기록은 emit_once() 한 경로로만 유지하고 렌더링 구간의 중복 쓰기를 제거.
    # 왜: 화면 재실행이 감사 사건을 새로 만들어서는 안 되며 동일 사용자 행동은 멱등이어야 함.
    # 영향: 기존 저장된 중복 레코드는 보존하지만 case37 이후 같은 세션의 단순 rerun은 중복 사건을 추가하지 않음.
    pill="eg-blockpill" if state=="BLOCKED" else ("eg-passpill" if state=="PASS" else "eg-warnpill")
    # [수정: 전문가2] 2026-09-25 case45
    # 종류: 오류수정 / 재현 방법: HTML 원문 문장이 화면 태그로 해석 / 변경 전: 원문을 unsafe HTML에 직접 삽입 / 변경 후: 표시만 이스케이프 / 왜: 원문 보존과 표시 안전 / 영향: 감사 원문값 불변.
    st.markdown(f'<div class="eg-selected"><span class="eg-pill {pill}">{html.escape(label)}</span><div class="eg-claim">{html.escape(claim.claim_id)} · {html.escape(claim.text)}</div><div class="eg-muted">원문 #{claim.source_page or "?"} · 원문 보존 · Contract {contract.contract_type.value}</div></div>',unsafe_allow_html=True)
    # case27 UX/SAFETY — show candidate vs confirmed provenance before any execution controls.
    if contract.contract_type in {ContractType.COMPARATIVE,ContractType.ASSOCIATION,ContractType.REGRESSION}:
        mc=getattr(claim,"method_candidate","") or getattr(claim,"analysis_method","")
        if mc:
            prov=provenance_label(getattr(claim,"method_candidate_source",""),getattr(claim,"method_confirmed",False))
            st.markdown(f'<div class="eg-provenance"><b>분석방법</b><span>{mc}</span><span class="eg-source">{prov}</span></div>',unsafe_allow_html=True)
            if not getattr(claim,"method_confirmed",False):
                st.caption("이 분석방법은 아직 실행 명세가 아닙니다. 사람이 확인해야 검증 계약에 반영됩니다.")
    # case25 SAFETY CHANGE
    # FAILURE: case24 allowed an inferential calculation after only missing-policy confirmation.
    # RISK: population/estimand/variance/multiplicity assumptions may differ from the paper.
    # WHY: a reproduction claim is meaningful only under an explicit analysis specification.
    # CHANGE: reviewer confirms the minimum supported analysis specification before execution.
    if contract.contract_type in {ContractType.COMPARATIVE,ContractType.ASSOCIATION,ContractType.REGRESSION} and not getattr(claim,"analysis_spec_confirmed",False):
        st.markdown('<div class="eg-alert"><b>분석 명세 확인 필요</b><br>근거 연결만으로는 추론통계를 실행하지 않습니다. 분석 모집단·estimand·결측치·분산추정·다중비교 정책을 확인하세요.</div>',unsafe_allow_html=True)
        c1,c2=st.columns(2)
        with c1:
            pop=st.text_input("분석 모집단",value=getattr(claim,"analysis_population","unspecified"),key=f"pop_{claim.claim_id}")
            estimand=st.text_input("Estimand",value=getattr(claim,"estimand","unspecified"),key=f"estimand_{claim.claim_id}")
            pol=st.selectbox("결측치 처리정책",["unspecified","complete_case","multiple_imputation","ipw","other"],key=f"missing_policy_{claim.claim_id}")
        with c2:
            variance=st.selectbox("분산/표준오차 정책",["unspecified","classical","welch","robust","clustered","other"],key=f"variance_{claim.claim_id}")
            multi=st.selectbox("다중비교 정책",["unspecified","none_reported","bonferroni","holm","fdr_bh","other"],key=f"multi_{claim.claim_id}")
            family_count=st.number_input("다중비교 가족의 검정 수",min_value=0,max_value=10000,value=int(claim.multiplicity_count),step=1,key=f"multi_count_{claim.claim_id}")
            # [작성/수정: 전문가5·6] 2026-09-26 case62
            # 무엇을: 전체 p 가족의 명시 입력 / 왜: 단일 p만으로 Holm/BH를 승인하지 않음.
            family_values=[];family_definition='';family_index=None
            if multi in {'holm','fdr_bh'}:
                family_text=st.text_area("전체 검정 가족의 원 p값 (JSON 배열)",value=json.dumps(claim.multiplicity_p_values),key=f"multi_values_{claim.claim_id}")
                family_definition=st.text_input("전체 검정 가족 정의·원문 위치",value=claim.multiplicity_family_definition,key=f"multi_definition_{claim.claim_id}")
                family_target=st.number_input("대상 검정 번호 (1부터 시작)",min_value=1,max_value=10000,value=(claim.multiplicity_target_index or 0)+1,step=1,key=f"multi_target_{claim.claim_id}")
                st.caption("원문의 전체 가족·순서와 반올림하지 않은 원 p값을 입력하세요. 다른 검정의 자동 재계산 또는 실제 사람 인증을 뜻하지 않습니다. BH는 FDR 보정이며 독립 또는 적절한 양의 의존 조건을 검토해야 합니다.")
            st.caption("현재 실행 엔진이 지원하지 않는 정책은 확인하더라도 실행이 차단됩니다.")
        if st.button("이 분석 명세를 확인",key=f"confirm_spec_{claim.claim_id}"):
            # [작성/수정: 전문가5·6] 2026-09-26 case62
            # 무엇을: 저장 전 임시 가족 검증 / 왜: 잘못된 입력은 기존 Claim과 감사 명세를 바꾸지 않음.
            try:
                if multi in {'holm','fdr_bh'}:
                    family_values=json.loads(family_text)
                    family_index=int(family_target)-1
                    temporary=AnalysisSpecification(multiplicity_policy=multi,multiplicity_count=int(family_count),multiplicity_p_values=family_values,multiplicity_target_index=family_index,multiplicity_family_definition=family_definition.strip())
                    validate_multiplicity_family(temporary)
            except (TypeError,ValueError) as exc:
                st.error(f"분석 명세를 저장하지 않았습니다: {exc}")
            else:
                claim.analysis_population=pop.strip() or "unspecified";claim.estimand=estimand.strip() or "unspecified"
                claim.missing_policy=pol;claim.missing_policy_confirmed=(pol!="unspecified")
                claim.variance_estimator=variance;claim.multiplicity_policy=multi;claim.multiplicity_count=int(family_count);claim.analysis_spec_confirmed=True
                claim.multiplicity_p_values=family_values;claim.multiplicity_target_index=family_index;claim.multiplicity_family_definition=family_definition.strip()
                record_event("ANALYSIS_POLICY_CONFIRMED",claim_id=claim.claim_id,actor="HUMAN",contract_type=contract.contract_type.value,detail=json.dumps(build_analysis_spec(claim).to_dict(),ensure_ascii=False))
                st.rerun()

    # case25 UX CHANGE — WHY: judges should see the scientific result before internal architecture.
    if run["state"]=="BLOCKED":
        st.markdown('<div class="eg-alert"><b>⊘ 검증 실행 보류</b><br>검증에 필요한 근거 또는 분석 명세가 아직 완성되지 않았습니다.</div>',unsafe_allow_html=True)
    elif contract.contract_type==ContractType.DESCRIPTIVE:
        _v=run["result"]["value"];_d=abs(_v-claim.original_value) if claim.original_value is not None else None
        _status,_,_=verify_reported_claim(claim,st.session_state.df)
        _headline="✓ 수치 재현 성공" if _status==Status.SUPPORTED else ("! 수치 재현 실패" if _status==Status.CONFLICT else "△ 보고값 확인 필요")
        _reported=claim.original_value if claim.original_value is not None else "—"
        _diff=fmt_number(_d)
        st.markdown(f'<div class="eg-result-hero"><div class="eg-title">{_headline}</div><div class="eg-result-flow"><div><div class="eg-label">논문 보고값</div><div class="eg-result-num">{fmt_number(_reported)}</div></div><div class="eg-result-arrow">→</div><div><div class="eg-label">원자료 재계산</div><div class="eg-result-num">{fmt_number(_v)}</div></div></div><div class="eg-result-note">차이 {_diff} · 허용오차 ±{claim.tolerance:g} · 사용 행 {run.get("rows_used",0)}</div></div>',unsafe_allow_html=True)
        if claim.revision_count:
            st.info(f"사람 정정값 {fmt_number(claim.current_value)} · 정정안 {claim.amendment_status.value} · 원문 {claim.reported_status.value}; 위 논문 원문 판정은 바뀌지 않습니다.")
        # [수정: 전문가4] 2026-09-25 case45
        # 종류: 검증방법추가 / 재현 방법: 실행 snapshot JSON만으로 제3자가 원자료 해시를 검증하며 재계산할 수 없음 / 변경 전: 계약과 결과만 다운로드 / 변경 후: 원문·CSV·해시·기대값 묶음 제공 / 왜: 독립 재실행 / 영향: 원자료가 포함되므로 사용자 본인만 내려받아 공유 여부를 결정.
        # [작성/수정: 전문가4·5·6] 2026-09-26 case62
        # 무엇을: 지원 분석을 실제 재생·행수·분모 대조 후 다운로드 / 왜: 정규화 차이나 불완전 필터로 거짓 재현 묶음 방지.
        # 입력·출력: 실제 실행 계약과 원본 CSV -> 일치한 ZIP만 노출 / 검증: tests/test_case62_ui.py.
        executed_method=run["result"].get('method',contract.aggregation)
        if executed_method in {'mean','row_count','missing_cells'} and st.session_state.get('source_bytes') and st.session_state.get('csv_bytes'):
            st.caption("독립 재실행: 필터는 문자열 정확 일치 AND, 결측은 빈 CSV 셀만(blank-only missing) 처리합니다. ZIP 해시는 자기일관성·산술 검사이며 인증이 아닙니다. 원문 진위·범위는 검증하지 않습니다.")
            try:
                exact_filters={}
                for item in contract.filters:
                    if not isinstance(item,dict) or set(item)!={'column','value'} or not isinstance(item['column'],str) or item['column'] in exact_filters:
                        raise ValueError('독립 재실행은 중복 필터 열·추가 연산자(op)를 지원하지 않습니다.')
                    if not isinstance(item['value'],(str,int,float)) or isinstance(item['value'],bool):
                        raise ValueError('독립 재실행 필터 값은 단일 문자열 또는 숫자여야 합니다.')
                    exact_filters[item['column']]=str(item['value'])
                packet=make_packet(st.session_state.source_name,st.session_state.source_bytes,st.session_state.dataset_name,st.session_state.csv_bytes,claim.claim_id,executed_method,claim.original_value,_v,claim.source_page,column=contract.variable if executed_method=='mean' else None,filters=exact_filters,missing_policy='drop')
                replay=replay_packet(packet)
                if replay['action']!='ARITHMETIC_MATCH' or replay['rows_used']!=run.get('rows_used') or replay['observations_used']!=run['result'].get('n'):
                    raise ValueError('독립 재실행의 값·사용행·분모가 엔진과 다릅니다. 문자열 필터 또는 결측 정규화 차이를 확인하세요.')
            except (TypeError,ValueError,KeyError,OverflowError) as exc:
                st.warning(f"독립 재실행 다운로드 차단: {exc}")
            else:
                st.download_button('제3자 독립 재실행 묶음 ZIP',packet,file_name=f'{claim.claim_id}_replay.zip',mime='application/zip',key=f'packet_{claim.claim_id}')
                # [작성: 전문가9·15] 2026-09-28 case81: 원본 재현 자료를 보존하며 별도 수식 방어 사본 제공.
                try:
                    safe_csv=safe_csv_export_bytes(st.session_state.csv_bytes)
                    st.download_button('원자료 스프레드시트 안전 보기',safe_csv,file_name=f'{claim.claim_id}_spreadsheet_view.csv',mime='text/csv',key=f'safe_csv_{claim.claim_id}')
                    st.caption('안전 보기는 수식 시작 문자 앞에 작은따옴표를 붙인 사본입니다. 재현에는 ZIP 안의 원본을 사용하세요.')
                except ValueError as exc:
                    st.warning(f'안전 보기 생성 불가: {exc}')

    else:
        st.markdown(f'<div class="eg-hero"><div class="eg-title">△ 추론통계 재현 결과 · 사람 검토 필요</div><div class="eg-sub">{contract.contract_type.value} 계약을 결정론적 엔진으로 재실행했습니다. 자동 승인하지 않습니다.</div></div>',unsafe_allow_html=True)

    # 2026-09-29 case95: explain results beside the numbers, without changing engine thresholds.
    from core.result_guidance import render_result_guidance
    render_result_guidance(run, contract.contract_type.value)

    # case22 UX CHANGE — WHY: machine contract remains available in details, but the primary card
    # must speak the reviewer's language: verification type, confirmed/candidate evidence, next action.
    cv=contract_view(contract)
    field_html="".join(f'<div class="eg-contract-field"><span>{k}</span><b>{v}</b></div>' for k,v in cv["fields"])
    st.markdown(f'<div class="eg-contract {"blocked" if not check.executable else ""}"><div class="eg-contract-type">검증 유형 · {cv["type"]}</div><div class="eg-contract-fields">{field_html}</div></div>',unsafe_allow_html=True)
    if not check.executable:
        missing=" · ".join(human_missing(check.missing))
        st.markdown(f'<div class="eg-alert"><b>검증 실행 보류</b><br>추가로 필요한 근거: {missing}<br><span class="eg-muted">근거가 확정되기 전에는 계산하거나 결론을 생성하지 않습니다.</span></div>',unsafe_allow_html=True)
    # case28 PROVENANCE SAFETY
    # FAILURE: case27 used one button to confirm both evidence semantics and the proposed statistical method.
    # RISK: confirming a column could silently approve a method the paper never used.
    # WHY: evidence, method, and analysis policy are independent scientific decisions.
    # CHANGE: each layer has its own explicit confirmation and provenance event.
    # REGRESSION: tests/test_case28.py verifies evidence confirmation cannot confirm the method.
    if not claim.semantic_confirmed and contract.contract_type!=ContractType.SCOPE:
        st.info("① 근거 후보 선택 → 확정. 시스템 1순위가 자동 승인되지 않습니다.")
        candidates=claim.evidence_candidates or ([{"column":claim.column,"score":None,"reason":"기존 연결"}] if claim.column else [])
        if candidates:
            labels=[]
            for x in candidates:
                score=x.get("score")
                labels.append(f"{x.get('column','')}" + (f" · 후보점수 {score:.2f}" if isinstance(score,(int,float)) else ""))
            choice=st.radio("근거 후보",options=list(range(len(candidates))),format_func=lambda i:labels[i],key=f"evidence_choice_{claim.claim_id}")
            selected=candidates[choice]
            st.caption(f"선택 후보: {selected.get('column','')} · {selected.get('reason','시스템 의미매칭 후보')}")
            if st.button("① 선택한 근거를 확정",type="primary",key=f"evidence_confirm_{claim.claim_id}"):
                # case29 PROVENANCE CHANGE
                # FAILURE: case28 always promoted the first ranked evidence candidate when the reviewer clicked confirm.
                # RISK: clicking a confirmation button did not prove the human selected that specific evidence.
                # CHANGE: persist SELECTED and CONFIRMED for the exact radio choice before contract execution.
                rec=proposed(selected.get("column",claim.column),source="system_candidate",source_location=f"원문 #{claim.source_page or '?'}",score=selected.get("score"))
                rec.select(reviewer); emit_once("EVIDENCE_SELECTED",claim,actor="HUMAN",message=json.dumps(rec.to_dict(),ensure_ascii=False))
                rec.confirm(reviewer); claim.evidence_provenance=rec.to_dict();claim.column=rec.value;claim.semantic_confirmed=True
                emit_once("EVIDENCE_CONFIRMED",claim,actor="HUMAN",message=json.dumps(claim.evidence_provenance,ensure_ascii=False));st.rerun()
        else:
            st.warning("선택 가능한 근거 후보가 없습니다. 검증 실행을 계속 차단합니다.")

    if claim.semantic_confirmed and contract.contract_type in {ContractType.COMPARATIVE,ContractType.ASSOCIATION,ContractType.REGRESSION} and not getattr(claim,"method_confirmed",False):
        candidate_method=getattr(claim,"method_candidate","") or getattr(claim,"analysis_method","")
        st.warning(f"② 분석방법 별도 확인 필요 · 시스템 제안: {candidate_method or '미확정'}")
        st.caption("근거 확인과 분석방법 확인은 별개입니다. 논문 Methods/통계분석 절과 대조하고 필요하면 제안을 변경하세요.")
        method_options={
            ContractType.COMPARATIVE:["welch_t","independent_t","mannwhitney_u","chi_square","fisher_exact","지원되지 않는 방법"],
            ContractType.ASSOCIATION:["pearson_r","spearman_r","지원되지 않는 방법"],
            ContractType.REGRESSION:["linear_regression","logistic_regression","지원되지 않는 방법"],
        }[contract.contract_type]
        if candidate_method and candidate_method not in method_options: method_options=[candidate_method]+method_options
        default_idx=method_options.index(candidate_method) if candidate_method in method_options else 0
        chosen_method=st.selectbox("실제 사용할 분석방법",method_options,index=default_idx,key=f"method_choice_{claim.claim_id}")
        if st.button("② 선택한 분석방법을 확정",key=f"method_confirm_{claim.claim_id}"):
            rec=proposed(chosen_method,source="system_candidate" if chosen_method==candidate_method else "human_override",source_location=f"원문 #{claim.source_page or '?'}")
            rec.select(reviewer);emit_once("METHOD_SELECTED",claim,actor="HUMAN",message=json.dumps(rec.to_dict(),ensure_ascii=False))
            rec.confirm(reviewer);claim.method_provenance=rec.to_dict();claim.analysis_method=chosen_method;claim.method_confirmed=True
            emit_once("METHOD_CONFIRMED",claim,actor="HUMAN",message=json.dumps(claim.method_provenance,ensure_ascii=False));st.rerun()

    if run["state"]=="EXECUTED":
        result=run["result"]
        if contract.contract_type==ContractType.DESCRIPTIVE:
            # case27 UX CHANGE — result hero above is the single source of truth; avoid repeating the same four numbers.
            pass
        elif contract.contract_type==ContractType.ASSOCIATION:
            st.markdown(f'<div class="eg-result"><div><div class="eg-label">X</div><div class="eg-big">{contract.x}</div></div><div><div class="eg-label">Y</div><div class="eg-big">{contract.y}</div></div><div><div class="eg-label">재분석 r</div><div class="eg-big">{result.get("estimate",float("nan")):.3f}</div></div><div><div class="eg-label">p-value</div><div class="eg-big">{(next(iter(result.get('terms',{}).values())).get('p_value') if result.get('terms') else result.get('p_value',float('nan'))):.3g}</div></div></div>',unsafe_allow_html=True)
        elif contract.contract_type==ContractType.REGRESSION:
            pred=", ".join(contract.predictors) if contract.predictors else "미연결"
            st.markdown(f'<div class="eg-result"><div><div class="eg-label">Outcome</div><div class="eg-big">{contract.outcome}</div></div><div><div class="eg-label">Predictor</div><div class="eg-big">{pred}</div></div><div><div class="eg-label">Estimate</div><div class="eg-big">{(next(iter(result.get('terms',{}).values())).get('estimate') if result.get('terms') else result.get('estimate',float('nan'))):.3g}</div></div><div><div class="eg-label">p-value</div><div class="eg-big">{(next(iter(result.get('terms',{}).values())).get('p_value') if result.get('terms') else result.get('p_value',float('nan'))):.3g}</div></div></div>',unsafe_allow_html=True)
            if result.get("odds_ratio") is not None:st.caption(f"Odds ratio {result['odds_ratio']:.4g} · 95% CI {result.get('ci95_or')}")
        elif contract.contract_type==ContractType.COMPARATIVE:
            st.markdown(f'<div class="eg-result"><div><div class="eg-label">Outcome</div><div class="eg-big">{contract.outcome}</div></div><div><div class="eg-label">비교</div><div class="eg-big">{contract.group_a} ↔ {contract.group_b}</div></div><div><div class="eg-label">Effect</div><div class="eg-big">{(next(iter(result.get('terms',{}).values())).get('estimate') if result.get('terms') else result.get('estimate',float('nan'))):.3g}</div></div><div><div class="eg-label">p-value</div><div class="eg-big">{(next(iter(result.get('terms',{}).values())).get('p_value') if result.get('terms') else result.get('p_value',float('nan'))):.3g}</div></div></div>',unsafe_allow_html=True)

    if run["state"]=="EXECUTED" and contract.contract_type in {ContractType.COMPARATIVE,ContractType.ASSOCIATION,ContractType.REGRESSION}:
        diag=(run.get("result") or {}).get("diagnostics",{})
        if diag:
            with st.expander("통계 가정 진단 · 사람 검토 필요"):
                st.json(diag,expanded=True)
                st.caption("진단값은 자동 PASS 판정이 아니라 방법론 검토를 위한 근거입니다.")

    semantic_status="PASS" if claim.semantic_confirmed else "PENDING"
    method_status="BLOCKED" if not check.executable else ("APPLICABLE" if contract.contract_type==ContractType.DESCRIPTIVE else "REVIEW")
    method_title="실행 조건 부족" if not check.executable else ("기술통계 재계산 가능" if contract.contract_type==ContractType.DESCRIPTIVE else "추론방법 검토")
    if run["state"]=="BLOCKED":repro_status,repro_title="BLOCKED","재현 실행 안 함"
    elif contract.contract_type==ContractType.DESCRIPTIVE:
        s,_,_=verify_reported_claim(claim,st.session_state.df);repro_status,repro_title=("PASS","논문 수치 재현 성공") if s==Status.SUPPORTED else (("FAIL","논문 수치 재현 실패") if s==Status.CONFLICT else ("REVIEW","논문 수치 검토"))
    else:
        rg=inferential_reproduction_gate(claim,run["result"]);repro_status,repro_title=rg.status,rg.title
    ig=interpretation_gate(claim,run["result"] if run["state"]=="EXECUTED" and contract.contract_type!=ContractType.DESCRIPTIVE else None)
    st.markdown('<div class="eg-gates">'+gate_html("의미 연결",semantic_status,"확인 완료" if claim.semantic_confirmed else "사람 확인 필요")+gate_html("근거 충분성",("PASS" if check.executable else "BLOCKED"),("실행 가능" if check.executable else "실행 보류"))+gate_html("재현 검증",repro_status,repro_title)+gate_html("해석 검토",ig.status,ig.title)+'</div>',unsafe_allow_html=True)

    with st.expander("근거 및 계산 과정 보기"):
        st.markdown("**검토자용 요약** · 아래 후보/계약은 실행 근거의 출처를 추적하기 위한 정보입니다.")
        st.caption("검증에 사용된 데이터·계약·후보 근거입니다. 개발자/감사 정보는 아래 JSON에서 확인할 수 있습니다.")
        with st.expander("개발자·감사 정보",expanded=False):
            st.json(contract.to_dict(),expanded=False)
        st.download_button("개발자·감사용 검증 계약 JSON",json.dumps(contract.to_dict(),ensure_ascii=False,indent=2,default=str).encode(),file_name=f"{claim.claim_id}_v{APP_VERSION.split('.')[0]}_contract.json",mime="application/json")
        st.caption(f"Dataset {st.session_state.dataset_name} · SHA-256 {st.session_state.dataset_hash[:20]}… · {ENGINE_VERSION}")
        if claim.evidence_candidates:st.dataframe(pd.DataFrame(claim.evidence_candidates),hide_index=True,width="stretch")

    # Human workflow is retained for descriptive numeric conflicts; inferential claims remain review-first.
    if run["state"]=="EXECUTED" and contract.contract_type==ContractType.DESCRIPTIVE:
        s,reason,calc=verify(claim,st.session_state.df)
        if s==Status.CONFLICT and claim.status!=Status.VALIDATED:
            with st.expander("사람 정정안 → 별도 재검증",expanded=True):
                st.caption("논문의 원래 보고값과 재현 실패 판정은 보존됩니다. 정정안은 별도 사람 판단입니다.")
                newv=st.number_input("정정안 수치",value=float(calc),key=f"new_{claim.claim_id}");note=st.text_input("정정 사유",key=f"note_{claim.claim_id}")
                if st.button("정정안 재검증",key=f"rv_{claim.claim_id}",disabled=not note.strip()):
                    bs,bv=claim.status,claim.current_value;result=revise_and_reverify(claim,st.session_state.df,newv,note);audit("REVISE_VALUE",claim,bs.value,bs.value,note,bv,claim.current_value,calc,"HUMAN");record_event("VALUE_REVISED",claim_id=claim.claim_id,actor="HUMAN",contract_type=contract.contract_type.value);audit("REVERIFY",claim,bs.value,result["status"].value,result["reason"],claim.current_value,claim.current_value,result["calc"]);record_event("REVERIFIED",claim_id=claim.claim_id,contract_type=contract.contract_type.value);st.rerun()
        elif s==Status.SUPPORTED and claim.status!=Status.VALIDATED:
            st.markdown('<div class="eg-ok">정정안 재검증 통과 · 논문 원문의 재현 결과는 위에서 별도로 확인하세요.</div>',unsafe_allow_html=True)
            with st.expander("사람 판단 승인"):
                note=st.text_input("승인 사유",key=f"approve_note_{claim.claim_id}")
                if not can(reviewer_role,"approve"):
                    st.info("최종 승인은 APPROVER 또는 ADMIN 역할이 필요합니다. 검토와 승인을 분리해 감사 가능성을 보장합니다.")
                if st.button("정정안 승인" if claim.revision_count else "원문 재현 승인",type="primary",key=f"approve_{claim.claim_id}",disabled=(not note.strip()) or (not can(reviewer_role,"approve"))):
                    # [수정: 전문가2·3·6] 2026-09-28 case81: 최신 실행에 영속 승인 성공한 경우에만 화면 승인.
                    try:
                        before=claim.status
                        _,reason,fc,approved=approve_reverified(claim,st.session_state.df,note,csv_bytes=st.session_state.csv_bytes,audit_store=st.session_state.audit_store,dataset_hash=st.session_state.dataset_hash,actor_id=reviewer,role=reviewer_role,app_version=APP_VERSION,engine_version=ENGINE_VERSION)
                        if approved:
                            audit("APPROVE",claim,before.value,claim.status.value,note,claim.current_value,claim.current_value,fc,"HUMAN")
                            st.rerun()
                        else: st.warning(reason)
                    except (ValueError,PermissionError) as exc:
                        st.error(f'승인 차단: {exc}')
    elif contract.contract_type==ContractType.SCOPE:
        st.warning("다음 단계: 아래에서 검증 지표·하위집단 기준·평가 시점을 확인하면 같은 Claim을 다시 평가합니다.")
        # case26 RESOLUTION WORKFLOW
        # FAILURE: case25 explained why a Scope claim was blocked but provided no path to resolve it.
        # WHY: fail-closed must be paired with a human-controlled completion workflow.
        with st.expander("① 차단 해제 조건 입력 → ② 계약 확정 → ③ 다시 평가",expanded=True):
            numeric_cols=list(st.session_state.df.select_dtypes(include='number').columns)
            endpoint_options=[""]+numeric_cols
            candidate=getattr(contract,'endpoint_candidate','') or ""
            ep_index=endpoint_options.index(candidate) if candidate in endpoint_options else 0
            endpoint=st.selectbox("검증 지표",endpoint_options,index=ep_index,key=f"scope_ep_{claim.claim_id}")
            subgroup_options=[c for c in st.session_state.df.columns if c!=endpoint]
            dims=st.multiselect("하위집단 기준",subgroup_options,default=getattr(claim,'scope_subgroup_dimensions',[]),key=f"scope_dims_{claim.claim_id}")
            time_col=st.selectbox("평가 시점 변수",[""]+subgroup_options,key=f"scope_timecol_{claim.claim_id}")
            tp=[]
            if time_col:
                vals=[str(x) for x in st.session_state.df[time_col].dropna().unique().tolist()]
                tp=st.multiselect("검증할 평가 시점",vals,default=vals,key=f"scope_tp_{claim.claim_id}")
            if st.button("검증 조건 확정 후 다시 평가",type="primary",key=f"scope_confirm_{claim.claim_id}"):
                claim.scope_endpoint=endpoint;claim.scope_subgroup_dimensions=dims;claim.scope_timepoints=tp;claim.scope_confirmed=bool(endpoint and dims and tp)
                record_event("SCOPE_SPEC_CONFIRMED",claim_id=claim.claim_id,actor="HUMAN",contract_type=contract.contract_type.value,detail=json.dumps({'endpoint':endpoint,'subgroups':dims,'timepoints':tp},ensure_ascii=False))
                st.rerun()
    elif run["state"]=="EXECUTED":
        st.info("추론통계 Claim은 자동 승인하지 않습니다. 효과크기·신뢰구간·가정·다중비교·과학적 해석을 사람이 검토해야 합니다.")

st.markdown("### 검증 계보 · Audit Trail")
claim_events=st.session_state.audit_store.for_claim(claim.claim_id,dataset_hash=st.session_state.dataset_hash)
if claim_events:
    st.caption(f"{claim.claim_id}에서 AI/규칙이 무엇을 제안했고 사람이 무엇을 확정했는지 시간순으로 추적합니다.")
    for e in claim_events:
        icon="✓" if e["event"] in {"EVIDENCE_CONFIRMED","METHOD_CONFIRMED","ANALYSIS_POLICY_CONFIRMED","APPROVED"} else ("⊘" if e["event"]=="CONTRACT_BLOCKED" else "•")
        detail=activity_detail(e.get("detail") or "")[:180]
        st.markdown(f"**{icon} {e.get('label', e['event'])}**  · `{e.get('actor_id') or e['actor']}`" + (f"  \n{detail}" if detail else ""))
else:
    st.caption("이 Claim의 검증 계보가 아직 없습니다.")
executions=st.session_state.audit_store.executions_for_claim(claim.claim_id,dataset_hash=st.session_state.dataset_hash)
if executions:
    with st.expander(f"재현 실행 원장 {len(executions)}건 · 변경 불가 snapshot"):
        for ex in executions:
            st.markdown(f"**{ex.get('attempt_id', ex.get('execution_id',''))}**  \nContract `{ex['contract_hash'][:16]}…` · Dataset `{ex['dataset_hash'][:16]}…` · Engine `{ex['engine_version']}`")
            st.download_button("활동 시각을 뺀 실행 기록 JSON",json.dumps({"view":"activity_times_removed_not_original_ledger", "record":activity_view(ex)},ensure_ascii=False,indent=2).encode(),file_name=f"{ex.get('attempt_id', ex.get('execution_id',''))}.json",mime="application/json",key=f"dl_{ex.get('attempt_id', ex.get('execution_id',''))}")
            st.caption("읽기용 사본입니다. 원본 감사 원장이나 독립 재실행 묶음으로 사용할 수 없습니다.")
rows=[]  # Legacy unscoped rows are retained on disk, not mixed across documents in the UI.
if rows:
    with st.expander(f"기존 변경 이력 {len(rows)}건 · 개발자/감사용"):
        st.dataframe(pd.DataFrame(rows,columns=["시각","Claim ID","Actor","Action","이전 상태","이후 상태","이전 값","이후 값","근거 값","사유"]),width="stretch")






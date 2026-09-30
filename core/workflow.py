"""Reusable human-review workflow for Evidence Gate case17.

case17 CHANGE:
Revision, deterministic re-verification, and final human approval are deliberately
separate actions. This prevents one click from both changing scientific content
and approving it, and makes the audit trail easier to defend.
"""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
from .models import Status
from .provenance import dataframe_hash
from .verifier import verify, refresh_reported_status, auto_verify
from .rbac import require_permission


def revise_and_reverify(claim, df, new_value: float, reason: str):
    """Apply a human revision and stop at SUPPORTED/CONFLICT after re-verification."""
    if not reason.strip():
        raise ValueError("감사 추적을 위해 수정 사유가 필요합니다.")
    before_status, before_value = claim.status, claim.current_value
    claim.semantic_confirmed = True
    refresh_reported_status(claim,df)
    claim.revise(new_value, reason)
    status, verify_reason, calc = verify(claim, df)
    claim.status, claim.reason = status, verify_reason
    claim.amendment_status, claim.amendment_reason = status, verify_reason
    return {
        "before_status": before_status, "before_value": before_value,
        "status": status, "reason": verify_reason, "calc": calc,
    }


def approve_reverified(claim, df, reason: str, *, csv_bytes: bytes | None = None,
                       audit_store=None,dataset_hash='',actor_id='',role=None,app_version='',engine_version=''):
    """Approve only a claim that still deterministically verifies as SUPPORTED."""
    # [수정: 가상 검토 역할2·3·6] 2026-09-28 case81: 실제 앱 승인은 최신 실행·데이터·서명에 결속하고 역할을 API에서도 검사; 기존 순수 함수 호출 호환.
    if role is not None or audit_store is not None:
        require_permission(role,'approve')
    if not reason.strip():
        raise ValueError("최종 승인 사유가 필요합니다.")
    if audit_store is not None:
        if not actor_id.strip() or not dataset_hash:
            raise ValueError('승인자와 데이터셋 식별자가 필요합니다.')
        if not audit_store.verify_audit_chain():
            raise ValueError('감사 원장 검증 실패: 승인할 수 없습니다.')
        # 실패한 영속 기록이 화면의 승인 상태를 바꾸지 않도록 별도 후보를 검증.
        candidate=deepcopy(claim)
        candidate_result=approve_reverified(candidate,df,reason,csv_bytes=csv_bytes)
        if not candidate_result[3]:
            claim.__dict__.update(candidate.__dict__)
            return candidate_result
        with audit_store.con:
            audit_store.con.execute('BEGIN IMMEDIATE')
            attempts=audit_store.attempts_for_claim(claim.claim_id,dataset_hash)
            if not attempts:
                raise ValueError('승인할 최신 영속 실행이 없습니다.')
            latest=attempts[-1];snapshot=json.loads(latest['claim_json'])
            if (not isinstance(snapshot,dict) or snapshot.get('verification_signature')!=candidate.verification_signature()
                or snapshot.get('dataframe_hash')!=dataframe_hash(df)
                or latest['app_version']!=app_version or latest['engine_version']!=engine_version
                or latest['nondeterministic']):
                raise ValueError('최신 실행과 현재 검증 입력이 다릅니다. 다시 실행한 뒤 승인하세요.')
            detail=json.dumps({'reason':reason,'verification_signature':candidate.validated_signature,
                'data_hash':candidate.validated_data_hash,'attempt_id':latest['attempt_id'],
                'result_hash':latest['result_hash']},ensure_ascii=False,sort_keys=True)
            audit_store.append(claim.claim_id,'APPROVED',actor='HUMAN',actor_id=actor_id,
                detail=detail,source=latest['attempt_id'],app_version=app_version,
                engine_version=engine_version,dataset_hash=dataset_hash)
        claim.__dict__.update(candidate.__dict__)
        return candidate_result
    claim.semantic_confirmed = True
    refresh_reported_status(claim,df)
    status, verify_reason, calc = verify(claim, df)
    if status != Status.SUPPORTED:
        claim.status, claim.reason = status, verify_reason
        if claim.revision_count:claim.amendment_status,claim.amendment_reason=status,verify_reason
        return status, verify_reason, calc, False
    claim.status, claim.reason = status, verify_reason
    claim.validate(reason)
    # [수정: 전문가7] 2026-09-25 case58
    # 무엇을: 승인 당시 데이터 지문 보존 / 왜: 같은 행 수의 값 교체도 새 승인 대상 / 검증: tests/test_case58_approval.py.
    claim.validated_data_hash = sha256(csv_bytes).hexdigest() if csv_bytes is not None else dataframe_hash(df)
    return Status.VALIDATED, reason, calc, True


# [작성: 가상 검토 역할2·6] 2026-09-28 case81: 화면 승인도 원장의 최신 승인/실행과 대조; 재실행·입력 변경·과거 미결속 승인은 별도 취소 사건으로 보존.
def refresh_audited_approval(claim,df,*,audit_store,dataset_hash,csv_bytes=None,app_version='',engine_version=''):
    if claim.status!=Status.VALIDATED:
        return auto_verify(claim,df,csv_bytes=csv_bytes)
    approval=audit_store.approval_state(claim.claim_id,dataset_hash)
    attempts=audit_store.attempts_for_claim(claim.claim_id,dataset_hash)
    latest=attempts[-1] if attempts else None
    current=bool(approval and approval['event']=='APPROVED' and latest and approval['source']==latest['attempt_id'])
    current=current and audit_store.verify_audit_chain()
    if latest and app_version:
        current=current and latest['app_version']==app_version and latest['engine_version']==engine_version
    try:
        detail=json.loads(approval['detail']) if approval else {}
        current=current and isinstance(detail,dict) and detail.get('verification_signature')==claim.validated_signature and detail.get('result_hash')==latest['result_hash']
    except (ValueError,TypeError):
        current=False
    result=auto_verify(claim,df,csv_bytes=csv_bytes)
    if not current and claim.status==Status.VALIDATED:
        status,reason,calc=verify(claim,df)
        claim.status=status;claim.reason='최신 실행에 결속된 승인이 없어 승인이 해제되었습니다. '+reason
        if claim.revision_count:claim.amendment_status=status;claim.amendment_reason=claim.reason
        result=(status,claim.reason,calc,True)
    if claim.status!=Status.VALIDATED and (not approval or approval['event']!='APPROVAL_REVOKED'):
        audit_store.append(claim.claim_id,'APPROVAL_REVOKED',detail=claim.reason,
            source=approval['source'] if approval else '',dataset_hash=dataset_hash,
            app_version=app_version,engine_version=engine_version)
    return result


# Backward-compatible wrappers retained for reuse by older tests/integrations.
def revise_reverify_approve(claim, df, new_value: float, reason: str):
    result = revise_and_reverify(claim, df, new_value, reason)
    if result["status"] == Status.SUPPORTED:
        approve_reverified(claim, df, reason)
    result["approved"] = claim.status == Status.VALIDATED
    return result


def approve_supported(claim, df, reason: str):
    return approve_reverified(claim, df, reason)

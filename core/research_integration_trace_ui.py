"""Record existing integration observations; never execute tools or approve.

Recorded-at times belong to SQLite checkpoints. Observed-at times come only from
the original receipt. A recorded skipped lookup is not a successful lookup.
"""
# [작성: 0 이영] 2026-10-01 04:15 KST — 웹 영수증을 같은 실행에 결속하되 과거 관측·미수행·현재 기록을 구분한다.
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit
import uuid

from . import research_integration_intake as intake
from .research_integration_runs import IntegrationRunStore, STAGES, fingerprint
from evidence_gate.spec import spec_sha256, validate

TRACE_FIELDS = {'observed_at_kst', 'observation_kind', 'http_status', 'elapsed_ms', 'usage_unknown'}
BASE_BINDING_KEYS = ('data_sha256', 'record_sha256', 'paper_context_sha256', 'spec_sha256', 'reference_sha256', 'engine_source_revision')
LIMITS = ['OBSERVATION_RECORDING_ONLY_NO_TOOL_EXECUTION', 'METADATA_ONLY_REACQUIRE_BYTES_AND_RECHECK_SHA256',
          'SKIPPED_LOOKUPS_ARE_NOT_SUCCESSFUL_LOOKUPS', 'ARITHMETIC_MATCH_IS_NOT_SOURCE_SEMANTIC_VERIFICATION',
          'OBSERVED_APPROVAL_RECORD_IS_NOT_INDEPENDENT_PROOF_OF_A_REAL_HUMAN_EVENT',
          'CANDIDATE_OR_AI_PROPOSAL_OBSERVATION_IS_NOT_COMPLETED_AI_VERIFICATION']


def _hash(value):
    intake._public(value)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(raw.encode('utf8')) > 128 * 1024:
        raise ValueError('TRACE_METADATA_TOO_LARGE')
    return hashlib.sha256(raw.encode('utf8')).hexdigest()


def _observed_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone(timedelta(hours=9))).isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 300:
        return None
    parts = urlsplit(value)
    return value if parts.scheme == 'https' and parts.hostname and not any((parts.username, parts.password, parts.query, parts.fragment)) else None


def _code(value, fallback='OBSERVATION_UNAVAILABLE'):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', value) else fallback


def _stage(name, kind, status, *, receipt=None, stable=None, available=True, extra=None):
    receipt = receipt if isinstance(receipt, dict) else {}
    telemetry = receipt.get('telemetry') if isinstance(receipt.get('telemetry'), dict) else {}
    elapsed = telemetry.get('elapsed_ms', receipt.get('elapsed_ms'))
    elapsed = int(round(elapsed)) if type(elapsed) in (int, float) and 0 <= elapsed <= 36000000 else None
    http = receipt.get('http_status')
    http = http if type(http) is int and 100 <= http <= 599 else None
    observed = receipt.get('retrieved_at_kst') or receipt.get('observed_at_kst') or receipt.get('calculated_at_kst') or receipt.get('approved_at_kst')
    metadata = dict(status=status, observation_kind=kind, observed_at_kst=_observed_time(observed),
                    http_status=http, elapsed_ms=elapsed, usage_unknown=True)
    provider = receipt.get('provider')
    if isinstance(provider, str) and provider:
        metadata['provider'] = provider[:100]
    url = _safe_url(receipt.get('source_url'))
    if url:
        metadata['url'] = url
    if extra:
        metadata.update(extra)
    fingerprint(metadata)
    return dict(stage=name, available=available, input_sha256=_hash(stable if stable is not None else metadata),
                output_metadata=metadata)


def snapshot(state, actor):
    """Pure public summary; recheck current bytes, receipt, spec and engine first."""
    try:
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 128 or not isinstance(state, dict):
            raise ValueError('TRACE_ACTOR_OR_STATE_INVALID')
        actor_sha = fingerprint(actor)
        downloaded = state.get('download') or {}
        receipt, raw, spec = downloaded.get('receipt'), downloaded.get('raw_bytes'), state.get('spec')
        if not isinstance(receipt, dict) or not isinstance(raw, bytes) or not isinstance(spec, dict):
            return dict(success=False, status='WAITING_FOR_BOUND_INPUTS', error=None, stages=[], limitations=list(LIMITS))
        intake._current_receipt(raw, receipt, state.get('record'))
        paper = intake._paper_context(state.get('paper_context'))
        intake._public(spec)
        source_receipt, source_bytes = state.get('source_receipt'), state.get('source_bytes')
        # [수정: 0 이영] 2026-10-01 04:35 KST — 같은 spec이라도 원문 바이트·영수증·후보 묶음·조건대조가 달라지면 이전 실행 재개를 차단한다.
        source_actual = None
        if source_bytes is not None:
            from .research_integration_candidates import _source_state
            source_checked, _ = _source_state(source_bytes, source_receipt, paper)
            source_actual = source_checked['actual_sha256']
            if paper.get('source_sha256') != source_actual:
                raise ValueError('TRACE_SOURCE_DECLARATION_SHA_MISMATCH')
        revision = intake.source_revision()
        bindings = dict(data_sha256=hashlib.sha256(raw).hexdigest(), record_sha256=receipt['record_context_sha256'],
                        paper_context_sha256=_hash(paper), spec_sha256=spec_sha256(spec),
                        reference_sha256=_hash(state.get('reference_ids')), engine_source_revision=revision,
                        source_location_sha256=_hash(state.get('source_location', spec.get('source_location'))),
                        source_receipt_sha256=_hash(source_receipt), source_bytes_sha256=source_actual,
                        candidate_set_sha256=_hash(state.get('candidate_set')),
                        source_agreement_sha256=_hash(state.get('source_agreement')))
        if spec.get('data_fingerprint') != bindings['data_sha256']:
            raise ValueError('TRACE_STALE_SPEC_DATA')
        root_sha = fingerprint(bindings)
        rows = []
        for name, response in [('search', state.get('search')), ('relations', state.get('relations') or state.get('relation_response'))]:
            if isinstance(response, dict):
                summary = {key: response.get(key) for key in ('provider', 'status', 'response_sha256', 'error')}
                summary['count'] = len(response.get('items', [])) if isinstance(response.get('items'), list) else 0
                rows.append(_stage(name, 'OBSERVED_PROVIDER_RECEIPT', _code(response.get('status'), 'PROVIDER_RESPONSE_RECORDED'),
                                   receipt=response, stable=summary, extra={'count': summary['count']}))
            else:
                rows.append(_stage(name, 'NOT_REQUESTED', 'NOT_REQUESTED_USER_SUPPLIED_SOURCE', stable={'stage': name, 'not_requested': True}))
        capture = receipt.get('source_capture')
        source_registered = receipt.get('provider') == 'registered' and isinstance(capture, dict)
        jats = state.get('jats') if isinstance(state.get('jats'), dict) else {}
        jats_receipt = jats.get('public_source_receipt') if isinstance(jats.get('public_source_receipt'), dict) else {}
        licensed_jats = False
        if source_actual and source_receipt.get('source_kind') == 'LICENSED_JATS_RECEIVED':
            from .research_integration_relations import _CC
            licensed_jats = bool(jats.get('ok') is True and jats.get('source_identity_checked') is True
                                 and jats_receipt.get('schema') == 'research_public_source_receipt/1'
                                 and jats_receipt.get('type') == 'JATS_XML'
                                 and jats_receipt.get('sha256') == source_actual
                                 and jats_receipt.get('url') == paper.get('source_url')
                                 and jats_receipt.get('doi') == paper.get('paper_doi')
                                 and isinstance(jats_receipt.get('license'), str) and _CC.fullmatch(jats_receipt['license']))
        source_kind = 'OBSERVED_LICENSED_JATS_RECEIPT' if licensed_jats else 'OBSERVED_SOURCE_BYTES_RECEIPT' if source_actual else 'OBSERVED_REGISTERED_PUBLIC_DERIVATIVE' if source_registered else 'USER_DECLARATION'
        source_status = 'LICENSED_JATS_CURRENT_SHA_RECHECKED' if licensed_jats else 'SOURCE_BYTES_CURRENT_SHA_RECHECKED' if source_actual else 'REGISTERED_PUBLIC_DERIVATIVE_CONFIRMED' if source_registered else 'USER_DECLARED_SOURCE_NOT_ACQUIRED'
        rows.append(_stage('original', source_kind, source_status,
                           receipt={'source_url': jats_receipt.get('url'), 'observed_at_kst': jats_receipt.get('received_at')} if licensed_jats else None,
                           stable={'paper': bindings['paper_context_sha256'], 'capture': capture, 'source_receipt': bindings['source_receipt_sha256'], 'source_bytes': source_actual},
                           extra={'source_sha256': paper.get('source_sha256')}))
        rows.append(_stage('file', 'OBSERVED_DOWNLOAD_RECEIPT', 'BYTES_RECHECKED_RECEIPT_RECORDED',
                           receipt=dict(receipt.get('download') or {}, provider=receipt.get('provider')),
                           stable={'data': bindings['data_sha256'], 'record': bindings['record_sha256']},
                           extra={'data_sha256': bindings['data_sha256'], 'record_sha256': bindings['record_sha256'],
                                  'receipt_sha256': _hash(receipt), 'byte_count': len(raw)}))
        confirmed = state.get('conditions_confirmed') is True
        ready = validate(spec)['ready'] and bool(spec.get('denominator')) and bool(spec.get('unit')) and spec.get('missing_policy') is not None and spec.get('missing_tokens') is not None
        rows.append(_stage('conditions', 'USER_CONFIRMATION_DECLARED', 'CONDITIONS_CONFIRMATION_RECORDED' if confirmed and ready else 'CONDITIONS_NOT_READY',
                           stable={'spec': bindings['spec_sha256'], 'confirmed': confirmed}, available=confirmed and ready,
                           extra={'spec_sha256': bindings['spec_sha256'], 'conditions_confirmed': confirmed}))
        report = state.get('report')
        report_available = isinstance(report, dict)
        if report_available and report.get('success'):
            report_bindings = report.get('bindings')
            if (not intake._intact(report) or not isinstance(report_bindings, dict)
                    or any(report_bindings.get(key) != bindings[key] for key in BASE_BINDING_KEYS)):
                raise ValueError('TRACE_STALE_REPORT')
        calculation = report.get('calculation') if report_available else None
        calc_stable = {'bindings': report.get('bindings'), 'calculation': calculation} if report_available else None
        rows.append(_stage('calculation', 'OBSERVED_CALCULATION_RECEIPT', 'CALCULATION_RECEIPT_RECORDED' if report_available and report.get('success') else 'OBSERVED_BLOCKED' if report_available else 'CALCULATION_NOT_OBSERVED',
                           receipt=report, stable=calc_stable, available=report_available,
                           extra={'receipt_sha256': _hash(calc_stable) if report_available else None,
                                  'code': _code(report.get('error'), 'ARITHMETIC_SCOPE_ONLY') if report_available else 'NOT_OBSERVED'}))
        approval = report.get('human_approval') if report_available else None
        approval_observed = bool(report_available and report.get('approved') is True and isinstance(approval, dict) and approval.get('active') is True and approval.get('bindings') == report.get('bindings'))
        rows.append(_stage('human_review', 'OBSERVED_APPROVAL_RECORD', 'BOUND_APPROVAL_RECORD_OBSERVED' if approval_observed else 'HUMAN_REVIEW_NOT_OBSERVED',
                           receipt=approval, stable=approval, available=approval_observed,
                           extra={'approval_receipt_sha256': _hash(approval) if approval_observed else None}))
        if intake.source_revision() != revision:
            raise ValueError('TRACE_SOURCE_CHANGED_DURING_SNAPSHOT')
        return dict(success=True, status='OBSERVATIONS_READY', actor_sha256=actor_sha, bindings=bindings,
                    root_input_sha256=root_sha, stages=rows, limitations=list(LIMITS), approved=False,
                    tool_executed=False, verified=False)
    except Exception as exc:
        return dict(success=False, status='BLOCKED', error=_code(str(exc), 'TRACE_INPUT_INVALID'), stages=[], limitations=list(LIMITS))


def persist_snapshot(state, actor, *, store, trace=None):
    """Append available observations in order. Existing completed stages are immutable."""
    observed = snapshot(state, actor)
    if not observed['success']:
        return observed
    try:
        if trace is not None:
            if trace.get('actor_sha256') != observed['actor_sha256']:
                raise ValueError('TRACE_ACTOR_CHANGED')
            run = store.get(actor, trace['run_id'])
            if run['root_input_sha256'] != observed['root_input_sha256']:
                raise ValueError('TRACE_ROOT_CHANGED_START_NEW_RUN')
        else:
            run = store.start(actor, observed['bindings'], idempotency_key='ui-observation-' + uuid.uuid4().hex)
        status = 'RECORDED_OBSERVATIONS'
        for row in observed['stages']:
            previous = [a for a in run['attempts'] if a['stage'] == row['stage'] and a['status'] == 'SUCCEEDED']
            if previous:
                if previous[-1]['input_sha256'] != row['input_sha256']:
                    raise ValueError('TRACE_OBSERVATION_CHANGED_START_NEW_RUN')
                continue
            if not row['available']:
                status = 'WAITING_FOR_' + row['stage'].upper()
                break
            if run['next_stage'] != row['stage']:
                raise ValueError('TRACE_STAGE_MISMATCH')
            active = [a for a in run['attempts'] if a['status'] == 'RUNNING']
            if active:
                status = 'EXPLICIT_RESUME_REQUIRED'
                break
            generation = 1 + sum(a['stage'] == row['stage'] for a in run['attempts'])
            claimed = store.begin_stage(actor, run['run_id'], row['stage'], input_sha256=row['input_sha256'],
                                        root_input_sha256=observed['root_input_sha256'], expected_revision=run['revision'],
                                        idempotency_key='observed-' + row['stage'] + '-' + str(generation) + '-' + row['input_sha256'])
            if not claimed['execute']:
                raise ValueError('TRACE_EXPLICIT_RESUME_REQUIRED')
            run = store.finish_stage(actor, run['run_id'], attempt_id=claimed['attempt']['attempt_id'],
                                     input_sha256=row['input_sha256'], root_input_sha256=observed['root_input_sha256'],
                                     expected_revision=claimed['revision'], output_metadata=row['output_metadata'],
                                     next_action='DONE' if row['stage'] == 'human_review' else 'REVIEW' if row['stage'] == 'calculation' else 'CONTINUE')
            if row['stage'] == 'calculation' and row['output_metadata']['status'] == 'OBSERVED_BLOCKED':
                status = 'BLOCKED_OBSERVATION_RECORDED'
                break
        return dict(success=True, status=status, run_id=run['run_id'], revision=run['revision'],
                    actor_sha256=observed['actor_sha256'], run=run, approved=False, verified=False,
                    tool_executed=False, limitations=list(LIMITS))
    except Exception as exc:
        failed = dict(success=False, status='BLOCKED', error=_code(str(exc), 'TRACE_RECORDING_FAILED'),
                      run_id=run['run_id'] if 'run' in locals() else None, limitations=list(LIMITS))
        if 'run' in locals():
            try:
                current = store.get(actor, run['run_id'])
                failed.update(revision=current['revision'], actor_sha256=observed['actor_sha256'], run=current)
            except Exception:
                pass
        return failed


def resume_snapshot(state, actor, *, store, trace):
    observed = snapshot(state, actor)
    if not observed['success']:
        return observed
    try:
        if trace.get('actor_sha256') != observed['actor_sha256']:
            raise ValueError('TRACE_ACTOR_CHANGED')
        run = store.get(actor, trace['run_id'])
        if run['root_input_sha256'] != observed['root_input_sha256']:
            raise ValueError('TRACE_ROOT_CHANGED_START_NEW_RUN')
        attempts = [a for a in run['attempts'] if a['stage'] == run['next_stage']]
        stage_input = next((s['input_sha256'] for s in observed['stages'] if s['stage'] == run['next_stage']), run['root_input_sha256'])
        if not attempts:
            stage_input = run['root_input_sha256']
        resumed = store.resume(actor, run['run_id'], root_input_sha256=observed['root_input_sha256'],
                               input_sha256=stage_input, expected_revision=trace['revision'])
        return dict(success=True, status='RESUMED_METADATA_ONLY', run_id=resumed['run_id'], revision=resumed['revision'],
                    actor_sha256=observed['actor_sha256'], run=resumed, approved=False, verified=False,
                    tool_executed=False, limitations=list(LIMITS))
    except Exception as exc:
        return dict(success=False, status='BLOCKED', error=_code(str(exc), 'TRACE_RESUME_BLOCKED'), limitations=list(LIMITS))


def render_trace(state, actor):
    """Idle rendering reads the last summary only; verification/writes are explicit."""
    import streamlit as st
    with st.expander('실행 영수증과 재개 기록'):
        st.caption('기존 관측을 기록합니다. 미수행 조회와 원문 선언은 취득 성공이 아니며, 기록만으로 계산·승인하지 않습니다.')
        # [수정: 0 이영] 2026-10-01 05:10 KST — 펼침 여부와 무관한 Streamlit 리런에서 전체 소스·자료 지문을 재산출하지 않는다. 명시 확인과 저장/재개에서는 실제 바이트·엔진·CAS 검사를 유지한다.
        if st.button('현재 실행 지문 확인', key='ri_trace_check'):
            observed = snapshot(state, actor)
            state['_integration_trace_summary'] = {
                'checked_at_kst': datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),
                'error': observed.get('error'), 'approved': False, 'verified': False,
                'rows': [{'단계': r['stage'], '관측 범위': r['output_metadata']['observation_kind'],
                          '상태': r['output_metadata']['status'], '원 관측 시각': r['output_metadata']['observed_at_kst']}
                         for r in observed.get('stages', [])]}
        summary = state.get('_integration_trace_summary')
        if isinstance(summary, dict):
            st.caption('마지막 확인 관측 · ' + str(summary.get('checked_at_kst', '시각 미확인')) + ' · 현재 입력의 재검사·승인 상태가 아닙니다.')
            if summary.get('rows'):
                st.dataframe(summary['rows'], hide_index=True, use_container_width=True)
            if summary.get('error'):
                st.warning(summary['error'])
        else:
            st.caption('현재 실행 지문 확인을 누르면 원 관측 범위를 표시합니다. 저장·재개는 누른 시점의 실제 입력을 다시 검사합니다.')
        prior = state.get('_integration_trace')
        action = st.button('현재 관측 영수증 기록', key='ri_trace_persist')
        resume = st.button('중단 기록 재개', key='ri_trace_resume', disabled=not prior or not prior.get('run_id'))
        new_run = st.button('변경된 입력으로 새 실행 기록', key='ri_trace_new_run')
        if action or resume or new_run:
            store = IntegrationRunStore()
            try:
                state['_integration_trace'] = resume_snapshot(state, actor, store=store, trace=prior) if resume else persist_snapshot(state, actor, store=store, trace=None if new_run else prior if prior and prior.get('run_id') else None)
                if new_run and prior and prior.get('run_id'):
                    state['_integration_trace_previous_ids'] = (state.get('_integration_trace_previous_ids', []) + [prior['run_id']])[-10:]
            finally:
                store.close()
        current = state.get('_integration_trace')
        if current:
            st.caption('run_id: ' + str(current.get('run_id', '미생성')) + ' · ' + current['status'])
            if current.get('error'):
                st.warning(current['error'])

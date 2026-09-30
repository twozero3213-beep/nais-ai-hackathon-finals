"""One explicitly requested tool from a validated proposal; no agent loop or approval.

``receipt`` is a bounded public observation. ``state_patch`` is session-internal:
its download may contain CSV bytes and must never be rendered or audit-logged.
Proposal hashes detect stale/tampered inputs; they are not digital signatures.
"""
# [작성: 0 이영 · Codex] 2026-10-01 04:57 KST — 현재 입력과 명시 선택을 다시 대조하여 수동 도구 한 번만 실행한다. 합성 모의 시험으로 동의·조건·늦은 결과 경계를 검증하며 실제 API 호출은 하지 않는다.
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import re
from time import perf_counter

from core import repository_extensions
from core import research_integration_candidates as candidates
from core import research_integration_intake as intake
from core import research_integration_proposals as proposals
from core import research_integration_router as router
from evidence_gate.spec import validate

SCHEMA = 'research-integration-action/1'
MAX_METADATA_BYTES = 256 * 1024
GUIDES = {'repository_record': 'REVIEW_RECORD_AND_SELECT_FILE',
          'acquisition': 'REVIEW_SOURCE_AND_CONFIRM_CONDITIONS',
          'verify_download': 'HUMAN_REVIEW_REQUIRED',
          'manual_source_review': 'MANUAL_SOURCE_REVIEW', 'stop': 'STOP'}


class ActionError(ValueError):
    pass


def _now():
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='milliseconds')


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _digest(value):
    raw = proposals._canonical(value).encode('utf-8')
    if len(raw) > MAX_METADATA_BYTES:
        raise ActionError('ACTION_METADATA_TOO_LARGE')
    return hashlib.sha256(raw).hexdigest()


def _bytes_sha(value):
    if value is None:
        return None
    if not isinstance(value, bytes) or not 0 < len(value) <= intake.MAX_BYTES:
        raise ActionError('ACTION_BYTES_INVALID')
    return hashlib.sha256(value).hexdigest()


def _snapshot(state):
    """Exactly the existing integration UI's propose_conditions input contract."""
    location = state.get('source_location', {})
    paper = state.get('paper_context', {})
    download = state.get('download', {})
    if not isinstance(location, dict) or not isinstance(paper, dict) or not isinstance(download, dict):
        raise ActionError('CURRENT_PROPOSAL_INPUT_REQUIRED')
    received = download.get('receipt', {})
    if not isinstance(received, dict):
        raise ActionError('CURRENT_PROPOSAL_INPUT_REQUIRED')
    excerpt = location.get('quote', '')
    if not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt.encode('utf-8')) > proposals.MAX_EXCERPT_BYTES:
        raise ActionError('CURRENT_PROPOSAL_INPUT_REQUIRED')
    context = {**paper, 'source_id': location.get('source_id'), 'source_location': deepcopy(location)}
    metadata = {key: received.get(key) for key in ('provider', 'actual_sha256', 'actual_size', 'license_policy')}
    tools = proposals._tools(state.get('proposal_allowed_tools'))
    value = {'excerpt': excerpt, 'paper_context': context, 'dataset_metadata': metadata, 'allowed_tools': list(tools)}
    proposals._public(value)
    if len(proposals._canonical([context, metadata]).encode('utf-8')) > proposals.MAX_CONTEXT_BYTES:
        raise ActionError('CURRENT_PROPOSAL_INPUT_TOO_LARGE')
    return value, tools


def _validated(proposal, state):
    if not isinstance(proposal, dict) or proposal.get('success') is not True or proposal.get('status') != 'PROPOSED':
        raise ActionError('SUCCESSFUL_MODEL_PROPOSAL_REQUIRED')
    observed = proposal.get('call_observation')
    usage = proposal.get('usage')
    if (not isinstance(observed, dict) or observed.get('attempt_started') is not True or
            observed.get('response_observed') is not True or observed.get('failure_observed') is not False or
            not isinstance(usage, dict) or type(usage.get('attempted_calls')) is not int or usage['attempted_calls'] != 1):
        raise ActionError('SUCCESSFUL_MODEL_OBSERVATION_REQUIRED')
    if proposal.get('provider') not in ('openai', 'anthropic') or any(proposal.get(k) is not False for k in ('approved', 'verified', 'executed', 'tool_executed', 'conditions_confirmed')):
        raise ActionError('PROPOSAL_BOUNDARY_INVALID')
    snapshot, tools = _snapshot(state)
    digest = proposals._digest(snapshot)
    if not _hash(proposal.get('input_snapshot_sha256')) or proposal['input_snapshot_sha256'] != digest:
        raise ActionError('STALE_PROPOSAL_INPUT')
    if proposal.get('prompt_sha256') != proposals._digest(proposals.SYSTEM):
        raise ActionError('STALE_PROPOSAL_PROMPT')
    body = proposals._validate_proposal(proposal.get('proposal'), snapshot['excerpt'], snapshot['paper_context'], tools)
    if proposal.get('proposal_sha256') != proposals._digest(body):
        raise ActionError('PROPOSAL_INTEGRITY_INVALID')
    return body['next_tool']['name'], digest


def _binding(proposal, state):
    """Bind source/data/spec/pool/selection without returning their contents."""
    download = state.get('download', {})
    if not isinstance(download, dict):
        raise ActionError('ACTION_STATE_INVALID')
    keys = ('pending_repository', 'record_provider', 'record', 'selected_file', 'spec', 'conditions_confirmed',
            'candidate_set', 'selected_candidate', 'source_receipt', 'paper_context', 'source_location')
    value = {key: _digest(state.get(key)) for key in keys}
    value.update(input_snapshot_sha256=proposal['input_snapshot_sha256'], proposal_sha256=proposal['proposal_sha256'],
                 data_sha256=_bytes_sha(download.get('raw_bytes')), receipt_sha256=_digest(download.get('receipt')),
                 source_sha256=_bytes_sha(state.get('source_bytes')), engine_revision=candidates.source_revision())
    return _digest(value)


def _selected(state):
    provider, record, selection = state.get('record_provider'), state.get('record'), state.get('selected_file')
    if provider not in ('zenodo', 'figshare', 'dataverse') or not isinstance(record, dict):
        raise ActionError('EXPLICIT_RECORD_SELECTION_REQUIRED')
    identifier = selection.get('id') if isinstance(selection, dict) else selection
    if type(identifier) not in (str, int) or isinstance(identifier, str) and not identifier:
        raise ActionError('EXPLICIT_FILE_SELECTION_REQUIRED')
    files = record.get('files')
    if not isinstance(files, list):
        raise ActionError('EXPLICIT_FILE_SELECTION_REQUIRED')
    matches = [f for f in files if isinstance(f, dict) and type(f.get('id')) is type(identifier) and f['id'] == identifier]
    if len(matches) != 1 or isinstance(selection, dict) and selection != matches[0]:
        raise ActionError('SELECTED_FILE_NOT_EXACT')
    intake._selection(provider, record, matches[0])
    return provider, deepcopy(record), deepcopy(matches[0])


def _verification(state):
    if state.get('conditions_confirmed') is not True:
        raise ActionError('HUMAN_CONDITION_CONFIRMATION_REQUIRED')
    spec = state.get('spec')
    if not isinstance(spec, dict) or not validate(spec)['ready'] or spec.get('method') not in ('mean', 'row_count'):
        raise ActionError('CURRENT_READY_SCALAR_SPEC_REQUIRED')
    proposals._public(spec)
    data = state.get('download', {})
    if not isinstance(data, dict) or data.get('success') is not True or not isinstance(data.get('receipt'), dict):
        raise ActionError('CURRENT_DOWNLOAD_REQUIRED')
    raw, receipt = data.get('raw_bytes'), data['receipt']
    if spec.get('data_fingerprint') != _bytes_sha(raw):
        raise ActionError('STALE_SPEC_DATA')
    intake._current_receipt(raw, receipt, state.get('record'))
    paper = intake._paper_context(state.get('paper_context'))
    if receipt.get('provider') == 'registered':
        # Existing intake enforces this fixed contract again before its sole calculation.
        context = receipt['record_context']
        if (paper.get('source_url') != context['paper_url'] or paper.get('source_sha256') != context['source_public_derivative_sha256']
                or paper.get('paper_doi') != '10.32614/RJ-2022-020' or paper.get('paper_version') != 'published article; registered public derivative'):
            raise ActionError('REGISTERED_PAPER_BINDING_REQUIRED')
        if state.get('source_bytes') is not None and _bytes_sha(state['source_bytes']) != paper['source_sha256']:
            raise ActionError('CURRENT_SOURCE_BYTES_DIFFER')
        case = intake._registered_case(receipt['record_context']['claim_id'])
        expected = {'method': 'row_count', 'variable': None, 'filters': [], 'missing_policy': 'not_applicable',
                    'missing_tokens': [], 'denominator': 'all CSV data rows, without filtering', 'unit': 'individual penguins',
                    'reported_value': case['source']['reported_value'], 'tolerance': case['source']['tolerance'],
                    'source_location': {'source_id': 'RJ-2022-020', 'locator': case['source_location'], 'quote': case['source_quote']}}
        if any(spec.get(key) != value for key, value in expected.items()):
            raise ActionError('REGISTERED_CONDITIONS_DIFFER')
    else:
        provider, _, selected = _selected(state)
        if provider != receipt.get('provider') or selected != receipt['record_context']['selected_file']:
            raise ActionError('STALE_FILE_SELECTION')
        pool = state.get('candidate_set')
        if not isinstance(pool, dict) or not isinstance(pool.get('candidates'), list):
            raise ActionError('CURRENT_EXACT_CANDIDATE_REQUIRED')
        matches = [c for c in pool['candidates'] if isinstance(c, dict) and c.get('candidate_id') == state.get('selected_candidate')]
        if len(matches) != 1:
            raise ActionError('CURRENT_EXACT_CANDIDATE_REQUIRED')
        check = candidates.compare_source_conditions(matches[0], spec, source_bytes=state.get('source_bytes'),
                    source_receipt=state.get('source_receipt'), paper_context=paper, data_sha256=_bytes_sha(raw), candidate_set=pool)
        if check.get('success') is not True or check.get('agreement') != 'EXACT' or check.get('can_preview') is not True:
            raise ActionError('CURRENT_EXACT_CANDIDATE_REQUIRED')
        header, rows = intake._csv(raw)
        denominator, _ = candidates._observed_denominator(spec, header, rows)
        if denominator['status'] != 'OBSERVED_ROW_COUNT_MATCH':
            raise ActionError('DENOMINATOR_OBSERVATION_REQUIRED')
    return raw, deepcopy(receipt), deepcopy(spec), paper


def _observation(receipt, result):
    source = result.get('receipt', {}).get('download', {}) if isinstance(result.get('receipt'), dict) else result
    stamp = source.get('retrieved_at_kst')
    if isinstance(stamp, str):
        try:
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is not None:
                receipt['observed_at_kst'] = parsed.astimezone(timezone(timedelta(hours=9))).isoformat()
        except ValueError:
            pass
    if receipt['tool'] == 'verify_download':
        stamp = result.get('calculated_at_kst')
        if isinstance(stamp, str):
            try:
                parsed = datetime.fromisoformat(stamp)
                if parsed.tzinfo is not None:
                    receipt['observed_at_kst'] = parsed.astimezone(timezone(timedelta(hours=9))).isoformat()
            except ValueError:
                pass
        receipt.update(http_status=None, http_observation='NOT_APPLICABLE_LOCAL_TOOL')
    else:
        status = source.get('http_status')
        if type(status) is int and 100 <= status <= 599:
            receipt.update(http_status=status, http_observation='OBSERVED_PROVIDER_RECEIPT')


def execute_next_tool(proposal, state, *, opted_in=False):
    """Return a public receipt and internal patch; never mutate caller state.

    Apply ``state_patch`` only on this synchronous user event. Store/display only
    ``receipt`` in audit UI. No polling, retry, model invocation or human approval.
    """
    started = perf_counter()
    receipt = {'schema': SCHEMA, 'tool': None, 'input_snapshot_sha256': None, 'proposal_sha256': None,
               'action_input_sha256': None, 'attempt_started': False, 'tool_invocations': 0,
               'recorded_at_kst': None, 'observed_at_kst': None, 'observation_kind': 'NOT_ATTEMPTED',
               'http_status': None, 'http_observation': 'UNKNOWN', 'elapsed_ms': None, 'usage_unknown': True,
               'error_code': None, 'output_sha256': None, 'approved': False, 'verified': False}
    outcome = {'success': False, 'status': 'BLOCKED', 'error': None, 'receipt': receipt,
               'next_action': 'REVIEW_INPUTS', 'state_patch': {}, 'approved': False, 'verified': False, 'tool_executed': False}
    try:
        if opted_in is not True:
            raise ActionError('EXPLICIT_OPT_IN_REQUIRED')
        if not isinstance(state, dict):
            raise ActionError('ACTION_STATE_INVALID')
        tool, snapshot_sha = _validated(proposal, state)
        receipt.update(tool=tool, input_snapshot_sha256=snapshot_sha, proposal_sha256=proposal['proposal_sha256'])
        bound = _binding(proposal, state)
        receipt['action_input_sha256'] = bound
        previous = state.get('action_receipt')
        if (isinstance(previous, dict) and bound in (previous.get('action_input_sha256'), previous.get('resulting_state_sha256'))
                and previous.get('attempt_started') is True):
            raise ActionError('ALREADY_ATTEMPTED_FOR_CURRENT_INPUT')
        outcome['next_action'] = GUIDES[tool]
        if tool in ('manual_source_review', 'stop'):
            receipt.update(observation_kind='GUIDANCE_ONLY', http_observation='NOT_APPLICABLE_GUIDANCE')
            outcome.update(success=True, status='GUIDANCE_ONLY')
        else:
            if tool == 'repository_record':
                selected = state.get('pending_repository')
                if not isinstance(selected, dict) or set(selected) != {'provider', 'identifier'}:
                    raise ActionError('EXPLICIT_REPOSITORY_SELECTION_REQUIRED')
                provider, identifier = selected['provider'], selected['identifier']
                repository_extensions._input(provider, identifier)  # Fixed host/ID grammar, before dispatch.
                args = (provider, identifier)
                function = router.repository
                kwargs = {}
            elif tool == 'acquisition':
                args = _selected(state)
                function = intake.acquisition
                kwargs = {}
            else:
                raw, received, spec, paper = _verification(state)
                args = (raw, received, spec)
                function = intake.verify_download
                kwargs = {'paper_context': paper, 'conditions_confirmed': True, 'current_record': deepcopy(state.get('record'))}
            receipt.update(attempt_started=True, tool_invocations=1, observation_kind='EXPLICIT_SINGLE_TOOL_INVOCATION')
            result = function(*args, **kwargs)  # Exactly one invocation. No fallback or retry.
            if not isinstance(result, dict) or any(result.get(k) is True for k in ('approved', 'verified')):
                raise ActionError('TOOL_RESULT_INVALID')
            _observation(receipt, result)
            if _binding(proposal, state) != bound:
                raise ActionError('INPUT_CHANGED_DURING_TOOL')
            good = result.get('ok') is True if tool == 'repository_record' else result.get('success') is True
            if not good:
                raise ActionError('TOOL_DID_NOT_SUCCEED')
            public_result = {k: v for k, v in result.items() if k != 'raw_bytes'}
            proposals._public(public_result)
            receipt['output_sha256'] = _digest(public_result)
            if tool == 'repository_record':
                items = result.get('items')
                if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
                    raise ActionError('TOOL_RESULT_INVALID')
                patch = {'repository_response': deepcopy(result), 'record': deepcopy(items[0]), 'record_provider': provider,
                         'selected_file': None, 'download': {}, 'conditions_confirmed': False, 'report': None,
                         'candidate_set': None, 'selected_candidate': None, 'source_agreement': None}
            elif tool == 'acquisition':
                intake._current_receipt(result.get('raw_bytes'), result.get('receipt'), args[1])
                patch = {'download': deepcopy(result), 'conditions_confirmed': False, 'report': None,
                         'candidate_set': None, 'selected_candidate': None, 'source_agreement': None}
            else:
                patch = {'report': deepcopy(result)}
            outcome.update(success=True, status='TOOL_COMPLETED', tool_executed=True, state_patch=patch)
    except Exception as error:
        # Never reflect provider exceptions, source cells, model prose or transport URLs.
        code = str(error) if isinstance(error, ActionError) else 'ACTION_PRECONDITION_INVALID' if not receipt['attempt_started'] else 'TOOL_EXECUTION_FAILED'
        outcome.update(success=False, status='BLOCKED', error=code, state_patch={}, next_action='REVIEW_INPUTS')
        receipt['error_code'] = code
    finally:
        receipt.update(recorded_at_kst=_now(), elapsed_ms=max(0, int((perf_counter() - started) * 1000)))
        if outcome['success'] or receipt['attempt_started'] and outcome['error'] != 'INPUT_CHANGED_DURING_TOOL':
            # [수정: 0 이영] 2026-10-01 05:10 KST — 성공 후 후보·확인을 비운 내부 패치도 동일 클릭의 결과로 결속해 화면 리런·중복 클릭이 재수신하지 않게 한다.
            if outcome['success'] and receipt['attempt_started']:
                try:
                    receipt['resulting_state_sha256'] = _binding(proposal, {**state, **outcome['state_patch']})
                except Exception:
                    outcome.update(success=False, status='BLOCKED', error='TOOL_RESULT_INVALID', state_patch={}, next_action='REVIEW_INPUTS')
                    receipt['error_code'] = 'TOOL_RESULT_INVALID'
            outcome['state_patch']['action_receipt'] = deepcopy(receipt)
    return outcome

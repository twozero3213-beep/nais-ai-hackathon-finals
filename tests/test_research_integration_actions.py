"""Synthetic manual-dispatch controls; every transport/model call is mocked."""
# [작성: 0 이영 · Codex] 2026-10-01 05:04 KST — 도구 동의 전 호출 0, 명시 선택, 같은 숫자·다른 조건, 중복·늦은 결과 및 정상 계산 한 번을 모의 회귀로 검증한다. 실제 AI 성능이나 실제 사람 승인이 아니다.
from copy import deepcopy
import hashlib
import json
from unittest.mock import Mock

import pytest
from core import research_integration_actions as actions
from core import research_integration_candidates as candidates
from core import research_integration_intake as intake
from core import research_integration_proposals as proposals
from evidence_gate.spec import empty_spec

RAW = b'group,score\nA,10\nA,30\nB,18\nB,22\n'
QUOTE = 'The mean of score in group A is 20 points (n=2). Missing policy: error. Tolerance: 0.'
LOCATION = {'source_id': 'synthetic-source', 'locator': 'Methods-1', 'quote': QUOTE}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def record(raw=RAW):
    return {'id': '23', 'doi': '10.5281/zenodo.23', 'concept_doi': '10.5281/zenodo.22',
            'version': None, 'detail_status': 'RETRIEVED', 'official_url': 'https://zenodo.org/records/23',
            'license': {'id': 'cc0-1.0'}, 'access': {'metadata': 'public', 'files': 'open'},
            'custom_terms_present': False, 'provenance': {'response_sha256': 'a' * 64},
            'files': [{'id': 'selected-file', 'name': 'synthetic.csv', 'size': len(raw), 'restricted': False,
                       'checksum': {'algorithm': 'md5', 'value': hashlib.md5(raw).hexdigest()}, 'supplied_checksum': None}]}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(candidates, 'source_revision', lambda: 'synthetic-engine-1')
    monkeypatch.setattr(intake, 'source_revision', lambda: 'synthetic-engine-1')
    network = Mock(side_effect=AssertionError('Transport must be explicitly mocked'))
    monkeypatch.setattr(actions.repository_extensions, '_request', network)
    monkeypatch.setattr(intake, '_get_bytes', network)
    monkeypatch.setattr(proposals.finals_provider, 'paid_call_allowed', lambda session: True)
    monkeypatch.setattr(proposals.finals_provider, 'live_allowed', lambda: True)
    monkeypatch.setattr(proposals.finals_provider, 'complete_json', network)
    return network


def state(monkeypatch, *, raw=RAW, quote=QUOTE, denominator='n=2', group='A', freeze=True):
    r = record(raw)
    network = Mock(return_value=(raw, {'http_status': 200, 'source_url': 'https://zenodo.org/api/records/23/files/synthetic.csv/content',
                                     'retrieved_at_kst': '2026-10-01T04:00:00+09:00'}))
    monkeypatch.setattr(intake, '_get_bytes', network)
    downloaded = intake.acquisition('zenodo', r, r['files'][0])
    assert downloaded['success']
    network.reset_mock()
    location = dict(LOCATION, quote=quote)
    source = ('Methods\n' + quote + '\n').encode()
    paper = {'source_id': location['source_id'], 'paper_version': 'synthetic-published-1',
             'source_url': 'https://example.org/synthetic', 'source_sha256': sha(source)}
    source_receipt = candidates.source_receipt_for_spans(source, source_url=paper['source_url'], paper_version=paper['paper_version'],
                        spans=[{'locator': location['locator'], 'start_byte': 0, 'end_byte': len(source)}], source_kind='SYNTHETIC_SOURCE_BYTES')
    s = empty_spec('SYNTHETIC-CLAIM')
    s.update(method='mean', variable='score', reported_value=20, filters=[{'column': 'group', 'operator': 'eq', 'value': group}],
             missing_policy='error', missing_tokens=['NA', ''], denominator=denominator, unit='points',
             data_fingerprint=sha(raw), tolerance=0, source_location=location)
    value = {'source_location': location, 'paper_context': paper, 'download': downloaded, 'spec': s,
             'record_provider': 'zenodo', 'record': r, 'selected_file': deepcopy(r['files'][0]),
             'pending_repository': {'provider': 'zenodo', 'identifier': '23'}, 'conditions_confirmed': True,
             'source_bytes': source, 'source_receipt': source_receipt}
    if freeze:
        contract = {'contract_version': 1, 'paper_version': paper['paper_version'], 'source_location': location,
                    'fields': {field: {'status': 'fact', 'value': deepcopy(candidates._spec_groups(s)[field]),
                                      'evidence': {'locator': location['locator'], 'quote': location['quote']}} for field in candidates.FIELDS}}
        pool = candidates.freeze_candidate(contract, s, source_bytes=source, source_receipt=source_receipt,
                                           paper_context=paper, data_sha256=sha(raw), candidate_id='synthetic-1')
        assert pool['success']
        value.update(candidate_set=pool, selected_candidate='synthetic-1')
    return value, network


def propose(monkeypatch, value, tool='verify_download', *, tools=None):
    snapshot, allowed = actions._snapshot(value)
    c = {key: deepcopy(value['spec'].get(key)) for key in proposals.CONDITION_FIELDS}
    model_value = {'conditions': c, 'missing': [], 'next_tool': {'name': tool, 'reason': 'Synthetic recommendation only.'},
                   'limitations': ['Not scientifically verified.']}
    model = Mock(return_value={'provider': 'openai', 'model': proposals.finals_provider.MODEL,
                              'output': model_value, 'usage': {'input_tokens': 10, 'output_tokens': 20}})
    monkeypatch.setattr(proposals.finals_provider, 'complete_json', model)
    result = proposals.propose_conditions(snapshot['excerpt'], snapshot['paper_context'], snapshot['dataset_metadata'],
                                         opted_in=True, session={}, allowed_tools=tools or allowed)
    assert result['success'], result.get('error')
    return result


@pytest.mark.parametrize('consent', [False, None, 0, 1, 'true', [], {}])
def test_explicit_bool_precedes_inputs_and_every_tool(consent, monkeypatch, isolated):
    result = actions.execute_next_tool({'untrusted': 'ignored'}, {}, opted_in=consent)
    assert result['error'] == 'EXPLICIT_OPT_IN_REQUIRED'
    assert result['receipt']['tool_invocations'] == 0 and result['state_patch'] == {}
    isolated.assert_not_called()


def test_sufficient_control_calls_existing_engine_once_never_approves(monkeypatch):
    value, network = state(monkeypatch)
    proposal = propose(monkeypatch, value)
    compute = Mock(wraps=intake.gate.evaluate)
    monkeypatch.setattr(intake.gate, 'evaluate', compute)
    before = deepcopy(value)
    result = actions.execute_next_tool(proposal, value, opted_in=True)
    assert result['success'], result['error']
    compute.assert_called_once()
    network.assert_not_called()
    report = result['state_patch']['report']
    assert report['calculation']['computed'] == 20
    assert report['calculation']['verdict'] == 'MATCH' and not report['approved'] and not report['verified']
    assert report['human_approval'] is None and result['next_action'] == 'HUMAN_REVIEW_REQUIRED'
    assert result['receipt']['http_observation'] == 'NOT_APPLICABLE_LOCAL_TOOL'
    assert value == before
    assert 'quote' not in json.dumps(result['receipt']) and 'raw_bytes' not in json.dumps(result['receipt'])


@pytest.mark.parametrize('field', ['source_quote', 'paper_version', 'receipt_sha', 'missing_snapshot', 'prompt', 'proposal'])
def test_proposal_stale_or_tampered_blocks_before_dispatch(field, monkeypatch):
    value, network = state(monkeypatch)
    proposal = propose(monkeypatch, value, 'acquisition')
    if field == 'source_quote': value['source_location']['quote'] += ' Changed.'
    if field == 'paper_version': value['paper_context']['paper_version'] = 'synthetic-v2'
    if field == 'receipt_sha': value['download']['receipt']['actual_sha256'] = 'b' * 64
    if field == 'missing_snapshot': proposal.pop('input_snapshot_sha256')
    if field == 'prompt': proposal['prompt_sha256'] = 'b' * 64
    if field == 'proposal': proposal['proposal']['next_tool']['reason'] = 'Modified after recording.'
    result = actions.execute_next_tool(proposal, value, opted_in=True)
    assert not result['success'] and result['receipt']['tool_invocations'] == 0
    network.assert_not_called()


@pytest.mark.parametrize('field', ['unsuccessful', 'schema', 'unknown_tool', 'no_observation', 'approval', 'imported_confirmation'])
def test_only_validated_successful_model_response_can_dispatch(field, monkeypatch):
    value, network = state(monkeypatch)
    p = propose(monkeypatch, value, 'acquisition')
    if field == 'unsuccessful': p['success'] = False
    if field == 'schema': p['proposal']['outer_url'] = 'https://example.org/ignored'
    if field == 'unknown_tool': p['proposal']['next_tool']['name'] = 'execute_python'
    if field == 'no_observation': p['call_observation']['response_observed'] = False
    if field == 'approval': p['approved'] = True
    if field == 'imported_confirmation': p['conditions_confirmed'] = True
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert not result['success'] and result['receipt']['tool_invocations'] == 0
    network.assert_not_called()


@pytest.mark.parametrize('tool', ['manual_source_review', 'stop'])
def test_guides_never_invoke_tools_or_network(tool, monkeypatch):
    value, network = state(monkeypatch)
    p = propose(monkeypatch, value, tool)
    dispatch = Mock(side_effect=AssertionError('Guide must not dispatch'))
    monkeypatch.setattr(intake, 'verify_download', dispatch)
    monkeypatch.setattr(intake, 'acquisition', dispatch)
    monkeypatch.setattr(actions.router, 'repository', dispatch)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['status'] == 'GUIDANCE_ONLY' and result['success'] and not result['tool_executed']
    assert result['receipt']['tool_invocations'] == 0
    dispatch.assert_not_called()
    network.assert_not_called()


def test_acquisition_exact_user_selected_file_once_preserves_original_observation(monkeypatch):
    value, network = state(monkeypatch)
    p = propose(monkeypatch, value, 'acquisition')
    value['report'] = {'approved': True, 'historical': True}
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['success'], result['error']
    network.assert_called_once()
    assert result['receipt']['observed_at_kst'] == '2026-10-01T04:00:00+09:00'
    assert result['receipt']['recorded_at_kst'] != result['receipt']['observed_at_kst']
    patch = result['state_patch']
    assert patch['download']['raw_bytes'] == RAW and patch['conditions_confirmed'] is False and patch['report'] is None
    assert patch['candidate_set'] is None and not patch['download']['approved']
    value.update(patch)
    network.reset_mock()
    assert actions.execute_next_tool(p, value, opted_in=True)['error'] == 'ALREADY_ATTEMPTED_FOR_CURRENT_INPUT'
    network.assert_not_called()


@pytest.mark.parametrize('selection', [None, True, '', 'https://example.org/file.csv', 'wrong-id', 1])
def test_no_file_guessing(selection, monkeypatch):
    value, network = state(monkeypatch)
    p = propose(monkeypatch, value, 'acquisition')
    value['selected_file'] = selection
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert not result['success'] and result['receipt']['tool_invocations'] == 0
    network.assert_not_called()


def test_replaced_metadata_outer_url_is_not_executed(monkeypatch):
    value, network = state(monkeypatch)
    p = propose(monkeypatch, value, 'acquisition')
    value['selected_file']['url'] = 'https://example.org/download.csv'
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['error'] == 'SELECTED_FILE_NOT_EXACT'
    network.assert_not_called()


def test_repository_uses_pending_selection_once_not_model_arguments(monkeypatch):
    value, network = state(monkeypatch)
    p = propose(monkeypatch, value, 'repository_record')
    answer = {'ok': True, 'items': [record()], 'provider': 'zenodo', 'http_status': 200,
              'retrieved_at_kst': '2026-10-01T04:00:00+09:00'}
    lookup = Mock(return_value=answer)
    monkeypatch.setattr(actions.router, 'repository', lookup)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['success']
    lookup.assert_called_once_with('zenodo', '23')
    network.assert_not_called()
    assert result['state_patch']['selected_file'] is None and result['state_patch']['download'] == {}


@pytest.mark.parametrize('pending', [None, {'provider': 'other', 'identifier': '23'},
                                    {'provider': 'zenodo', 'identifier': 'https://example.org/23'},
                                    {'provider': 'zenodo', 'identifier': '23', 'url': 'https://example.org/ignored'}])
def test_repository_requires_explicit_fixed_provider_identifier(pending, monkeypatch):
    value, network = state(monkeypatch)
    p = propose(monkeypatch, value, 'repository_record')
    value['pending_repository'] = pending
    lookup = Mock(side_effect=AssertionError('No guessed record'))
    monkeypatch.setattr(actions.router, 'repository', lookup)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert not result['success'] and result['receipt']['tool_invocations'] == 0
    lookup.assert_not_called()
    network.assert_not_called()


@pytest.mark.parametrize('confirmation', [False, None, 1, 'true'])
def test_spec_json_or_ai_flags_are_never_human_confirmation(confirmation, monkeypatch):
    value, network = state(monkeypatch)
    p = propose(monkeypatch, value)
    value['conditions_confirmed'] = confirmation
    value['spec']['confirmed'] = True
    compute = Mock(side_effect=AssertionError('No unconfirmed calculation'))
    monkeypatch.setattr(intake.gate, 'evaluate', compute)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['error'] == 'HUMAN_CONDITION_CONFIRMATION_REQUIRED'
    compute.assert_not_called()
    network.assert_not_called()


@pytest.mark.parametrize('attack', ['same_average_other_group', 'same_numbers_new_data', 'new_source', 'new_pool', 'no_pool', 'unresolved', 'denominator'])
def test_exact_current_source_guard_runs_before_calculation(attack, monkeypatch):
    value, network = state(monkeypatch)
    if attack == 'denominator':
        quote = QUOTE.replace('n=2', 'n=20')
        value, network = state(monkeypatch, quote=quote, denominator='n=20')
    p = propose(monkeypatch, value)
    if attack == 'same_average_other_group': value['spec']['filters'][0]['value'] = 'B'
    if attack == 'same_numbers_new_data': value['download']['raw_bytes'] = b'group,score\nA,5\nA,35\nB,18\nB,22\n'
    if attack == 'new_source': value['source_bytes'] += b' Different context.'
    if attack == 'new_pool': value['candidate_set']['candidate_set_sha256'] = 'b' * 64
    if attack == 'no_pool': value.pop('candidate_set')
    if attack == 'unresolved': value['spec']['unresolved'] = ['MISSING_SOURCE_CONDITION']
    compute = Mock(side_effect=AssertionError('Guard must precede calculation'))
    monkeypatch.setattr(intake.gate, 'evaluate', compute)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert not result['success'] and result['receipt']['tool_invocations'] == 0
    compute.assert_not_called()
    network.assert_not_called()


def test_same_average_wrong_group_frozen_candidate_not_exact(monkeypatch):
    value, network = state(monkeypatch, freeze=False)
    s = deepcopy(value['spec'])
    contract = {'contract_version': 1, 'paper_version': value['paper_context']['paper_version'], 'source_location': LOCATION,
                'fields': {f: {'status': 'fact', 'value': deepcopy(candidates._spec_groups(s)[f]),
                              'evidence': {'locator': LOCATION['locator'], 'quote': QUOTE}} for f in candidates.FIELDS}}
    s['filters'][0]['value'] = 'B'
    pool = candidates.freeze_candidate(contract, s, source_bytes=value['source_bytes'], source_receipt=value['source_receipt'],
                paper_context=value['paper_context'], data_sha256=sha(RAW), candidate_id='synthetic-1')
    assert pool['success']
    value.update(spec=s, candidate_set=pool, selected_candidate='synthetic-1')
    p = propose(monkeypatch, value)
    verify = Mock(side_effect=AssertionError('Wrong group must not calculate'))
    monkeypatch.setattr(intake, 'verify_download', verify)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['error'] == 'CURRENT_EXACT_CANDIDATE_REQUIRED'
    verify.assert_not_called()
    network.assert_not_called()


def test_late_tool_result_cannot_replace_changed_inputs(monkeypatch):
    value, network = state(monkeypatch)
    p = propose(monkeypatch, value, 'repository_record')
    def late(*args):
        value['spec']['unit'] = 'changed-unit'
        return {'ok': True, 'items': [record()]}
    lookup = Mock(side_effect=late)
    monkeypatch.setattr(actions.router, 'repository', lookup)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['error'] == 'INPUT_CHANGED_DURING_TOOL' and result['state_patch'] == {}
    lookup.assert_called_once()
    network.assert_not_called()


def test_engine_change_during_tool_is_not_applied(monkeypatch):
    value, _ = state(monkeypatch)
    p = propose(monkeypatch, value, 'repository_record')
    def changed(*args):
        monkeypatch.setattr(candidates, 'source_revision', lambda: 'synthetic-engine-2')
        return {'ok': True, 'items': [record()]}
    monkeypatch.setattr(actions.router, 'repository', changed)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['error'] == 'INPUT_CHANGED_DURING_TOOL' and result['state_patch'] == {}


def test_failure_does_not_echo_sensitive_exception_or_retry(monkeypatch):
    value, _ = state(monkeypatch)
    p = propose(monkeypatch, value, 'repository_record')
    secret = 'SYNTHETIC_PRIVATE_EXCEPTION_PAYLOAD'
    lookup = Mock(side_effect=RuntimeError(secret))
    monkeypatch.setattr(actions.router, 'repository', lookup)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['error'] == 'TOOL_EXECUTION_FAILED' and result['receipt']['tool_invocations'] == 1
    assert secret not in json.dumps(result)
    value.update(result['state_patch'])
    assert actions.execute_next_tool(p, value, opted_in=True)['error'] == 'ALREADY_ATTEMPTED_FOR_CURRENT_INPUT'
    lookup.assert_called_once()


def registered_state(monkeypatch):
    # This registry is deliberately synthetic; no real registered dataset is fetched.
    quote = 'Four individual penguins in all CSV data rows, without filtering.'
    location = {'source_id': 'RJ-2022-020', 'locator': 'Synthetic Table 1', 'quote': quote}
    source_sha = sha(quote.encode())
    paper_url = 'https://example.org/synthetic-registered'
    case = {'registered_data_sha256': sha(RAW), 'source_sha256': source_sha, 'source_quote': quote,
            'source_location': location['locator'], 'paper_url': paper_url,
            'source': {'reported_value': 4, 'tolerance': 0}}
    monkeypatch.setattr(intake, '_registered_case', lambda claim: deepcopy(case))
    context = {'provider': 'registered', 'claim_id': intake.REGISTERED_CLAIM_ID,
               'source_public_derivative_sha256': source_sha, 'source_quote': quote,
               'source_location': location['locator'], 'paper_url': paper_url}
    received = intake._seal({'schema': intake.SCHEMA, 'provider': 'registered', 'record_context': context,
                'record_context_sha256': intake._digest(context), 'actual_sha256': sha(RAW), 'actual_size': len(RAW),
                'license_policy': 'CC0-1.0', 'download': {'http_status': 200, 'retrieved_at_kst': '2026-10-01T04:00:00+09:00'},
                'approved': False, 'verified': False})
    s = empty_spec('SYNTHETIC-REGISTERED')
    s.update(method='row_count', reported_value=4, filters=[], missing_policy='not_applicable', missing_tokens=[],
             denominator='all CSV data rows, without filtering', unit='individual penguins',
             data_fingerprint=sha(RAW), tolerance=0, source_location=location)
    return {'spec': s, 'source_location': location, 'conditions_confirmed': True,
            'paper_context': {'paper_doi': '10.32614/RJ-2022-020', 'source_id': 'RJ-2022-020',
                              'paper_version': 'published article; registered public derivative',
                              'source_url': paper_url, 'source_sha256': source_sha},
            'download': {'success': True, 'raw_bytes': RAW, 'receipt': received}}


def test_registered_static_contract_can_calculate_once_without_invented_candidate_or_approval(monkeypatch, isolated):
    value = registered_state(monkeypatch)
    p = propose(monkeypatch, value)
    compute = Mock(wraps=intake.gate.evaluate)
    monkeypatch.setattr(intake.gate, 'evaluate', compute)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['success'], result['error']
    compute.assert_called_once()
    report = result['state_patch']['report']
    assert report['calculation']['computed'] == 4 and not report['approved'] and not report['verified']
    assert report['paper_source_status']['status'] == 'REGISTERED_PUBLIC_DERIVATIVE_CONFIRMED'
    isolated.assert_not_called()


@pytest.mark.parametrize('field', ['filters', 'unit', 'denominator', 'source_location', 'reported_value'])
def test_registered_static_contract_rejects_new_conditions_even_with_new_proposal(field, monkeypatch, isolated):
    value = registered_state(monkeypatch)
    if field == 'filters': value['spec']['filters'] = [{'column': 'group', 'operator': 'eq', 'value': 'B'}]
    if field == 'unit': value['spec']['unit'] = 'rows'
    if field == 'denominator': value['spec']['denominator'] = 'all CSV rows'
    if field == 'reported_value': value['spec']['reported_value'] = 2
    if field == 'source_location':
        value['source_location']['locator'] = 'Other Table'
        value['spec']['source_location'] = deepcopy(value['source_location'])
    p = propose(monkeypatch, value)
    compute = Mock(side_effect=AssertionError('Registry conditions must be checked first'))
    monkeypatch.setattr(intake.gate, 'evaluate', compute)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['error'] == 'REGISTERED_CONDITIONS_DIFFER'
    assert result['receipt']['tool_invocations'] == 0
    compute.assert_not_called()
    isolated.assert_not_called()


@pytest.mark.parametrize('field', ['source_url', 'source_sha256', 'paper_version', 'source_bytes'])
def test_registered_other_paper_or_actual_bytes_block_before_dispatch(field, monkeypatch, isolated):
    value = registered_state(monkeypatch)
    if field == 'source_url': value['paper_context'][field] = 'https://example.org/other-source'
    if field == 'source_sha256': value['paper_context'][field] = 'b' * 64
    if field == 'paper_version': value['paper_context'][field] = 'Other published version'
    if field == 'source_bytes': value[field] = b'A different received source with the same numbers.'
    p = propose(monkeypatch, value)
    verify = Mock(side_effect=AssertionError('Registry pair must be checked before the tool'))
    monkeypatch.setattr(intake, 'verify_download', verify)
    result = actions.execute_next_tool(p, value, opted_in=True)
    assert result['error'] in {'REGISTERED_PAPER_BINDING_REQUIRED', 'CURRENT_SOURCE_BYTES_DIFFER'}
    assert result['receipt']['tool_invocations'] == 0
    verify.assert_not_called()
    isolated.assert_not_called()

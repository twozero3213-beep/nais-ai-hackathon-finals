"""Real registered UI path, input invalidation and internal-byte isolation."""
# [작성: 0 이영] 2026-10-01 04:33 KST — 모의 전송만 사용하고 실제 intake/gate/UI의 단계·상태 전이를 검증한다. 실제 사람 승인·배포 검증과 구분한다.
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock
import json
import hashlib

import pytest
from streamlit.testing.v1 import AppTest
from core import research_integration_router as router
from core import research_integration_intake as intake
from core import research_integration_relations as relations
from core import research_integration_feeds as feeds
from core.research_integration_ui import _public
from finals.finals_cases import load_case

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app(monkeypatch):
    monkeypatch.chdir(ROOT)
    for module, name in ((router, 'search'), (router, 'publication'), (router, 'repository'),
                         (relations, 'datacite_relations'), (relations, 'jats_data_availability'),
                         (feeds, 'get_integration_feed')):
        monkeypatch.setattr(module, name, Mock(side_effect=AssertionError('implicit network')))
    raw = load_case('PENG-RAW-ROWS')['data_bytes']
    def received(host, path, **kwargs):
        body = b'Package: palmerpenguins\nLicense: CC0\n' if path == intake.LICENSE_PATH else raw
        return body, {'http_status': 200, 'source_url': 'https://' + host + path,
                      'retrieved_at_kst': '2026-10-01T04:33:00+09:00'}
    monkeypatch.setattr(intake, '_get_bytes', received)
    return AppTest.from_file(str(ROOT / '0_이영_연구연동.py'), default_timeout=60).run()


def receive(app):
    app.button(key='ri_registered_acquire').click().run()
    assert not app.exception
    assert app.session_state['ri_step'] == 2
    return app


def calculated(app):
    receive(app)
    assert app.button(key='ri_conditions_next').disabled
    app.checkbox(key='ri_conditions_confirmed').check().run()
    app.button(key='ri_conditions_next').click().run()
    assert app.session_state['ri_step'] == 3
    app.button(key='ri_compute').click().run()
    assert not app.exception
    return app.session_state['ri_state']['report']


def test_registered_real_gate_to_manual_review_without_auto_approval(app):
    report = calculated(app)
    assert report['calculation']['computed'] == 344
    assert report['calculation']['verdict'] == 'MATCH'
    assert report['approved'] is False and report['verified'] is False
    assert report['paper_source_status']['original_publisher_response_sha256'] is None
    app.button(key='ri_result_next').click().run()
    assert not app.exception and app.session_state['ri_step'] == 4
    assert app.button(key='ri_approve').disabled
    relations.jats_data_availability.assert_not_called()
    router.search.assert_not_called()


def test_registered_redownload_resets_confirmed_widget_and_result(app):
    calculated(app)
    app.button(key='ri_back').click().run()
    receive(app)
    assert not app.session_state['ri_state'].get('report')
    assert app.checkbox(key='ri_conditions_confirmed').value is False
    assert app.button(key='ri_conditions_next').disabled


def test_changed_source_location_resets_review(app):
    calculated(app)
    app.button(key='ri_back').click().run()
    app.text_input(key='ri_locator').set_value('a different group').run()
    assert not app.exception
    assert not app.session_state['ri_state'].get('report')
    assert app.session_state['ri_state']['conditions_confirmed'] is False


def test_missing_condition_candidate_freezes_without_widget_exception(app):
    receive(app)
    app.checkbox(key='ri_conditions_confirmed').check().run()
    app.button(key='ri_candidate_freeze').click().run()
    assert not app.exception
    pool = app.session_state['ri_state']['candidate_set']
    assert pool['success'] and len(pool['candidates']) == 1
    assert pool['semantic_ready'] is False and pool['can_approve'] is False
    assert app.checkbox(key='ri_conditions_confirmed').value is False
    assert app.button(key='ri_blind_request').disabled
    app.checkbox(key='ri_conditions_confirmed').check().run()
    app.button(key='ri_conditions_next').click().run()
    app.button(key='ri_compute').click().run()
    assert not app.exception
    assert not app.session_state['ri_state'].get('report')
    assert app.session_state['ri_state']['source_agreement']['agreement'] != 'EXACT'


def test_internal_bytes_cannot_enter_public_json():
    result = _public({'source_bytes': b'private original', 'raw_bytes': b'raw rows',
                      'nested': {'unknown_name': b'private bytes'}, 'receipt': {'sha256': 'a' * 64}})
    encoded = json.dumps(result)
    assert 'private' not in encoded and 'raw rows' not in encoded
    assert 'source_bytes' not in result and 'raw_bytes' not in result
    assert result['receipt']['sha256'] == 'a' * 64


def test_explicit_proposal_same_input_is_reserved_once_even_when_failed(app, monkeypatch):
    # [수정: 0 이영] 2026-10-01 05:25 KST — 모델은 모의하며 실패한 같은 입력의 반복 클릭에서도 호출 1회와 내부 자료 비전송을 검사한다.
    from core import research_integration_proposals as proposals
    from finals import finals_provider
    propose = Mock(return_value={'success': False, 'status': 'BLOCKED', 'error': 'SIMULATED_PROVIDER_FAILURE',
                                 'usage': {'attempted_calls': 1}})
    monkeypatch.setattr(proposals, 'propose_conditions', propose)
    monkeypatch.setattr(finals_provider, 'paid_call_allowed', lambda session: True)
    monkeypatch.setattr(finals_provider, 'availability', lambda: {'available': True})
    monkeypatch.setattr(finals_provider, 'live_allowed', lambda: True)
    receive(app)
    app.checkbox(key='ri_ai_opted').check().run()
    app.button(key='ri_ai_propose').click().run()
    app.button(key='ri_ai_propose').click().run()
    assert not app.exception and propose.call_count == 1
    assert len(app.session_state['ri_proposal_attempts']) == 1
    assert 'raw_bytes' not in propose.call_args.args[2]
    assert 'report' not in propose.call_args.args[1]


def test_blind_button_passes_actual_data_sha_and_server_budget_session(app, monkeypatch):
    from core import research_integration_blind_review as blind
    from finals import finals_provider
    def observed(*args, **kwargs):
        # SessionStateProxy resolves inside the AppTest script thread, not the outer pytest thread.
        kwargs['session']['ri_blind_has_server_state'] = kwargs['session'].get('ri_state') is not None
        return {'success': False, 'status': 'BLOCKED', 'error': 'SIMULATED', 'semantic_ready': False}
    call = Mock(side_effect=observed)
    monkeypatch.setattr(blind, 'blind_review_conditions', call)
    monkeypatch.setattr(finals_provider, 'paid_call_allowed', lambda session: True)
    monkeypatch.setattr(finals_provider, 'availability', lambda: {'available': True})
    monkeypatch.setattr(finals_provider, 'live_allowed', lambda: True)
    receive(app)
    app.button(key='ri_candidate_freeze').click().run()
    state = app.session_state['ri_state']
    state['source_bytes'] = b'<p>Neutral methods paragraph.</p>'
    state['source_receipt'] = {'locations': {'/article/body/sec/p': {'context_sha256': 'a' * 64}}}
    app.run()
    app.multiselect(key='ri_blind_locations').set_value(['/article/body/sec/p']).run()
    app.checkbox(key='ri_blind_opted').check().run()
    app.button(key='ri_blind_request').click().run()
    assert not app.exception and call.call_count == 1
    kwargs = call.call_args.kwargs
    assert kwargs['dataset_metadata']['actual_sha256'] == hashlib.sha256(state['download']['raw_bytes']).hexdigest()
    assert 'raw_bytes' not in kwargs['dataset_metadata']
    assert app.session_state['ri_blind_has_server_state'] is True


def test_explicit_verify_tool_result_survives_rerun_without_reset(app, monkeypatch):
    from core import research_integration_actions as actions
    receive(app)
    state = app.session_state['ri_state']
    state['proposal'] = {'success': True, 'suggested_spec': state['download']['suggested_spec']}
    report = {'success': True, 'state': 'NEEDS_HUMAN_REVIEW', 'approved': False, 'verified': False}
    execute = Mock(return_value={'success': True, 'tool_executed': True, 'status': 'TOOL_COMPLETED',
                                'receipt': {'tool': 'verify_download'}, 'state_patch': {'report': report}})
    monkeypatch.setattr(actions, 'execute_next_tool', execute)
    app.run()
    app.checkbox(key='ri_action_opted').check().run()
    app.button(key='ri_action_execute').click().run()
    assert not app.exception and app.session_state['ri_step'] == 3
    assert app.session_state['ri_state']['report'] == report
    assert execute.call_count == 1


def test_jats_contexts_parse_once_until_received_bytes_change(app, monkeypatch):
    from core import research_integration_source_spans as spans
    raw = b'<article><body><sec><p>Methods: group A, score in points.</p></sec></body></article>'
    received = {'ok': True, 'status': 'AVAILABILITY_CANDIDATES', 'source_bytes': raw,
                'response_sha256': hashlib.sha256(raw).hexdigest(), 'items': []}
    monkeypatch.setattr(relations, 'jats_data_availability', Mock(return_value=received))
    parse = Mock(wraps=spans.jats_contexts)
    monkeypatch.setattr(spans, 'jats_contexts', parse)
    app.text_input(key='ri_paper_doi').set_value('10.1371/journal.pone.0326678').run()
    app.button(key='ri_jats').click().run()
    assert not app.exception and parse.call_count == 1
    app.text_input(key='ri_identifier').set_value('42').run()
    assert not app.exception and parse.call_count == 1
    state = app.session_state['ri_state']
    changed = raw + b'\n'
    state['jats'] = {**received, 'source_bytes': changed, 'response_sha256': hashlib.sha256(changed).hexdigest()}
    app.run()
    assert not app.exception and parse.call_count == 2
    assert relations.jats_data_availability.call_count == 1


@pytest.mark.parametrize('field,value', [
    ('unit', 'grams'), ('denominator', 'group B only'),
    ('filters', [{'column': 'Sex', 'operator': 'eq', 'value': 'MALE'}]),
    ('source_location', {'source_id': 'OTHER', 'locator': 'wrong location', 'quote': '344'}),
])
def test_same_reported_number_different_registered_conditions_cannot_first_pass(app, field, value):
    receive(app)
    downloaded = app.session_state['ri_state']['download']
    spec = deepcopy(downloaded['suggested_spec'])
    spec[field] = value
    report = intake.verify_download(downloaded['raw_bytes'], downloaded['receipt'], spec,
                                    paper_context=downloaded['paper_context'], conditions_confirmed=True)
    assert report['action'] == 'BLOCK' and report['error'] == 'REGISTERED_CONDITIONS_DIFFER'
    assert report['approved'] is False

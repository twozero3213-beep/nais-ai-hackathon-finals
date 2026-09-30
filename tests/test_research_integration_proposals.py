"""Opt-in proposal contract tests: mocked provider invocations, no live model traffic."""
# [작성: 0 이영 · Codex] 2026-10-01 03:32 KST — 후보 구조·미확정 조건·출처 결속·호출 시도/실패/사용량·비밀 비반사를 모의 검증한다.
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
from core import research_integration_proposals as proposals
from finals import finals_provider

EXCERPT='Table 1 reports 4 observations. All CSV rows are counted, without filtering. Unit: observations. Missing values do not affect row count. Tolerance: 0.'
PAPER={'paper_doi':'10.0000/synthetic','source_id':'synthetic-source','locator':'Table 1','source_url':'https://example.org/paper','source_sha256':'a'*64}
DATA={'claim_id':'SYNTHETIC-CLAIM','actual_sha256':'b'*64,'name':'Synthetic CSV','columns':['x']}
KEY='not-a-real-server-key'


def candidate():
    return {'conditions':{'denominator':'all CSV rows','filters':[],'unit':'observations','missing_policy':'not_applicable',
                         'missing_tokens':[],'method':'row_count','variable':None,'reported_value':4,'tolerance':0,
                         'source_location':{'source_id':'synthetic-source','locator':'Table 1','quote':'Table 1 reports 4 observations.'}},
            'missing':[],'next_tool':{'name':'verify_download','reason':'The user must confirm the stated row-count conditions before calculation.'},
            'limitations':['These conditions are an unconfirmed model proposal.']}


def envelope(output=None,usage=None):
    return {'provider':'openai','model':finals_provider.MODEL,'output':candidate() if output is None else output,
            'usage':{'input_tokens':71,'output_tokens':30} if usage is None else usage}


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    monkeypatch.setattr(finals_provider,'paid_call_allowed',lambda session=None:True)
    monkeypatch.setattr(finals_provider,'live_allowed',lambda:True)
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope()))
    monkeypatch.setattr(finals_provider,'_api_key',Mock(side_effect=AssertionError('No direct key lookup')))
    monkeypatch.setattr(proposals.research_agent,'_post_messages',Mock(side_effect=AssertionError('Unexpected Anthropic traffic')))


def call(**kwargs):
    args={'opted_in':True,'session':{'authenticated_member':'test-member'}}
    args.update(kwargs)
    return proposals.propose_conditions(EXCERPT,PAPER,DATA,**args)


@pytest.mark.parametrize('opted_in',[False,None,0,1,'true',[]])
def test_no_explicit_bool_consent_has_no_configuration_or_call(opted_in,monkeypatch):
    paid=Mock(side_effect=AssertionError('Do not inspect server config'))
    monkeypatch.setattr(finals_provider,'paid_call_allowed',paid)
    report=call(opted_in=opted_in)
    assert report['error']=='EXPLICIT_OPT_IN_REQUIRED'
    assert report['usage']['attempted_calls']==0
    paid.assert_not_called(); finals_provider.complete_json.assert_not_called(); finals_provider._api_key.assert_not_called()


def test_team_auth_precedes_provider_invocation(monkeypatch):
    monkeypatch.setattr(finals_provider,'paid_call_allowed',lambda session=None:False)
    assert call()['error']=='TEAM_AUTH_REQUIRED'
    finals_provider.complete_json.assert_not_called(); finals_provider._api_key.assert_not_called()


def test_operator_off_precedes_key_and_call(monkeypatch):
    monkeypatch.setattr(finals_provider,'live_allowed',lambda:False)
    report=call()
    assert report['error']=='LIVE_AI_NOT_ALLOWED' and report['usage']['status']=='NOT_ATTEMPTED'
    finals_provider.complete_json.assert_not_called(); finals_provider._api_key.assert_not_called()


def test_one_existing_client_attempt_no_approval_or_execution():
    report=call()
    assert report['success'] and report['status']=='PROPOSED'
    assert report['usage']=={'attempted_calls':1,'input_tokens':71,'output_tokens':30,'status':'OBSERVED'}
    assert report['call_observation']['attempt_started'] and report['call_observation']['response_observed']
    assert not report['call_observation']['failure_observed']
    assert not report['approved'] and not report['executed'] and not report['tool_executed'] and not report['conditions_confirmed']
    assert report['suggested_spec']['unresolved']==['AI_PROPOSAL_REQUIRES_HUMAN_CONDITION_CONFIRMATION']
    assert report['source_basis']['full_document_bytes_verified'] is False
    assert report['source_basis']['declared_document_sha256']=='a'*64
    finals_provider.complete_json.assert_called_once()
    kwargs=finals_provider.complete_json.call_args.kwargs
    assert kwargs['max_request_bytes']==proposals.research_agent.MAX_INPUT_BYTES
    assert kwargs['schema']['additionalProperties'] is False


def test_attempt_observed_before_failed_transport_no_retry(monkeypatch):
    client=Mock(side_effect=RuntimeError('external exception '+KEY))
    monkeypatch.setattr(finals_provider,'complete_json',client)
    report=call(api_key=KEY)
    assert report['usage']=={'attempted_calls':1,'input_tokens':None,'output_tokens':None,'status':'UNKNOWN'}
    assert report['call_observation']['failure_observed'] and not report['call_observation']['response_observed']
    assert report['error']=='PROPOSAL_UNAVAILABLE'
    assert KEY not in json.dumps(report)
    client.assert_called_once()


def test_http_failure_records_status_only(monkeypatch):
    monkeypatch.setattr(finals_provider,'complete_json',Mock(side_effect=finals_provider.ProviderError('MODEL_HTTP_429')))
    report=call()
    assert report['call_observation']['response_observed']
    assert report['call_observation']['http_status_observed']==429
    assert report['usage']['input_tokens'] is None
    assert report['usage']['attempted_calls']==1


@pytest.mark.parametrize('usage',[{}, {'input_tokens':True,'output_tokens':2}, {'input_tokens':-1,'output_tokens':2}, {'input_tokens':2,'output_tokens':None}])
def test_unknown_usage_is_not_zero(usage,monkeypatch):
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope(usage=usage)))
    report=call()
    assert report['error']=='USAGE_UNAVAILABLE' and report['usage']['status']=='UNKNOWN'
    assert report['usage']['input_tokens'] is None and report['usage']['output_tokens'] is None
    assert report['call_observation']['response_observed'] and report['call_observation']['failure_observed']


def test_invalid_output_preserves_valid_observed_usage(monkeypatch):
    bad=candidate();bad['approved']=True
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope(bad)))
    report=call()
    assert report['error']=='INVALID_PROPOSAL_SCHEMA'
    assert report['usage']['status']=='OBSERVED' and report['usage']['input_tokens']==71
    assert report['proposal'] is None and report['approved'] is False


@pytest.mark.parametrize('change,code',[('extra_condition','INVALID_PROPOSAL_SCHEMA'),('unknown_method','INVALID_PROPOSAL_SCHEMA'),
    ('negative_tolerance','INVALID_PROPOSAL_SCHEMA'),('boolean_number','INVALID_PROPOSAL_SCHEMA'),('unsupported_tool','INVALID_PROPOSAL_SCHEMA'),
    ('omitted_missing','MISSING_FIELDS_NOT_EXPLICIT'),('invented_quote','SOURCE_QUOTE_NOT_IN_EXCERPT'),
    ('wrong_source_id','SOURCE_ID_NOT_BOUND'),('invented_locator','SOURCE_LOCATOR_NOT_BOUND'),
    ('row_variable','ROW_COUNT_VARIABLE_INVALID'),('method_missing_verify','NEXT_TOOL_PRECONDITIONS_MISSING')])
def test_strict_structure_and_source_binding(change,code,monkeypatch):
    c=candidate()
    if change=='extra_condition':c['conditions']['confirmed']=True
    if change=='unknown_method':c['conditions']['method']='arbitrary_python'
    if change=='negative_tolerance':c['conditions']['tolerance']=-1
    if change=='boolean_number':c['conditions']['reported_value']=True
    if change=='unsupported_tool':c['next_tool']['name']='shell_exec'
    if change=='omitted_missing':c['conditions']['denominator']=None
    if change=='invented_quote':c['conditions']['source_location']['quote']='This never appears in the source.'
    if change=='wrong_source_id':c['conditions']['source_location']['source_id']='other-paper'
    if change=='invented_locator':c['conditions']['source_location']['locator']='Invented Table'
    if change=='row_variable':c['conditions']['variable']='x'
    if change=='method_missing_verify':c['conditions']['method']=None;c['missing']=['method']
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope(c)))
    assert call()['error']==code


def test_unknown_conditions_remain_null_and_listed(monkeypatch):
    c=candidate()
    c['conditions']={k:None for k in proposals.CONDITION_FIELDS}
    c['missing']=[k for k in proposals.CONDITION_FIELDS if k!='variable']
    c['next_tool']={'name':'manual_source_review','reason':'The excerpt does not establish the required calculation conditions.'}
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope(c)))
    report=call()
    assert report['success'] and report['proposal']['conditions']['denominator'] is None
    assert not report['conditions_confirmed']
    assert report['suggested_spec']['method'] is None


def test_caller_tool_subset_is_enforced(monkeypatch):
    report=call(allowed_tools=['manual_source_review','stop'])
    assert report['error']=='INVALID_PROPOSAL_SCHEMA'
    schema=finals_provider.complete_json.call_args.kwargs['schema']
    assert schema['properties']['next_tool']['properties']['name']['enum']==['manual_source_review','stop']


@pytest.mark.parametrize('tools',[[],['shell_exec'],['stop','stop'],[['stop']],'stop'])
def test_invalid_tool_whitelist_blocks_before_call(tools):
    assert call(allowed_tools=tools)['error']=='ALLOWED_TOOL_SET_INVALID'
    finals_provider.complete_json.assert_not_called()


def test_no_dataset_hash_cannot_propose_compute():
    report=proposals.propose_conditions(EXCERPT,PAPER,{},opted_in=True,session={})
    assert report['error']=='NEXT_TOOL_PRECONDITIONS_MISSING'


def test_output_key_reflection_is_not_reported(monkeypatch):
    c=candidate();c['limitations']=[KEY]
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope(c)))
    report=call(api_key=KEY)
    assert report['error']=='SECRET_IN_MODEL_OUTPUT'
    assert KEY not in json.dumps(report)


def test_input_key_reflection_blocks_without_call():
    report=proposals.propose_conditions(EXCERPT+KEY,PAPER,DATA,opted_in=True,session={},api_key=KEY)
    assert report['error']=='SECRET_IN_INPUT'
    finals_provider.complete_json.assert_not_called()


def test_personal_input_blocks_without_call():
    text='Contact synthetic'+chr(64)+'example.invalid'
    report=proposals.propose_conditions(text,PAPER,DATA,opted_in=True,session={})
    assert report['error']=='PERSONAL_OR_SECRET_INPUT'
    finals_provider.complete_json.assert_not_called()
    assert 'synthetic' not in json.dumps(report)


def test_auth_url_input_blocks_without_call():
    paper=deepcopy(PAPER);paper['source_url']='https://example.org/paper?api_key=mock-value'
    report=proposals.propose_conditions(EXCERPT,paper,DATA,opted_in=True,session={})
    assert report['error']=='AUTH_URL_NOT_ALLOWED'
    finals_provider.complete_json.assert_not_called()


def test_nonfinite_model_output_blocks_with_usage_kept(monkeypatch):
    c=candidate();c['conditions']['reported_value']=float('nan')
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope(c)))
    report=call()
    assert not report['success'] and report['usage']['status']=='OBSERVED'
    assert report['proposal'] is None


def test_existing_anthropic_client_and_decoder_reused(monkeypatch):
    response={'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(candidate())}],
              'usage':{'input_tokens':80,'output_tokens':40}}
    client=Mock(return_value=response)
    monkeypatch.setattr(proposals.research_agent,'_post_messages',client)
    report=call(provider='anthropic',model='claude-test-model',api_key=KEY)
    assert report['success'] and report['usage']['attempted_calls']==1 and report['usage']['input_tokens']==80
    client.assert_called_once(); finals_provider.complete_json.assert_not_called()
    payload=client.call_args.args[0]
    assert payload['max_tokens']==1800 and 'tools' not in payload


def test_anthropic_invalid_output_preserves_observed_usage(monkeypatch):
    response={'stop_reason':'max_tokens','content':[{'type':'text','text':'{}'}], 'usage':{'input_tokens':80,'output_tokens':40}}
    monkeypatch.setattr(proposals.research_agent,'_post_messages',Mock(return_value=response))
    report=call(provider='anthropic',model='claude-test-model',api_key=KEY)
    assert report['error']=='INCOMPLETE_MODEL_OUTPUT'
    assert report['usage']['status']=='OBSERVED' and report['usage']['output_tokens']==40


def test_declared_full_document_hash_does_not_change_source_evidence():
    report=call()
    assert report['source_basis']['status']=='USER_SUPPLIED_EXCERPT'
    assert report['source_basis']['full_document_bytes_verified'] is False
    assert report['source_basis']['declared_document_sha256']!=report['source_basis']['excerpt_sha256']


def test_provider_model_mismatch_is_not_fallback():
    assert call(model='different-model')['error']=='MODEL_NOT_ALLOWED'
    finals_provider.complete_json.assert_not_called()
    proposals.research_agent._post_messages.assert_not_called()


@pytest.mark.parametrize('bad',[{'not':'hash'},'short',123])
def test_declared_source_hash_requires_sha256_form(bad):
    paper=deepcopy(PAPER);paper['source_sha256']=bad
    report=proposals.propose_conditions(EXCERPT,paper,DATA,opted_in=True,session={})
    assert report['error']=='DECLARED_SOURCE_HASH_INVALID'
    finals_provider.complete_json.assert_not_called()


def test_malformed_external_error_is_safely_closed(monkeypatch):
    monkeypatch.setattr(finals_provider,'complete_json',Mock(side_effect=finals_provider.ProviderError({'unsafe':'external'})))
    report=call()
    assert report['error']=='PROPOSAL_UNAVAILABLE'
    assert report['usage']['status']=='UNKNOWN'
    assert 'unsafe' not in json.dumps(report)


def test_credential_field_blocks_without_provider_call():
    metadata=deepcopy(DATA);metadata['token']='mock-value'
    report=proposals.propose_conditions(EXCERPT,PAPER,metadata,opted_in=True,session={})
    assert report['error']=='CREDENTIAL_FIELD_NOT_ALLOWED'
    finals_provider.complete_json.assert_not_called()


def test_excerpt_byte_budget_blocks_without_call():
    report=proposals.propose_conditions('한'*3000,PAPER,DATA,opted_in=True,session={})
    assert report['error']=='EXCERPT_REQUIRED_OR_TOO_LARGE'
    finals_provider.complete_json.assert_not_called()


def test_strict_request_schema_and_local_schema_remain_valid():
    from jsonschema import Draft202012Validator
    schema=proposals.proposal_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator.check_schema(finals_provider.request_schema(schema))
    assert schema['properties']['conditions']['properties']['filters']['items']['properties']['operator']=={'type':'string','enum':['eq']}
    assert schema['properties']['next_tool']['properties']['name']['type']=='string'
    assert schema['properties']['conditions']['properties']['method']['type']==['string','null']


def test_server_key_cannot_be_used_as_model_identifier():
    report=call(provider='anthropic',model=KEY,api_key=KEY)
    assert report['error']=='SECRET_IN_MODEL_IDENTIFIER'
    proposals.research_agent._post_messages.assert_not_called()


@pytest.mark.parametrize('field',['access_token','refresh_token','client_secret'])
def test_credential_alias_blocks_before_provider(field):
    metadata=deepcopy(DATA);metadata[field]='mock-value'
    report=proposals.propose_conditions(EXCERPT,PAPER,metadata,opted_in=True,session={})
    assert report['error']=='CREDENTIAL_FIELD_NOT_ALLOWED'
    finals_provider.complete_json.assert_not_called()

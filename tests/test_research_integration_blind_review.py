"""Source-only blind review transport mocks; no keys or paid/live network traffic."""
# [작성: 0 이영 · Codex] 2026-10-01 05:03 KST — 전송 가림·원문 실제 위치·미확정 의미와 1+1 호출 예산을 합성 정상/공격 입력으로 검증한다. 실제 독립 모델 정확도나 유료 실행을 측정하지 않는다.
from copy import deepcopy
import hashlib
import json
from unittest.mock import Mock

import pytest
from core import research_integration_blind_review as blind
from core import research_integration_candidates as candidates
from core import research_integration_proposals as proposals
from evidence_gate.spec import empty_spec
from finals import finals_provider

QUOTE='We count all CSV rows: 4 observations without filtering. Missing policy: not_applicable. Tolerance: 0.'
SOURCE=('Methods\n'+QUOTE+'\nExcluded section\nB,KNOWN_COMPUTED_SENTINEL,PRIVATE_ROW_SENTINEL\n').encode()
RAW=b'group,score\nA,PRIVATE_ROW_SENTINEL\nB,123\n'
PAPER={'source_id':'synthetic-source','source_url':'https://example.org/original','paper_version':'publication-1'}
LOCATION={'source_id':'synthetic-source','locator':'Methods-1','quote':QUOTE}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def rc(source=SOURCE,locations=None):
    if locations is None:
        locations=[{'locator':'Methods-1','start_byte':0,'end_byte':source.find(b'Excluded section')}]
    return candidates.source_receipt_for_spans(source,source_url=PAPER['source_url'],paper_version=PAPER['paper_version'],spans=locations,source_kind='SYNTHETIC_ACTUAL_BYTES')


def spec():
    value=empty_spec('SYNTHETIC')
    value.update(method='row_count',reported_value=4,filters=[],unit='observations',missing_policy='not_applicable',
                 missing_tokens=[],denominator='all CSV rows',tolerance=0,data_fingerprint=sha(RAW),source_location=deepcopy(LOCATION))
    return value


def pool(s=None,source=SOURCE,receipt=None,contract=None,previous=None):
    s=spec() if s is None else s
    c={'contract_version':1,'paper_version':PAPER['paper_version'],'source_location':deepcopy(s['source_location']),
       'fields':{field:{'status':'fact','value':deepcopy(value),'evidence':{'locator':s['source_location']['locator'],'quote':s['source_location']['quote']}}
                 for field,value in candidates._spec_groups(s).items()}} if contract is None else contract
    return candidates.freeze_candidate(c,s,source_bytes=source,source_receipt=rc(source) if receipt is None else receipt,
            paper_context=PAPER,data_sha256=sha(RAW),candidate_id='candidate-1' if previous is None else 'candidate-2',existing_set=previous)


def output():
    return {'conditions':{'denominator':'all CSV rows','filters':[],'unit':'observations','missing_policy':'not_applicable',
                         'missing_tokens':[],'method':'row_count','variable':None,'reported_value':4,'tolerance':0,
                         'source_location':{'source_id':'synthetic-source','locator':blind.NEUTRAL_LOCATOR,'quote':QUOTE}},
            'missing':[],'next_tool':{'name':'manual_source_review','reason':'A human must review the source meaning.'},
            'limitations':['No automatic confirmation.']}


def envelope(value=None,usage=None):
    return {'provider':'openai','model':finals_provider.MODEL,'output':output() if value is None else value,
            'usage':{'input_tokens':85,'output_tokens':34} if usage is None else usage}


@pytest.fixture(autouse=True)
def mocked(monkeypatch):
    monkeypatch.setattr(candidates,'source_revision',lambda:'synthetic-engine-1')
    monkeypatch.setattr(finals_provider,'paid_call_allowed',lambda session=None:True)
    monkeypatch.setattr(finals_provider,'live_allowed',lambda:True)
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope()))
    monkeypatch.setattr(finals_provider,'_api_key',Mock(side_effect=AssertionError('No key file access')))
    monkeypatch.setattr(proposals.research_agent,'_post_messages',Mock(side_effect=AssertionError('Unexpected real Anthropic call')))


def call(frozen=None,**kwargs):
    frozen=pool() if frozen is None else frozen
    args={'source_bytes':SOURCE,'source_receipt':rc(),'paper_context':PAPER,
          'dataset_metadata':{'actual_sha256':sha(RAW),'columns':['group','score'],'public_dictionary':{}},
          'review_locations':['Methods-1'],'opted_in':True,'session':{'authenticated_member':'synthetic-member'}}
    args.update(kwargs)
    return blind.blind_review_conditions(frozen['candidate'],frozen,**args)


def test_one_source_only_call_and_six_normal_agreements():
    report=call()
    assert report['success'],report
    assert len(report['field_cards'])==6 and all(c['status']=='RECORDED_VALUES_AGREE' for c in report['field_cards'])
    assert report['blocking_fields']==[]
    assert not report['semantic_ready'] and not report['can_approve'] and not report['approved'] and not report['verified']
    assert not report['executed'] and report['calculation'] is None
    assert report['usage']['status']=='OBSERVED' and report['usage']['attempted_calls']==1
    assert report['receipt']['review_invocation_attempts']==1
    assert report['receipt']['provider_invocation_attempts']==1
    assert report['receipt']['paid_call_status']=='NOT_INDEPENDENTLY_OBSERVED'
    finals_provider.complete_json.assert_called_once(); finals_provider._api_key.assert_not_called()
    evidence=report['field_cards'][0]['evidence']
    assert evidence['actual_source_sha256']==sha(SOURCE) and evidence['locator']=='Methods-1'
    assert evidence['context_sha256']==rc()['locations']['Methods-1']['context_sha256']


def test_callback_sees_original_numbers_but_no_candidate_result_approval_or_rows(monkeypatch):
    s=spec();s['reported_value']=999123;s['source_location']['quote']='FIRST_CANDIDATE_QUOTE_SENTINEL'
    frozen=pool(s);seen=[]
    def callback(system,snapshot,**kwargs):
        seen.append(snapshot)
        text=json.dumps(snapshot)
        for forbidden in ['FIRST_CANDIDATE_QUOTE_SENTINEL','999123','B,','KNOWN_COMPUTED_SENTINEL','PRIVATE_ROW_SENTINEL',
                          'computed','approval','candidate_spec','source_condition_contract','selected_candidate','numerical_match']:
            assert forbidden not in text
        assert '4 observations' in text and snapshot['dataset_metadata']=={'columns':['group','score'],'public_dictionary':{}}
        assert set(snapshot['paper_context'])=={'source_id','source_url','paper_version','source_sha256','locator'}
        return envelope()
    monkeypatch.setattr(finals_provider,'complete_json',callback)
    metadata={'actual_sha256':sha(RAW),'columns':['group','score'],'raw_rows':RAW.decode(),'computed':999123,
              'approval':{'approved':True},'first_candidate':s}
    report=call(frozen,dataset_metadata=metadata)
    assert report['success'] and len(seen)==1
    assert not report['receipt']['frozen_candidate_values_sent'] and not report['receipt']['candidate_quote_field_sent']
    assert not report['receipt']['computed_results_sent'] and not report['receipt']['approval_values_sent']
    assert not report['receipt']['raw_dataset_rows_sent']


@pytest.mark.parametrize('opted_in',[False,None,0,1,'true'])
def test_no_boolean_consent_no_auth_config_or_call(opted_in,monkeypatch):
    auth=Mock(side_effect=AssertionError('No early config lookup'))
    monkeypatch.setattr(finals_provider,'paid_call_allowed',auth)
    report=call(opted_in=opted_in)
    assert report['error']=='EXPLICIT_OPT_IN_REQUIRED' and report['usage']['attempted_calls']==0
    auth.assert_not_called(); finals_provider.complete_json.assert_not_called()


@pytest.mark.parametrize('gate,error',[('paid_call_allowed','TEAM_AUTH_REQUIRED'),('live_allowed','LIVE_AI_NOT_ALLOWED')])
def test_auth_operator_gate_before_invocation(gate,error,monkeypatch):
    monkeypatch.setattr(finals_provider,gate,lambda *args,**kwargs:False)
    assert call()['error']==error
    finals_provider.complete_json.assert_not_called(); finals_provider._api_key.assert_not_called()


def test_stale_current_data_and_engine_block_before_call(monkeypatch):
    frozen=pool()
    assert call(frozen,dataset_metadata={'actual_sha256':'0'*64,'columns':['group']})['error']=='STALE_FROZEN_BINDINGS'
    monkeypatch.setattr(candidates,'source_revision',lambda:'synthetic-engine-2')
    assert call(frozen)['error']=='STALE_FROZEN_BINDINGS'
    finals_provider.complete_json.assert_not_called()


def test_declared_source_hash_alone_never_replaces_actual_bytes():
    report=call(source_bytes=None,paper_context=dict(PAPER,source_sha256=sha(SOURCE)))
    assert report['error']=='STALE_FROZEN_BINDINGS' and not report['success']
    finals_provider.complete_json.assert_not_called()


@pytest.mark.parametrize('locations',[[],['Unknown'],['Methods-1']*2,['Methods-1','X','Y','Z']])
def test_review_location_allowlist_and_count_before_call(locations):
    report=call(review_locations=locations)
    assert report['error'] in ('REVIEW_LOCATIONS_INVALID','REVIEW_LOCATION_NOT_BOUND')
    finals_provider.complete_json.assert_not_called()


def test_selected_large_context_rejected_before_call():
    source=(QUOTE+' '+'x'*8000+'\nExcluded section\nEnd').encode()
    frozen=pool(source=source)
    report=call(frozen,source_bytes=source,source_receipt=rc(source))
    assert report['error']=='REVIEW_CONTEXT_TOO_LARGE'
    finals_provider.complete_json.assert_not_called()


@pytest.mark.parametrize('change,error',[('quote','SOURCE_QUOTE_NOT_IN_EXCERPT'),('locator','SOURCE_LOCATOR_NOT_BOUND'),('extra','INVALID_PROPOSAL_SCHEMA')])
def test_model_quote_locator_and_schema_binding(change,error,monkeypatch):
    value=output()
    if change=='quote':value['conditions']['source_location']['quote']='An invented result.'
    if change=='locator':value['conditions']['source_location']['locator']='Fake Table'
    if change=='extra':value['approved']=True
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope(value)))
    report=call()
    assert report['error']==error and report['usage']['status']=='OBSERVED' and not report['semantic_ready']
    finals_provider.complete_json.assert_called_once()


def test_duplicate_quote_across_two_actual_locations_is_not_arbitrarily_selected():
    source=(QUOTE+'\n'+QUOTE).encode();n=len(QUOTE.encode())
    receipt=rc(source,[{'locator':'Methods-1','start_byte':0,'end_byte':n},{'locator':'Methods-2','start_byte':n+1,'end_byte':len(source)}])
    frozen=pool(source=source,receipt=receipt)
    report=call(frozen,source_bytes=source,source_receipt=receipt,review_locations=['Methods-1','Methods-2'])
    assert report['error']=='INDEPENDENT_QUOTE_LOCATION_NOT_UNIQUE_OR_BOUND' and not report['success']
    finals_provider.complete_json.assert_called_once()


@pytest.mark.parametrize('field,value',[('denominator','n=2'),('unit','mg'),('filters',[{'column':'group','operator':'eq','value':'A'}]),
                                       ('missing_policy','complete_case'),('reported_value',3),('tolerance',1)])
def test_mismatch_or_unstated_independent_value_is_manual_not_auto_confirmed(field,value,monkeypatch):
    response=output();response['conditions'][field]=value
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope(response)))
    report=call();assert report['success'],report
    group='missing' if field=='missing_policy' else 'calculation' if field in ('reported_value','tolerance') else field
    card=next(card for card in report['field_cards'] if card['field']==group)
    assert card['status'] in ('MISMATCH','INDEPENDENT_VALUE_NOT_SUPPORTED_BY_QUOTE','ROW_DICTIONARY_REQUIRED')
    assert group in report['blocking_fields'] and not report['semantic_ready'] and not report['can_approve']


def test_missing_source_conditions_remain_null_and_blocking(monkeypatch):
    value=output();value['conditions']['unit']=None;value['conditions']['denominator']=None;value['missing']=['denominator','unit']
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope(value)))
    report=call()
    assert report['success']
    for field in ('unit','denominator'):
        card=next(c for c in report['field_cards'] if c['field']==field)
        assert card['independently_extracted_value'] is None and card['status']=='MISSING_INDEPENDENT_EVIDENCE'
        assert field in report['blocking_fields']


def test_no_row_dictionary_never_infers_n_people(monkeypatch):
    quote=QUOTE.replace('all CSV rows','n=4')
    source=('Methods\n'+quote+'\nExcluded section\nEnd').encode()
    s=spec();s['denominator']='n=4';s['source_location']['quote']=quote
    value=output();value['conditions']['denominator']='n=4';value['conditions']['source_location']['quote']=quote
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope(value)))
    frozen=pool(s,source=source)
    report=call(frozen,source_bytes=source,source_receipt=rc(source))
    assert 'denominator' in report['blocking_fields']
    assert next(c for c in report['field_cards'] if c['field']=='denominator')['status']=='ROW_DICTIONARY_REQUIRED'
    assert 'row_dictionary' not in finals_provider.complete_json.call_args.args[1]['dataset_metadata']


def test_public_dictionary_kept_but_not_inferred():
    data={'actual_sha256':sha(RAW),'columns':['group','score'],'public_dictionary':{'score':'Public measurement in points'},
          'row_dictionary':'One CSV observation; distinct-person identity is not supplied.'}
    report=call(dataset_metadata=data)
    assert report['success']
    meta=finals_provider.complete_json.call_args.args[1]['dataset_metadata']
    assert meta['public_dictionary']==data['public_dictionary'] and meta['row_dictionary']==data['row_dictionary']


def test_once_per_pool_including_failed_attempt_and_no_secret_reflection(monkeypatch):
    key='not-a-real-review-key'
    provider=Mock(side_effect=RuntimeError('external detail '+key))
    monkeypatch.setattr(finals_provider,'complete_json',provider)
    session={'authenticated_member':'synthetic-member'};frozen=pool()
    first=call(frozen,session=session,api_key=key)
    assert first['error']=='PROPOSAL_UNAVAILABLE' and first['usage']['status']=='UNKNOWN'
    assert first['receipt']['review_invocation_attempts']==1 and first['receipt']['provider_invocation_attempts']==1
    assert key not in json.dumps(first)
    second=call(frozen,session=session)
    assert second['error']=='REEXTRACTION_ALREADY_ATTEMPTED' and second['usage']['attempted_calls']==0
    provider.assert_called_once()


def test_previous_review_receipt_also_prevents_an_automatic_repeat():
    frozen=pool();first=call(frozen)
    second=call(frozen,previous_review=first)
    assert second['error']=='REEXTRACTION_ALREADY_ATTEMPTED'
    finals_provider.complete_json.assert_called_once()


def test_two_call_budget_observed_prior_receipt_and_bad_prior_count():
    frozen=pool();bad=call(frozen,prior_proposal_receipt={'usage':{'attempted_calls':2}})
    assert bad['error']=='TOTAL_PROPOSAL_REVIEW_BUDGET_EXCEEDED'
    finals_provider.complete_json.assert_not_called()
    report=call(frozen,prior_proposal_receipt={'usage':{'attempted_calls':1}})
    assert report['success'] and report['budget']['max_total_invocations']==2
    assert report['budget']['proposal_invocations']==1 and report['receipt']['review_invocation_attempts']==1
    finals_provider.complete_json.assert_called_once()


def test_new_frozen_pool_is_a_distinct_explicit_review():
    session={'authenticated_member':'synthetic-member'};first=pool()
    assert call(first,session=session)['success']
    second=pool(previous=first)
    assert second['candidate_set_sha256']!=first['candidate_set_sha256']
    assert call(second,session=session)['success']
    assert finals_provider.complete_json.call_count==2


def test_engine_changed_during_response_is_blocked(monkeypatch):
    frozen=pool()
    def response(*args,**kwargs):
        monkeypatch.setattr(candidates,'source_revision',lambda:'changed-engine')
        return envelope()
    monkeypatch.setattr(finals_provider,'complete_json',response)
    report=call(frozen)
    assert report['error']=='ENGINE_CHANGED_DURING_BLIND_REVIEW' and not report['success']
    assert report['usage']['status']=='OBSERVED'


def test_invalid_public_dictionary_and_private_description_before_call():
    data={'actual_sha256':sha(RAW),'columns':['group'],'public_dictionary':{'missing-column':'Inferred description'}}
    assert call(dataset_metadata=data)['error']=='PUBLIC_DICTIONARY_INVALID'
    data['public_dictionary']={'group':'Contact synthetic-person@example.org'}
    assert call(dataset_metadata=data)['error']=='PERSONAL_OR_SECRET_INPUT'
    finals_provider.complete_json.assert_not_called()


def test_unknown_usage_stays_unknown_no_second_attempt(monkeypatch):
    monkeypatch.setattr(finals_provider,'complete_json',Mock(return_value=envelope(usage={})))
    report=call()
    assert report['error']=='USAGE_UNAVAILABLE' and report['usage']['status']=='UNKNOWN'
    assert report['usage']['input_tokens'] is None and report['usage']['output_tokens'] is None
    assert report['receipt']['provider_invocation_attempts']==1
    finals_provider.complete_json.assert_called_once()


def test_per_field_proposals_never_called():
    report=call();assert len(report['field_cards'])==6
    finals_provider.complete_json.assert_called_once()
    assert all(card['evidence']['actual_source_sha256']==sha(SOURCE) for card in report['field_cards'])


# [수정: 0 이영 · Codex] 2026-10-01 05:27 KST — 느린 모델 응답 중 사전/후보/자료/위치가 바뀌면 이전 답을 카드나 승인 상태에 붙이지 않는다. 실패도 기존 단일 호출 예약을 소비한다.
@pytest.mark.parametrize('dimension',['candidate','pool','receipt','paper','data','columns','dictionary','locations'])
def test_late_response_cannot_attach_to_changed_live_input(dimension,monkeypatch):
    frozen=pool();receipt=rc();paper=deepcopy(PAPER)
    data={'actual_sha256':sha(RAW),'columns':['group','score'],'public_dictionary':{}}
    locations=['Methods-1'];session={'authenticated_member':'synthetic-member'}
    def response(*args,**kwargs):
        if dimension=='candidate':frozen['candidate']['candidate_spec']['reported_value']=99
        elif dimension=='pool':frozen['candidates'].append(deepcopy(frozen['candidate']))
        elif dimension=='receipt':receipt['locations']['Methods-1']['start_byte']=1
        elif dimension=='paper':paper['paper_version']='publication-2'
        elif dimension=='data':data['actual_sha256']='0'*64
        elif dimension=='columns':data['columns'].append('new_column')
        elif dimension=='dictionary':data['public_dictionary']['score']='Changed public units dictionary'
        else:locations.append('Unbound-location')
        return envelope()
    provider=Mock(side_effect=response);monkeypatch.setattr(finals_provider,'complete_json',provider)
    report=call(frozen,source_receipt=receipt,paper_context=paper,dataset_metadata=data,review_locations=locations,session=session)
    assert report['error']=='STALE_BLIND_REVIEW_INPUTS' and report['status']=='STALE'
    assert report['field_cards']==[] and report['usage']['status']=='OBSERVED'
    assert not report['semantic_ready'] and not report['can_approve'] and not report['approved']
    assert report['receipt']['review_invocation_attempts']==1 and session[blind.BUDGET_KEY][report['candidate_set_sha256']]==1
    provider.assert_called_once()


def test_post_response_recheck_preserves_matching_original_snapshot():
    report=call();assert report['success']
    assert report['receipt']['post_response_inputs_rechecked'] is True
    assert report['receipt']['post_response_neutral_snapshot_sha256']==report['blind_input_snapshot_sha256']


def test_observation_only_time_change_during_model_response_is_not_semantic_change(monkeypatch):
    receipt=rc()
    def response(*args,**kwargs):
        receipt['bound_at_kst']='2026-10-01T05:27:01+09:00'
        return envelope()
    monkeypatch.setattr(finals_provider,'complete_json',Mock(side_effect=response))
    report=call(source_receipt=receipt)
    assert report['success'] and report['receipt']['post_response_inputs_rechecked']
    finals_provider.complete_json.assert_called_once()

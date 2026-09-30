"""Mock-only Cloud settings, bounded OpenAI transport, research, and paid UI tests."""
# [작성: 0 이영] 2026-10-01 01:13 KST — 실키/실호출 없이 Cloud 타입·응답·usage·인용·2시도·팀 인증·동의·키 비노출을 검증한다.
import json
from pathlib import Path
import tomllib
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from finals import finals_provider as provider
from core import research_agent as agent, research_assistant_ui as ui, team_workspace as team

KEY = "MockOnly-ServerSetting-ForTests"
EVIDENCE = [{"id":"mock-e1","text":"This synthetic excerpt supports the mock statement.","doi":"10.1234/mock","locator":"synthetic p.1"}]
DRAFT = {"answer":"Synthetic supported draft.","citations":["mock-e1"],"limitations":["Synthetic fixture only."]}
CRITIC = {"supported":True,"issues":[]}
HASH = "pbkdf2_sha256$" + "a"*32 + "$" + "b"*64


@pytest.fixture(autouse=True)
def isolate_runtime(monkeypatch, tmp_path):
    for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','NAIS_AGENT_MODEL','NAIS_AGENT_ENABLED','NAIS_AGENT_PROVIDER','EVIDENCE_GATE_LOCAL_MODE','EVIDENCE_GATE_LOCAL_ROLE','NAIS_ALLOW_LIVE_AI','NAIS_LIVE_CALL_LIMIT'):
        monkeypatch.delenv(key, raising=False)
    # [수정: 0 이영] 2026-10-01 01:35 KST — 양성 모의 전송만 명시 허용하고 프로세스 예산을 시험별 격리한다. 실제 전송은 아래에서 계속 금지한다.
    monkeypatch.setenv('NAIS_ALLOW_LIVE_AI', '1')
    monkeypatch.setenv('NAIS_LIVE_CALL_LIMIT', '100')
    monkeypatch.setattr(provider, '_LIVE_CALLS', {'n':0})
    monkeypatch.setenv('NAIS_SECRETS_FILE', str(tmp_path/'nonexistent-secret-file'))
    monkeypatch.setattr(st, 'secrets', {})
    monkeypatch.setattr(agent, 'load_knowledge', lambda: ({}, 'mock-knowledge-sha'))
    monkeypatch.setattr(agent, 'forbidden_claims', lambda: [])
    monkeypatch.setattr(agent, 'known_error_cases', lambda _: [])
    monkeypatch.setattr(provider.http.client, 'HTTPSConnection', lambda *a,**k: pytest.fail('Real network forbidden'))


@pytest.mark.parametrize('config', [{'OPENAI_API_KEY':KEY}, {'openai':{'api_key':KEY}}, {'OPENAI_API_KEY':'','openai':{'api_key':KEY}}])
def test_cloud_secret_formats(config, monkeypatch):
    monkeypatch.setattr(st, 'secrets', config)
    assert provider._api_key() == KEY
    status = provider.availability()
    assert status['available'] is True and status['request_status']=='NOT_CHECKED'
    assert KEY not in json.dumps(status)


@pytest.mark.parametrize('config', [{'OPENAI_API_KEY':True}, {'OPENAI_API_KEY':None}, {'openai':[]}, {'openai':{'api_key':42}}, {'openai':{'api_key':'bad internal space'}}])
def test_invalid_cloud_key_type_fails_closed(config, monkeypatch):
    monkeypatch.setattr(st, 'secrets', config)
    with pytest.raises(provider.ProviderError, match='MODEL_KEY_UNAVAILABLE'):
        provider._api_key()
    assert provider.availability()['available'] is False


def test_environment_priority_and_absent_key(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', KEY)
    monkeypatch.setattr(st,'secrets',{'OPENAI_API_KEY':True})
    assert provider._api_key() == KEY
    monkeypatch.delenv('OPENAI_API_KEY')
    monkeypatch.setattr(st,'secrets',{})
    assert not provider.availability()['available']


def mock_http(monkeypatch, output=DRAFT, status=200):
    observed = []
    envelope={'status':'completed','id':'mock-response','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(output)}]}],'usage':{'input_tokens':11,'output_tokens':7}}
    class Response:
        def read(self, limit):
            observed.append(('read',limit))
            assert status==200, 'Error bodies must not be read'
            return json.dumps(envelope).encode()
    Response.status=status
    class Connection:
        def __init__(self,host,timeout):observed.append(('connect',host,timeout))
        def request(self,method,path,body,headers):observed.append(('request',method,path,json.loads(body),headers))
        def getresponse(self):return Response()
        def close(self):observed.append(('close',))
    monkeypatch.setattr(provider.http.client,'HTTPSConnection',Connection)
    return observed


def test_responses_fixed_host_model_strict_store_and_actual_usage(monkeypatch):
    observed=mock_http(monkeypatch)
    result=provider.complete_json('Mock instructions',{'question':'Mock'},schema=agent.DRAFT_SCHEMA,api_key=KEY,max_request_bytes=48000)
    request=next(row for row in observed if row[0]=='request')
    assert request[1:3]==('POST','/v1/responses')
    body=request[3]
    assert body['model']=='gpt-4.1-mini' and body['store'] is False and body['max_output_tokens']==1800
    assert body['text']['format']['strict'] is True and 'tools' not in body
    assert next(row for row in observed if row[0]=='connect')[1]=='api.openai.com'
    assert result['usage']=={'input_tokens':11,'output_tokens':7}
    assert result['provider']=='openai' and result['model']==provider.MODEL
    assert KEY not in json.dumps(body) and KEY not in json.dumps(result)
    assert len([r for r in observed if r[0]=='request'])==1
    assert observed[-1]==('close',)


@pytest.mark.parametrize('status',[302,401,429,500])
def test_http_failure_never_reads_body_or_retries(status,monkeypatch):
    observed=mock_http(monkeypatch,status=status)
    with pytest.raises(provider.ProviderError,match='MODEL_HTTP_'+str(status)):
        provider.complete_json('Mock',{},api_key=KEY)
    assert not any(r[0]=='read' for r in observed)
    assert len([r for r in observed if r[0]=='request'])==1 and observed[-1]==('close',)


def test_key_reflection_and_smaller_budget_are_blocked(monkeypatch):
    with pytest.raises(provider.ProviderError,match='SECRET_IN_REQUEST'):
        provider.complete_json('Mock',{'text':KEY},api_key=KEY)
    with pytest.raises(provider.ProviderError,match='REQUEST_TOO_LARGE'):
        provider.complete_json('Mock',{'text':'x'*1000},api_key=KEY,max_request_bytes=100)
    mock_http(monkeypatch,output={'answer':KEY})
    with pytest.raises(provider.ProviderError,match='SECRET_IN_MODEL_OUTPUT') as error:
        provider.complete_json('Mock',{},api_key=KEY)
    assert KEY not in str(error.value)


def fake_openai(monkeypatch, values):
    calls=[]
    iterator=iter(values)
    def complete(system,payload,**kwargs):
        calls.append((system,payload,kwargs))
        value=next(iterator)
        if isinstance(value,Exception):raise value
        return {'output':value,'usage':{'input_tokens':100 if len(calls)==1 else 60,'output_tokens':12 if len(calls)==1 else 5},'provider':'openai','model':provider.MODEL}
    monkeypatch.setattr(provider,'complete_json',complete)
    monkeypatch.setattr(agent,'_post_messages',lambda *a,**k:pytest.fail('No provider fallback'))
    return calls


def test_openai_two_roles_strict_validation_real_usage_and_no_approval(monkeypatch):
    calls=fake_openai(monkeypatch,[DRAFT,CRITIC])
    result=agent.run_research_agent('Mock question',EVIDENCE,api_key=KEY,model=provider.MODEL,provider='openai')
    assert result['status']=='READY' and result['answer']==DRAFT['answer']
    assert result['usage']=={'calls':2,'input_tokens':160,'output_tokens':17}
    assert result['approved'] is False and result['executed'] is False
    assert result['provider']=='openai' and result['model']==provider.MODEL
    assert calls[0][2]['schema']==agent.DRAFT_SCHEMA and calls[1][2]['schema']==agent.CRITIC_SCHEMA
    assert all(call[2]['max_request_bytes']==48000 and call[2]['timeout']==30 for call in calls)
    assert calls[1][1]['proposal']==DRAFT
    assert KEY not in json.dumps(result)


@pytest.mark.parametrize('draft,critic,attempts',[
    ({'answer':'x','citations':['not-supplied'],'limitations':[]},CRITIC,1),
    (dict(DRAFT,extra='wrong'),CRITIC,1),
    (DRAFT,{'supported':False,'issues':['unsupported']},2),
    (DRAFT,{'supported':True,'issues':['unresolved']},2),
    (DRAFT,{'supported':'true','issues':[]},2),
    (DRAFT,{'supported':True,'issues':[],'extra':'wrong'},2),
    (dict(DRAFT,answer=KEY),CRITIC,1),
])
def test_model_output_errors_block_without_approval_or_key_leak(draft,critic,attempts,monkeypatch):
    calls=fake_openai(monkeypatch,[draft,critic])
    result=agent.run_research_agent('Mock question',EVIDENCE,api_key=KEY,model=provider.MODEL,provider='openai')
    assert result['status']=='BLOCKED' and not result['answer']
    assert result['usage']['calls']==attempts and len(calls)==attempts
    assert not result['approved'] and not result['executed']
    assert KEY not in json.dumps(result)


def test_provider_exception_is_sanitized_and_not_retried(monkeypatch):
    calls=fake_openai(monkeypatch,[provider.ProviderError(KEY)])
    result=agent.run_research_agent('Mock question',EVIDENCE,api_key=KEY,model=provider.MODEL,provider='openai')
    assert result['status']=='BLOCKED' and len(calls)==1 and result['usage']['calls']==1
    assert result['usage']['input_tokens'] is None and KEY not in json.dumps(result)


@pytest.mark.parametrize('key,model,kind',[(None,provider.MODEL,'openai'),(KEY,'unbounded-model','openai'),(KEY,provider.MODEL,'unknown')])
def test_invalid_call_configuration_stops_before_transport(key,model,kind,monkeypatch):
    calls=fake_openai(monkeypatch,[])
    result=agent.run_research_agent('Mock question',EVIDENCE,api_key=key,model=model,provider=kind)
    assert result['status']=='BLOCKED' and result['usage']['calls']==0 and not calls


def test_anthropic_default_remains_two_messages(monkeypatch):
    calls=[];outputs=iter([DRAFT,CRITIC])
    def post(payload,api_key):
        calls.append(payload)
        return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(next(outputs))}],'usage':{'input_tokens':3,'output_tokens':2}}
    monkeypatch.setattr(agent,'_post_messages',post)
    result=agent.run_research_agent('Mock question',EVIDENCE,api_key=KEY,model='claude-mock')
    assert result['status']=='READY' and result['provider']=='anthropic'
    assert result['usage']=={'calls':2,'input_tokens':6,'output_tokens':4}
    assert len(calls)==2 and all(p['model']=='claude-mock' for p in calls)


@pytest.mark.parametrize('role,expected',[('ADMIN',True),('REVIEWER',True),('VIEWER',False),('APPROVER',False),('UNKNOWN',False)])
def test_paid_gate_checks_existing_operating_roles(role,expected,monkeypatch):
    monkeypatch.setattr(team,'settings',lambda:{'password_hashes':{m:HASH for m in team.MEMBERS}})
    monkeypatch.setattr(team,'member_role',lambda _:role)
    assert provider.paid_call_allowed({'authenticated_member':'이영'}) is expected


def test_paid_gate_rejects_public_local_missing_hash_and_bad_identity(monkeypatch):
    monkeypatch.setattr(team,'settings',lambda:{'password_hashes':{m:HASH for m in team.MEMBERS}})
    assert not provider.paid_call_allowed({})
    assert not provider.paid_call_allowed({'authenticated_member':'outsider'})
    monkeypatch.setenv('EVIDENCE_GATE_LOCAL_MODE','1')
    assert not provider.paid_call_allowed({'authenticated_member':'이영'})
    monkeypatch.delenv('EVIDENCE_GATE_LOCAL_MODE')
    monkeypatch.setattr(team,'settings',lambda:{'password_hashes':{m:'' for m in team.MEMBERS}})
    assert not provider.paid_call_allowed({'authenticated_member':'이영'})


def test_ui_provider_settings_keep_server_key_and_legacy_anthropic(monkeypatch):
    monkeypatch.setattr(st,'secrets',{'openai':{'api_key':KEY},'research_agent':{'provider':'openai','enabled':True,'api_key':'Mock-Anthropic-Setting','model':'claude-mock'}})
    selected=ui.provider_settings()
    assert selected['provider']=='openai' and selected['api_key']==KEY and selected['model']==provider.MODEL and selected['enabled']
    legacy=ui.provider_settings('anthropic')
    assert legacy['api_key']=='Mock-Anthropic-Setting' and legacy['model']=='claude-mock'
    assert ui.provider_settings('unknown')['enabled'] is False
    monkeypatch.setattr(st,'secrets',{'research_agent':{'provider':[]}})
    assert ui.provider_settings()['enabled'] is False
    monkeypatch.setattr(st,'secrets',{'openai':{'api_key':True}})
    assert ui.provider_settings('openai')['api_key']==''


def prepare_ui(monkeypatch,authorized):
    monkeypatch.setattr(st,'secrets',{'openai':{'api_key':KEY},'research_agent':{'provider':'openai','enabled':True}})
    monkeypatch.setattr(ui,'_registered_replay',lambda:None)
    monkeypatch.setattr(ui,'_metadata_watch',lambda:None)
    monkeypatch.setattr(ui,'search_evidence',lambda *a,**k:EVIDENCE)
    monkeypatch.setattr(provider,'paid_call_allowed',lambda *a,**k:authorized)
    calls=[]
    def run(*a,**kwargs):
        calls.append(kwargs)
        return {'status':'READY','answer':'Synthetic answer '+KEY,'citations':['mock-e1'],'limitations':['synthetic'],'steps':[],'usage':{'calls':2,'input_tokens':12,'output_tokens':3},'provider':'openai','model':provider.MODEL}
    monkeypatch.setattr(ui,'run_research_agent',run)
    app=AppTest.from_string('from core.research_assistant_ui import render_research_assistant\nrender_research_assistant()',default_timeout=30).run()
    app.text_area(key='research_question').set_value('Mock question').run()
    app.button(key='research_search').click().run()
    assert not app.exception
    return app,calls


def test_ui_blocks_unauthed_even_when_key_and_enabled_exist(monkeypatch):
    app,calls=prepare_ui(monkeypatch,False)
    assert app.checkbox(key='research_consent').disabled
    assert app.button(key='research_run').disabled and not calls


def test_ui_explicit_consent_openai_selection_and_redacted_report(monkeypatch):
    app,calls=prepare_ui(monkeypatch,True)
    assert app.selectbox(key='research_provider').value=='openai'
    assert app.button(key='research_run').disabled and not calls
    app.checkbox(key='research_consent').check().run()
    app.button(key='research_run').click().run()
    assert not app.exception and len(calls)==1 and calls[0]['provider']=='openai'
    assert KEY not in str(app.get('text')) and KEY not in str(app.get('markdown'))
    stored=app.session_state['research_result']
    assert KEY not in json.dumps(stored['report'])
    app.selectbox(key='research_provider').select('anthropic').run()
    assert 'research_result' not in app.session_state and app.checkbox(key='research_consent').value is False


def test_blank_example_and_no_real_configuration():
    root=Path(__file__).resolve().parents[1]
    example=tomllib.loads((root/'.streamlit/secrets.toml.example').read_text(encoding='utf-8'))
    assert example['openai']['api_key']=='' and example['research_agent']['enabled'] is False


# [작성: 0 이영] 2026-10-01 01:23 KST — 버튼 활성 이후 팀 인증이 바뀌어도 서버 호출 직전 재검사에서 전송을 차단한다.
def test_ui_rechecks_team_authentication_immediately_before_call(monkeypatch):
    app,calls=prepare_ui(monkeypatch,True)
    app.checkbox(key='research_consent').check().run()
    checks=[]
    def authorized():
        checks.append(1)
        return len(checks)==1
    monkeypatch.setattr(provider,'paid_call_allowed',authorized)
    app.button(key='research_run').click().run()
    assert not app.exception and len(checks)==2 and not calls
    assert 'research_result' not in app.session_state
    assert app.error and KEY not in str(app.error)


# [작성: 0 이영] 2026-10-01 01:35 KST — 키가 있어도 운영 허용이 없거나 프로세스 예산이 소진되면 HTTP 생성 자체가 없어야 한다.
def test_live_disabled_blocks_before_network(monkeypatch):
    # [수정: 0 이영] 2026-10-01 01:51 KST — 기본 횟수 한도와 독립된 명시 운영 중지 값 0을 검사한다.
    monkeypatch.setenv('NAIS_ALLOW_LIVE_AI','0')
    connections=[]
    def forbidden(*args,**kwargs):
        connections.append(1)
        pytest.fail('Disabled live mode must not connect')
    monkeypatch.setattr(provider.http.client,'HTTPSConnection',forbidden)
    with pytest.raises(provider.ProviderError,match='LIVE_AI_NOT_ALLOWED'):
        provider.complete_json('Mock',{},api_key=KEY)
    assert not connections and provider._LIVE_CALLS['n']==0


def test_live_zero_or_exhausted_budget_blocks_before_network(monkeypatch):
    connections=[]
    def forbidden(*args,**kwargs):
        connections.append(1)
        pytest.fail('Exhausted process budget must not connect')
    monkeypatch.setattr(provider.http.client,'HTTPSConnection',forbidden)
    for limit, used in [('0',0),('1',1)]:
        monkeypatch.setenv('NAIS_LIVE_CALL_LIMIT',limit)
        provider._LIVE_CALLS['n']=used
        with pytest.raises(provider.ProviderError,match='LIVE_AI_BUDGET_EXHAUSTED'):
            provider.complete_json('Mock',{},api_key=KEY)
        assert not connections and provider._LIVE_CALLS['n']==used


# [작성: 0 이영] 2026-10-01 01:51 KST — 승인된 기본 무횟수 상한은 명시 live 허용 후 모의 전송으로만 검증한다.
def test_default_negative_count_limit_unlimited_with_live_opt_in(monkeypatch):
    monkeypatch.delenv('NAIS_LIVE_CALL_LIMIT')
    assert provider.live_allowed() is True
    assert provider.DEFAULT_CALL_LIMIT==-1 and provider._call_limit()==-1
    provider._LIVE_CALLS['n']=10000
    observed=mock_http(monkeypatch)
    provider.complete_json('Mock',{},api_key=KEY)
    monkeypatch.setenv('NAIS_LIVE_CALL_LIMIT','-1')
    assert provider._call_limit()==-1
    provider.complete_json('Mock',{},api_key=KEY)
    assert len([row for row in observed if row[0]=='request'])==2
    assert provider._LIVE_CALLS['n']==10002

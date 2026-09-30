"""Opt-in condition and allowed-tool proposals; no calculation, fetch or approval."""
# [작성: 0 이영 · Codex] 2026-10-01 03:28 KST — 기존 모델 전송기를 재사용해 여섯 조건 후보만 생성하며 호출 시도·실패·미확인 사용량을 분리한다. 모의 회귀로 검증하고 실제 유료 호출은 하지 않는다.
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from time import perf_counter
from urllib.parse import parse_qs, urlsplit

from jsonschema import Draft202012Validator
from core import research_agent
from evidence_gate.spec import METHODS, empty_spec, validate as validate_spec
from finals import finals_provider
from finals.finals_privacy import sensitive_kinds

MAX_EXCERPT_BYTES = 8000
MAX_CONTEXT_BYTES = 24000
ALLOWED_TOOLS = ('repository_record', 'acquisition', 'verify_download', 'manual_source_review', 'stop')
CONDITION_FIELDS = ('denominator', 'filters', 'unit', 'missing_policy', 'missing_tokens', 'method', 'variable',
                    'reported_value', 'tolerance', 'source_location')
SYSTEM = research_agent.UNTRUSTED + (
    'Propose six groups of analysis conditions: denominator; inclusion/exclusion filters; unit; missing-data policy and tokens; '
    'calculation method, variable, reported value and tolerance; original source location. '
    'Use null for every condition not directly stated in the supplied excerpt or explicit source context. '
    'List every missing field. Never infer a denominator, missing policy, filter or tolerance from conventions. '
    'Use verbatim source quotes. Select only one supplied allowed next tool and explain why; do not execute it. '
    'These are unconfirmed proposals, never facts, approval, full-paper reproduction or execution instructions. '
    'If source context is insufficient, propose manual_source_review or stop. Return only the requested JSON object.')


def _nullable(kind, **extra):
    return {'type': [kind, 'null'], **extra}


# [수정: 0 이영 · Codex] 2026-10-01 03:50 KST — 기존 strict Responses 요청에도 enum의 자료형을 명시하고 const 대신 허용값 목록을 사용한다. SDK는 재작성하지 않고 원본 schema를 로컬에서 다시 검사한다.
def proposal_schema(tools=ALLOWED_TOOLS):
    location = {'type': ['object','null'], 'properties': {k: {'type':'string','minLength':1,'maxLength':n}
                for k,n in (('source_id',128),('locator',512),('quote',4000))},
                'required':['source_id','locator','quote'],'additionalProperties':False}
    filters = {'type':['array','null'],'maxItems':8,'items':{'type':'object',
               'properties':{'column':{'type':'string','minLength':1,'maxLength':128},'operator':{'type':'string','enum':['eq']},
                             'value':{'type':['string','number']}},'required':['column','operator','value'],'additionalProperties':False}}
    conditions = {'denominator':_nullable('string',minLength=1,maxLength=2000), 'filters':filters,
                  'unit':_nullable('string',minLength=1,maxLength=256),
                  'missing_policy':{'type':['string','null'],'enum':['error','complete_case','not_applicable',None]},
                  'missing_tokens':{'type':['array','null'],'maxItems':16,'uniqueItems':True,'items':{'type':'string','maxLength':32}},
                  'method':{'type':['string','null'],'enum':[*METHODS,None]}, 'variable':_nullable('string',minLength=1,maxLength=128),
                  'reported_value':_nullable('number'),'tolerance':_nullable('number',minimum=0), 'source_location':location}
    props={'conditions':{'type':'object','properties':conditions,'required':list(CONDITION_FIELDS),'additionalProperties':False},
           'missing':{'type':'array','maxItems':len(CONDITION_FIELDS),'uniqueItems':True,'items':{'type':'string','enum':list(CONDITION_FIELDS)}},
           'next_tool':{'type':'object','properties':{'name':{'type':'string','enum':list(tools)},'reason':{'type':'string','minLength':1,'maxLength':1500}},
                        'required':['name','reason'],'additionalProperties':False},
           'limitations':{'type':'array','maxItems':12,'items':{'type':'string','minLength':1,'maxLength':1500}}}
    return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}


class ProposalError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _public(value):
    if sensitive_kinds(value):
        raise ProposalError('PERSONAL_OR_SECRET_INPUT')
    def walk(item):
        if isinstance(item,dict):
            if any(re.fullmatch(r'(?:api_key|token|access_token|refresh_token|secret|client_secret|password|authorization|credentials)',str(k),re.I) for k in item):
                raise ProposalError('CREDENTIAL_FIELD_NOT_ALLOWED')
            for val in item.values(): walk(val)
        elif isinstance(item,list):
            for val in item:walk(val)
        elif isinstance(item,str) and item.lower().startswith(('https://','http://')):
            try:
                parts=urlsplit(item)
                query=parse_qs(parts.query)
            except ValueError:
                raise ProposalError('SOURCE_URL_INVALID') from None
            if parts.username or parts.password or any(re.search(r'key|token|secret|password|authorization',k,re.I) for k in query):
                raise ProposalError('AUTH_URL_NOT_ALLOWED')
    walk(value)
    _canonical(value)


def _tools(tools):
    if tools is None:return ALLOWED_TOOLS
    if not isinstance(tools,(list,tuple)) or not tools or len(tools)>len(ALLOWED_TOOLS) or any(not isinstance(t,str) or t not in ALLOWED_TOOLS for t in tools) or len(set(tools))!=len(tools):
        raise ProposalError('ALLOWED_TOOL_SET_INVALID')
    return tuple(tools)


def _usage(value):
    if not isinstance(value,dict) or any(type(value.get(k)) is not int or not 0<=value[k]<=1000000 for k in ('input_tokens','output_tokens')):
        raise ProposalError('USAGE_UNAVAILABLE')
    return {k:value[k] for k in ('input_tokens','output_tokens')}


def _validate_proposal(value, excerpt, paper, tools):
    try:
        raw=_canonical(value)
        if len(raw.encode('utf-8'))>research_agent.MAX_OUTPUT_BYTES:
            raise ProposalError('MODEL_OUTPUT_TOO_LARGE')
        _public(value)
        if not Draft202012Validator(proposal_schema(tools)).is_valid(value):
            raise ProposalError('INVALID_PROPOSAL_SCHEMA')
    except (TypeError,ValueError) as exc:
        if isinstance(exc,ProposalError):raise
        raise ProposalError('INVALID_PROPOSAL_SCHEMA') from None
    c=value['conditions']
    required={'denominator','filters','unit','missing_policy','missing_tokens','method','reported_value','tolerance','source_location'}
    if c['method']=='mean':required.add('variable')
    if c['method']=='row_count' and c['variable'] is not None:
        raise ProposalError('ROW_COUNT_VARIABLE_INVALID')
    if c['method'] in ('mean','ols_regression') and c['missing_policy']=='not_applicable':
        raise ProposalError('MISSING_POLICY_INVALID')
    missing={k for k in required if c[k] is None}
    if set(value['missing'])!=missing:
        raise ProposalError('MISSING_FIELDS_NOT_EXPLICIT')
    location=c['source_location']
    if location is not None:
        if location['quote'] not in excerpt:
            raise ProposalError('SOURCE_QUOTE_NOT_IN_EXCERPT')
        known_id=paper.get('source_id') or paper.get('paper_doi') or paper.get('doi') or 'USER-SOURCE'
        if location['source_id']!=known_id:
            raise ProposalError('SOURCE_ID_NOT_BOUND')
        known_locator=paper.get('locator')
        if isinstance(paper.get('source_location'),dict):known_locator=paper['source_location'].get('locator',known_locator)
        if not known_locator or location['locator']!=known_locator:
            raise ProposalError('SOURCE_LOCATOR_NOT_BOUND')
    if value['next_tool']['name']=='verify_download' and (missing or c['method'] not in ('row_count','mean')):
        raise ProposalError('NEXT_TOOL_PRECONDITIONS_MISSING')
    return deepcopy(value)


def _safe_provider_error(error):
    if isinstance(error,ProposalError):
        code=error.args[0] if len(error.args)==1 else ''
        if isinstance(code,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{1,80}',code):return code
    if type(error) is finals_provider.ProviderError:
        code=error.args[0] if len(error.args)==1 else ''
        allowed={'LIVE_AI_NOT_ALLOWED','MODEL_KEY_UNAVAILABLE','PERSONAL_DATA_IN_OUTBOUND_PAYLOAD','SECRET_IN_REQUEST',
                 'REQUEST_TOO_LARGE','INVALID_LOCAL_REQUEST','LIVE_AI_BUDGET_EXHAUSTED','RESPONSE_TOO_LARGE',
                 'MODEL_RESPONSE_INCOMPLETE','MODEL_USAGE_UNAVAILABLE','SECRET_IN_MODEL_OUTPUT','MODEL_CONNECTION_OR_FORMAT_ERROR',
                 'NON_TEXT_MODEL_OUTPUT','MODEL_REFUSAL_OR_NON_TEXT','MODEL_OUTPUT_NOT_OBJECT','NONFINITE_MODEL_JSON','DUPLICATE_MODEL_JSON_KEY'}
        if isinstance(code,str) and (code in allowed or re.fullmatch(r'MODEL_HTTP_[1-5]\d{2}',code)):return code
    if type(error) is research_agent.AgentError:
        code=error.args[0] if len(error.args)==1 else ''
        if isinstance(code,str) and code in research_agent.SAFE_ERROR_CODES:return code
    return 'PROPOSAL_UNAVAILABLE'


def propose_conditions(excerpt, paper_context, dataset_metadata, *, opted_in=False, session=None,
                       provider='openai', model=None, api_key=None, allowed_tools=None):
    """One opt-in provider invocation. Caller supplies authenticated session, never document instructions."""
    started=perf_counter()
    result={'success':False,'status':'BLOCKED','proposal':None,'suggested_spec':None,'conditions_confirmed':False,
            'approved':False,'verified':False,'executed':False,'tool_executed':False,'error':None,
            'usage':{'attempted_calls':0,'input_tokens':None,'output_tokens':None,'status':'NOT_ATTEMPTED'},
            'call_observation':{'attempt_started':False,'response_observed':False,'failure_observed':False,'http_status_observed':None,'error_code':None},
            'input_snapshot_sha256':None,'source_basis':None,'provider':provider if provider in ('openai','anthropic') else None,
            'model':None,'limits':['Unconfirmed model proposals; no scientific verification, calculation or approval.',
                                 'Declared source hashes are user statements, not proof of full-document acquisition.'],
            'created_at_kst':datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')}
    try:
        # Consent/auth/operator switch precede configuration and any provider invocation.
        if opted_in is not True:raise ProposalError('EXPLICIT_OPT_IN_REQUIRED')
        if not finals_provider.paid_call_allowed(session):raise ProposalError('TEAM_AUTH_REQUIRED')
        if not finals_provider.live_allowed():raise ProposalError('LIVE_AI_NOT_ALLOWED')
        if provider not in ('openai','anthropic'):raise ProposalError('PROVIDER_NOT_ALLOWED')
        selected_model=finals_provider.MODEL if provider=='openai' and model is None else model
        if provider=='openai' and selected_model!=finals_provider.MODEL:raise ProposalError('MODEL_NOT_ALLOWED')
        if not isinstance(selected_model,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',selected_model):raise ProposalError('MODEL_NOT_ALLOWED')
        if api_key and isinstance(api_key,str) and api_key in selected_model:raise ProposalError('SECRET_IN_MODEL_IDENTIFIER')
        if api_key is not None and (not isinstance(api_key,str) or not 1<=len(api_key)<=512 or any(ord(c)<33 or ord(c)>126 for c in api_key)):
            raise ProposalError('SERVER_KEY_INVALID')
        if provider=='anthropic' and api_key is None:raise ProposalError('SERVER_KEY_REQUIRED')
        if not isinstance(excerpt,str) or not excerpt.strip() or len(excerpt.encode('utf-8'))>MAX_EXCERPT_BYTES:
            raise ProposalError('EXCERPT_REQUIRED_OR_TOO_LARGE')
        if not isinstance(paper_context,dict) or not isinstance(dataset_metadata,dict):raise ProposalError('CONTEXT_OBJECTS_REQUIRED')
        # [수정: 0 이영 · Codex] 2026-10-01 03:44 KST — 인증 URL 차단 코드를 URL 파싱 오류로 덮지 않으며 선언 지문의 형식과 예외 비반사를 검증한다. UTF-8 LF로 저장.
        source_hash=paper_context.get('source_sha256')
        if source_hash is not None and (not isinstance(source_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',source_hash)):
            raise ProposalError('DECLARED_SOURCE_HASH_INVALID')
        _public({'excerpt':excerpt,'paper_context':paper_context,'dataset_metadata':dataset_metadata})
        if len(_canonical([paper_context,dataset_metadata]).encode('utf-8'))>MAX_CONTEXT_BYTES:raise ProposalError('CONTEXT_TOO_LARGE')
        tools=_tools(allowed_tools)
        snapshot={'excerpt':excerpt,'paper_context':deepcopy(paper_context),'dataset_metadata':deepcopy(dataset_metadata),'allowed_tools':list(tools)}
        if api_key and api_key in _canonical(snapshot):raise ProposalError('SECRET_IN_INPUT')
        result.update(model=selected_model,input_snapshot_sha256=_digest(snapshot),prompt_sha256=_digest(SYSTEM),
                      source_basis={'status':'USER_SUPPLIED_EXCERPT','excerpt_sha256':hashlib.sha256(excerpt.encode('utf-8')).hexdigest(),
                                    'declared_document_sha256':paper_context.get('source_sha256'), 'full_document_bytes_verified':False},
                      budget={'max_calls':1,'max_request_bytes':research_agent.MAX_INPUT_BYTES,'max_output_tokens':research_agent.MAX_OUTPUT_TOKENS})
        result['usage'].update(attempted_calls=1,status='UNKNOWN')
        result['call_observation']['attempt_started']=True
        if provider=='openai':
            response=finals_provider.complete_json(SYSTEM,snapshot,schema=proposal_schema(tools),timeout=research_agent.TIMEOUT_SECONDS,
                        api_key=api_key,max_request_bytes=research_agent.MAX_INPUT_BYTES)
            result['call_observation']['response_observed']=True
            if not isinstance(response,dict) or response.get('provider')!='openai' or response.get('model')!=finals_provider.MODEL:
                raise ProposalError('INVALID_PROVIDER_RESPONSE')
            usage=_usage(response.get('usage'))
            result['usage'].update(usage,status='OBSERVED')
            value=response.get('output')
        else:
            payload={'model':selected_model,'max_tokens':research_agent.MAX_OUTPUT_TOKENS,'system':SYSTEM,
                     'messages':[{'role':'user','content':_canonical(snapshot)}]}
            response=research_agent._post_messages(payload,api_key=api_key)
            result['call_observation']['response_observed']=True
            if not isinstance(response,dict):raise ProposalError('INVALID_PROVIDER_RESPONSE')
            usage=_usage(response.get('usage'))
            result['usage'].update(usage,status='OBSERVED')
            value,_=research_agent._decode_message(response)
        if api_key and api_key in _canonical(value):raise ProposalError('SECRET_IN_MODEL_OUTPUT')
        proposal=_validate_proposal(value,excerpt,paper_context,tools)
        candidate=empty_spec(dataset_metadata.get('claim_id','USER-CLAIM'))
        candidate.update(proposal['conditions'])
        digest=dataset_metadata.get('actual_sha256') or dataset_metadata.get('data_fingerprint')
        candidate['data_fingerprint']=digest if isinstance(digest,str) and re.fullmatch(r'[0-9a-f]{64}',digest) else None
        candidate['unresolved']=['AI_PROPOSAL_REQUIRES_HUMAN_CONDITION_CONFIRMATION']
        if candidate['method'] in ('ols_regression','row_alignment'):
            candidate['unresolved'].append('ADDITIONAL_TYPED_METHOD_FIELDS_REQUIRE_HUMAN_INPUT')
        if proposal['next_tool']['name']=='verify_download':
            check=deepcopy(candidate);check['unresolved']=[]
            if not validate_spec(check)['ready']:raise ProposalError('NEXT_TOOL_PRECONDITIONS_MISSING')
        result.update(success=True,status='PROPOSED',proposal=proposal,suggested_spec=candidate,
                      proposal_sha256=_digest(proposal),candidate_requires_human_review=True)
    except Exception as error:
        code=_safe_provider_error(error)
        result['error']=code
        result['call_observation']['error_code']=code
        result['call_observation']['failure_observed']=result['call_observation']['attempt_started']
        if re.fullmatch(r'MODEL_HTTP_[1-5]\d{2}',code):
            result['call_observation'].update(response_observed=True,http_status_observed=int(code.rsplit('_',1)[1]))
    result['telemetry']={'elapsed_ms':round((perf_counter()-started)*1000,2),'provider_invocation_attempts':result['usage']['attempted_calls'],
                         'network_request_count':'NOT_INDEPENDENTLY_OBSERVED','failed':not result['success']}
    return result

"""One opt-in blind source re-extraction; agreement remains a human review task."""
# [작성: 0 이영 · Codex] 2026-10-01 05:00 KST — 기존 단일 모델 제안기를 재사용하되 봉인 후보·계산 결과·승인은 전송하지 않는다. 실제 받은 원문의 중립 문단만 재구성하고 위치·지문 대조 및 모의 회귀로 검증한다.
from __future__ import annotations
from collections.abc import MutableMapping
from copy import deepcopy
import hashlib
import json
import re

from core import research_integration_candidates as candidates
from core import research_integration_proposals as proposals
from finals import finals_provider

FIELDS=candidates.FIELDS
PRIORITY=('source_location','denominator','filters','missing','unit','calculation')
NEUTRAL_LOCATOR='USER_SELECTED_REVIEW_CONTEXTS'
BUDGET_KEY='research_integration_blind_attempts'
MAX_REVIEW_LOCATIONS=3


class BlindReviewError(ValueError):
    pass


def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _error(code):
    if isinstance(code,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{1,80}',code):return code
    return 'BLIND_REVIEW_UNAVAILABLE'


def _result():
    return {'success':False,'status':'BLOCKED','error':None,'field_cards':[],
            'blocking_fields':list(PRIORITY),'next_action':{'tool':'manual_source_review','priority_fields':list(PRIORITY)},
            'semantic_ready':False,'can_approve':False,'approved':False,'verified':False,'executed':False,'calculation':None,
            'usage':{'attempted_calls':0,'input_tokens':None,'output_tokens':None,'status':'NOT_ATTEMPTED'},
            'receipt':{'review_invocation_attempts':0,'provider_invocation_attempts':0,
                       'network_request_count':'NOT_INDEPENDENTLY_OBSERVED','paid_call_status':'NOT_INDEPENDENTLY_OBSERVED'},
            'limits':['Model agreement is an unconfirmed review observation, not independent scientific truth.',
                      'One proposal and at most one blind re-extraction per current frozen pool; no per-field calls or retries.',
                      'CSV rows and first-candidate values, quotes, previews, explanations and approvals are excluded from model input.',
                      'Received source bytes may be a registered public derivative; publisher-original bytes are not assumed.']}


def _neutral_inputs(source_bytes,source_receipt,paper_context,dataset_metadata,review_locations):
    source,contexts=candidates._source_state(source_bytes,source_receipt,paper_context)
    if source['status']=='NOT_ACQUIRED':raise BlindReviewError('ACTUAL_SOURCE_BYTES_REQUIRED')
    if not isinstance(review_locations,list) or not 1<=len(review_locations)<=MAX_REVIEW_LOCATIONS or len(set(review_locations))!=len(review_locations):
        raise BlindReviewError('REVIEW_LOCATIONS_INVALID')
    if any(not isinstance(loc,str) or loc not in contexts for loc in review_locations):
        raise BlindReviewError('REVIEW_LOCATION_NOT_BOUND')
    neutral={loc:contexts[loc] for loc in review_locations}
    if any(not text for text in neutral.values()):raise BlindReviewError('EMPTY_REVIEW_CONTEXT')
    excerpt='\n\n'.join('Source location: '+loc+'\n'+text for loc,text in neutral.items())
    if len(excerpt.encode())>proposals.MAX_EXCERPT_BYTES:raise BlindReviewError('REVIEW_CONTEXT_TOO_LARGE')
    if not isinstance(dataset_metadata,dict):raise BlindReviewError('DATASET_METADATA_REQUIRED')
    columns=dataset_metadata.get('columns')
    if not isinstance(columns,list) or not columns or len(columns)>128 or any(not candidates._text(c,128) for c in columns) or len(set(columns))!=len(columns):
        raise BlindReviewError('COLUMN_NAMES_REQUIRED')
    dictionary=dataset_metadata.get('public_dictionary',{})
    if not isinstance(dictionary,dict) or len(dictionary)>len(columns) or any(k not in columns or not candidates._text(v,1000) for k,v in dictionary.items()):
        raise BlindReviewError('PUBLIC_DICTIONARY_INVALID')
    row_dictionary=dataset_metadata.get('row_dictionary')
    if row_dictionary is not None and not candidates._text(row_dictionary,2000):raise BlindReviewError('ROW_DICTIONARY_INVALID')
    known_id=paper_context.get('source_id') or paper_context.get('paper_doi') or paper_context.get('doi') or 'USER-SOURCE'
    # Neutral envelope is a decoder label, not an invented paragraph locator. Quotes are rebound below to one actual span.
    paper={'source_id':known_id,'source_url':source_receipt['source_url'],'paper_version':paper_context['paper_version'],
           'source_sha256':source['actual_sha256'],'locator':NEUTRAL_LOCATOR}
    metadata={'columns':deepcopy(columns),'public_dictionary':deepcopy(dictionary)}
    if row_dictionary is not None:metadata['row_dictionary']=row_dictionary
    proposals._public({'excerpt':excerpt,'paper_context':paper,'dataset_metadata':metadata})
    return excerpt,paper,metadata,source,neutral


def _proposal_attempts(prior):
    if prior is None:return 1,'ONE_PROPOSAL_SLOT_RESERVED_NOT_OBSERVED'
    if not isinstance(prior,dict) or not isinstance(prior.get('usage'),dict):raise BlindReviewError('PRIOR_PROPOSAL_RECEIPT_INVALID')
    count=prior['usage'].get('attempted_calls')
    if type(count) is not int or not 0<=count<=1:raise BlindReviewError('TOTAL_PROPOSAL_REVIEW_BUDGET_EXCEEDED')
    return count,'PRIOR_PROPOSAL_INVOCATION_RECEIPT'


def _reserve(session,pool_sha,previous_review):
    if not isinstance(session,MutableMapping):raise BlindReviewError('SERVER_REVIEW_BUDGET_STATE_REQUIRED')
    if previous_review is not None:
        if not isinstance(previous_review,dict):raise BlindReviewError('PREVIOUS_REVIEW_INVALID')
        if previous_review.get('candidate_set_sha256')==pool_sha and previous_review.get('receipt',{}).get('review_invocation_attempts',0):
            raise BlindReviewError('REEXTRACTION_ALREADY_ATTEMPTED')
    budget=session.get(BUDGET_KEY,{})
    if not isinstance(budget,dict) or any(not candidates._hash(k) or type(v) is not int or v not in (0,1) for k,v in budget.items()):
        raise BlindReviewError('SERVER_REVIEW_BUDGET_INVALID')
    if budget.get(pool_sha,0)>=1:raise BlindReviewError('REEXTRACTION_ALREADY_ATTEMPTED')
    # Reserve before provider invocation. A failed attempt never produces an automatic retry.
    budget=deepcopy(budget);budget[pool_sha]=1
    session[BUDGET_KEY]=budget


def _groups(conditions):
    missing=None if conditions['missing_policy'] is None or conditions['missing_tokens'] is None else {'policy':conditions['missing_policy'],'tokens':conditions['missing_tokens']}
    calculation=None if any(conditions[k] is None for k in ('method','reported_value','tolerance')) or (conditions['method']=='mean' and conditions['variable'] is None) else {
        k:conditions[k] for k in ('method','variable','reported_value','tolerance')}
    return {'denominator':conditions['denominator'],'filters':conditions['filters'],'unit':conditions['unit'],
            'missing':missing,'calculation':calculation,'source_location':conditions['source_location']}


def _bind_evidence(conditions,neutral,source_receipt,actual_sha):
    location=conditions['source_location']
    if location is None:return None
    quote=location['quote']
    # The model sees neutral source spans, so only an unambiguous actual selected location can be claimed.
    quote_text=candidates._visible(quote.encode())
    matches=[loc for loc,text in neutral.items() if quote_text and quote_text in text]
    if len(matches)!=1:raise BlindReviewError('INDEPENDENT_QUOTE_LOCATION_NOT_UNIQUE_OR_BOUND')
    loc=matches[0]
    return {'actual_source_sha256':actual_sha,'locator':loc,'quote':quote,
            'context_sha256':source_receipt['locations'][loc]['context_sha256'],
            'source_id':location['source_id'],'paper_version':source_receipt['paper_version']}


def _cards(frozen_candidate,conditions,evidence,source_check,row_dictionary):
    independent=_groups(conditions);contract=frozen_candidate['source_condition_contract']
    if evidence is not None:
        independent['source_location']={k:evidence[k] for k in ('source_id','locator','quote')}
    cards=[];blocking=set(source_check.get('unresolved_fields',[]))
    independent_proof={}
    if evidence is not None:
        actual_location={k:evidence[k] for k in ('source_id','locator','quote')}
        independent_contract={'contract_version':1,'paper_version':contract['paper_version'],'source_location':actual_location,
                              'fields':{field:{'status':'missing' if independent[field] is None else 'fact','value':independent[field],
                                               'evidence':None if independent[field] is None else {'locator':evidence['locator'],'quote':evidence['quote']}} for field in FIELDS}}
        # [수정: 0 이영 · Codex] 2026-10-01 05:03 KST — 독립 출력도 실제 선택 위치와 값별 인용 근거를 재검사한다. 문자열 일치는 의미 확정이 아니며 원문에 없는 조건은 검토 필요로 남긴다.
        independent_proof=candidates._condition_contract(independent_contract,{'source_id':evidence['source_id'],'paper_version':evidence['paper_version']},
                                                       {evidence['locator']:candidates._visible(evidence['quote'].encode())})
    for field in FIELDS:
        entry=contract['fields'][field];first=entry['value'];second=independent[field]
        if evidence is None or second is None:
            status='MISSING_INDEPENDENT_EVIDENCE';reason='The selected source did not supply a bound independent value.'
        elif not independent_proof.get(field,{}).get('lexical_support',False):
            status='INDEPENDENT_VALUE_NOT_SUPPORTED_BY_QUOTE';reason='The independently proposed value lacks explicit support in its bound source quote.'
        elif entry['status']=='missing' or first is None:
            status='MISSING_CANDIDATE';reason='A source proposal may fill a candidate only through explicit human review and re-freezing.'
        else:
            same=(first.get('source_id')==second.get('source_id') and first.get('locator')==second.get('locator')) if field=='source_location' else candidates._same(field,first,second)
            status='RECORDED_VALUES_AGREE' if same and entry['status']=='fact' else 'HYPOTHESIS_VALUES_AGREE' if same else 'MISMATCH'
            reason='Recorded values agree; meaning and approval remain unconfirmed.' if same else 'Independent source extraction differs from the frozen candidate.'
        if status!='RECORDED_VALUES_AGREE':blocking.add(field)
        cards.append({'field':field,'candidate_value':deepcopy(first),'candidate_status':entry['status'],
                      'independently_extracted_value':deepcopy(second),'status':status,'reason':reason,
                      'evidence':deepcopy(evidence),'semantic_ready':False,'approved':False})
    denominator=independent['denominator'] or ''
    if re.search(r'(?:\bn\s*=|person|people|participant|subject|patient|개인|사람|환자|대상자)',denominator,re.I) and not row_dictionary:
        blocking.add('denominator')
        card=next(card for card in cards if card['field']=='denominator')
        card['status']='ROW_DICTIONARY_REQUIRED';card['reason']='CSV rows are not known to be distinct people; supply an original row-unit dictionary.'
    operations=contract.get('unsupported_operations',[])
    if 'unit_conversion' in operations:blocking.add('unit')
    if 'per_subject_aggregation' in operations:blocking.add('denominator')
    if 'weighted_calculation' in operations:blocking.add('calculation')
    return cards,[field for field in PRIORITY if field in blocking]


def blind_review_conditions(frozen_candidate,candidate_set, *,source_bytes,source_receipt,paper_context,dataset_metadata,
                            review_locations,opted_in=False,session=None,provider='openai',model=None,api_key=None,
                            prior_proposal_receipt=None,previous_review=None):
    """Explicit source-only re-extraction, one invocation per sealed pool, with no approval or calculation."""
    result=_result()
    try:
        if opted_in is not True:raise BlindReviewError('EXPLICIT_OPT_IN_REQUIRED')
        if not finals_provider.paid_call_allowed(session):raise BlindReviewError('TEAM_AUTH_REQUIRED')
        if not finals_provider.live_allowed():raise BlindReviewError('LIVE_AI_NOT_ALLOWED')
        if not isinstance(frozen_candidate,dict) or not isinstance(dataset_metadata,dict):raise BlindReviewError('FROZEN_CANDIDATE_REQUIRED')
        # [수정: 0 이영 · Codex] 2026-10-01 05:27 KST — 모델 I/O 전 입력 사전을 분리 봉인하고 응답 뒤 live 지문·중립 전송본을 다시 대조한다. 늦은 결과가 바뀐 후보/근거에 붙지 않는 동시변경 회귀로 검증하며 추가 호출은 없다.
        initial_candidate=deepcopy(frozen_candidate);initial_set=deepcopy(candidate_set)
        initial_receipt=deepcopy(source_receipt);initial_paper=deepcopy(paper_context)
        initial_metadata=deepcopy(dataset_metadata);initial_locations=deepcopy(review_locations)
        data_sha=initial_metadata.get('actual_sha256') or initial_metadata.get('data_fingerprint')
        if not candidates._hash(data_sha):raise BlindReviewError('CURRENT_DATA_SHA256_REQUIRED')
        check=candidates.compare_source_conditions(initial_candidate,initial_candidate.get('candidate_spec'),
                    source_bytes=source_bytes,source_receipt=initial_receipt,paper_context=initial_paper,
                    data_sha256=data_sha,candidate_set=initial_set)
        if not check.get('success'):raise BlindReviewError(check.get('error','FROZEN_CANDIDATE_INVALID'))
        excerpt,paper,metadata,source,neutral=_neutral_inputs(source_bytes,initial_receipt,initial_paper,initial_metadata,initial_locations)
        prior_count,prior_basis=_proposal_attempts(prior_proposal_receipt)
        snapshot_sha=_digest({'excerpt':excerpt,'paper_context':paper,'dataset_metadata':metadata})
        result.update(candidate_set_sha256=initial_set['candidate_set_sha256'],frozen_sha256=initial_candidate['frozen_sha256'],
                      candidate_bindings=deepcopy(check['candidate_bindings']),blind_input_snapshot_sha256=snapshot_sha,
                      source_state=deepcopy(source),review_locations=list(initial_locations),
                      budget={'max_total_invocations':2,'proposal_invocations':prior_count,'proposal_observation_basis':prior_basis,
                              'max_reextraction_invocations':1,'automatic_retries':0})
        _reserve(session,initial_set['candidate_set_sha256'],previous_review)
        result['receipt'].update(review_invocation_attempts=1,actual_source_sha256=source['actual_sha256'],
                                 selected_locations=list(initial_locations),frozen_candidate_values_sent=False,
                                 candidate_quote_field_sent=False,computed_results_sent=False,approval_values_sent=False,
                                 raw_dataset_rows_sent=False,model_input_scope='ACTUAL_SOURCE_SPANS_AND_PUBLIC_COLUMN_DICTIONARY_ONLY')
        observation=proposals.propose_conditions(excerpt,paper,metadata,opted_in=True,session=session,provider=provider,
                    model=model,api_key=api_key,allowed_tools=['manual_source_review','stop'])
        result['usage']=deepcopy(observation['usage'])
        result['receipt'].update(provider_invocation_attempts=observation['usage']['attempted_calls'],
                                 call_observation=deepcopy(observation.get('call_observation',{})))
        if candidates.source_revision()!=initial_candidate['bindings']['engine_revision']:raise BlindReviewError('ENGINE_CHANGED_DURING_BLIND_REVIEW')
        try:
            current_data_sha=dataset_metadata.get('actual_sha256') or dataset_metadata.get('data_fingerprint')
            current_check=candidates.compare_source_conditions(frozen_candidate,frozen_candidate.get('candidate_spec'),
                    source_bytes=source_bytes,source_receipt=source_receipt,paper_context=paper_context,
                    data_sha256=current_data_sha,candidate_set=candidate_set)
            if not current_check.get('success') or current_check.get('candidate_bindings')!=check['candidate_bindings']:
                raise BlindReviewError('STALE_BLIND_REVIEW_INPUTS')
            if candidate_set.get('candidate_set_sha256')!=initial_set['candidate_set_sha256'] or frozen_candidate.get('frozen_sha256')!=initial_candidate['frozen_sha256']:
                raise BlindReviewError('STALE_BLIND_REVIEW_INPUTS')
            new_excerpt,new_paper,new_metadata,_,_=_neutral_inputs(source_bytes,source_receipt,paper_context,dataset_metadata,review_locations)
            current_snapshot_sha=_digest({'excerpt':new_excerpt,'paper_context':new_paper,'dataset_metadata':new_metadata})
            if current_snapshot_sha!=snapshot_sha:raise BlindReviewError('STALE_BLIND_REVIEW_INPUTS')
        except Exception as exc:
            if isinstance(exc,BlindReviewError) and str(exc)=='STALE_BLIND_REVIEW_INPUTS':raise
            raise BlindReviewError('STALE_BLIND_REVIEW_INPUTS') from None
        result['receipt'].update(post_response_inputs_rechecked=True,post_response_neutral_snapshot_sha256=current_snapshot_sha)
        if not observation.get('success'):
            result['error']=_error(observation.get('error'));return result
        # Cards use the initial immutable copies after checking live inputs, never a different mutable candidate.
        conditions=observation['proposal']['conditions']
        evidence=_bind_evidence(conditions,neutral,initial_receipt,source['actual_sha256'])
        cards,blocking=_cards(initial_candidate,conditions,evidence,check,metadata.get('row_dictionary'))
        result.update(success=True,status='BLIND_REVIEW_REQUIRES_HUMAN_REVIEW',field_cards=cards,blocking_fields=blocking,
                      independent_conditions_sha256=_digest(conditions),independent_proposal_sha256=observation['proposal_sha256'],
                      next_action={'tool':'manual_source_review','priority_fields':blocking,
                                   'reason':'Resolve blocking source fields and explicitly review meaning; no numerical-distance selection.'},
                      semantic_ready=False,approved=False,verified=False,executed=False,calculation=None)
    except Exception as exc:
        result['error']=_error(str(exc)) if isinstance(exc,(BlindReviewError,candidates.CandidateError,proposals.ProposalError)) else 'BLIND_REVIEW_UNAVAILABLE'
        if result['error'] in ('STALE_BLIND_REVIEW_INPUTS','ENGINE_CHANGED_DURING_BLIND_REVIEW'):result['status']='STALE'
    return result

"""Frozen source-condition candidates and non-approving scalar previews."""
# [작성: 0 이영 · Codex] 2026-10-01 04:16 KST — 계산 전 최대3 조건 후보·실제 원문 위치를 봉인하고 숫자 일치와 원문 조건 동등성을 분리한다. 신규 모의 공격/정상 회귀로 검증하며 모델·승인 호출은 없다.
from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
import re
import unicodedata
from urllib.parse import parse_qs,urlsplit

from core.source_revision import source_revision
from evidence_gate import gate
from evidence_gate.compute import read_csv, select_rows, numeric_table, GateError
from evidence_gate.spec import validate as validate_spec, spec_sha256
from finals.finals_privacy import sensitive_kinds

SCHEMA='research-integration-candidates/1'
MAX_CANDIDATES=3
MAX_BYTES=5*1024*1024
FIELDS=('denominator','filters','unit','missing','calculation','source_location')
SUPPORTED_METHODS=('row_count','mean')
UNSUPPORTED_OPERATIONS=('unit_conversion','per_subject_aggregation','weighted_calculation')
SEMANTIC_MARKERS={'AI_PROPOSAL_REQUIRES_HUMAN_CONDITION_CONFIRMATION','SEMANTIC_REVIEW_REQUIRED'}
LIMITS=['Conditional scalar preview only; no approval or full-paper verification.',
        'Fact labels are recorded source interpretations, not independent semantic truth.',
        'Integrity hashes bind inputs but are not signatures or authenticated identities.',
        'No closest-result selection; all current candidates remain visible.']


class CandidateError(ValueError):
    pass


def _now():return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')


def _json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def _sha(raw):return hashlib.sha256(raw).hexdigest()


def _digest(value):return _sha(_json(value).encode('utf-8'))


def _public(value):
    if sensitive_kinds(value):raise CandidateError('SENSITIVE_INPUT')
    _json(value)


def _text(value,limit=4000):return isinstance(value,str) and bool(value.strip()) and len(value.encode('utf-8'))<=limit


def _hash(value):return isinstance(value,str) and re.fullmatch(r'[0-9a-f]{64}',value) is not None


def _seal(item):
    result=deepcopy(item);result.pop('integrity_sha256',None);result['integrity_sha256']=_digest(result);return result


def _intact(item):
    if not isinstance(item,dict):return False
    value=deepcopy(item);expected=value.pop('integrity_sha256',None)
    try:return _hash(expected) and expected==_digest(value)
    except (ValueError,TypeError):return False


def _valid_frozen(item):
    if not _intact(item) or item.get('schema')!=SCHEMA:return False
    row=deepcopy(item)
    for key in ('integrity_sha256','frozen_sha256','frozen_at_kst','status'):row.pop(key,None)
    if item.get('frozen_sha256')!=_digest(row):return False
    expected=row.pop('base_sha256',None)
    if not isinstance(row.get('bindings'),dict):return False
    row['bindings'].pop('candidate_set_sha256',None)
    return expected==_digest(row)


def _same(field,left,right):
    # Typed eq filters are conjunctions; numeric 20 and 20.0 are exact equals, without rounding.
    def eq(a,b):
        if type(a) in (int,float) and type(b) in (int,float):return a==b
        if type(a) is not type(b):return False
        if isinstance(a,dict):return a.keys()==b.keys() and all(eq(a[k],b[k]) for k in a)
        if isinstance(a,list):return len(a)==len(b) and all(eq(x,y) for x,y in zip(a,b))
        return a==b
    if field=='filters' and isinstance(left,list) and isinstance(right,list):
        pending=list(right)
        for value in left:
            found=next((i for i,item in enumerate(pending) if eq(value,item)),None)
            if found is None:return False
            pending.pop(found)
        return not pending
    if field=='missing' and isinstance(left,dict) and isinstance(right,dict):
        return left.get('policy')==right.get('policy') and set(left.get('tokens',[]))==set(right.get('tokens',[]))
    return eq(left,right)


def _blocked(code,**extra):
    return {'success':False,'status':'BLOCKED','agreement':'BLOCKED','error':code,'can_preview':False,
            'can_calculate':False,'can_approve':False,'semantic_ready':False,'approved':False,'verified':False,
            'limits':list(LIMITS),**extra}


class _Visible(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'):self.skip+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript') and self.skip:self.skip-=1
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)


def _visible(raw):
    try:text=raw.decode('utf-8-sig')
    except UnicodeError:raise CandidateError('SOURCE_UTF8_REQUIRED') from None
    parser=_Visible();parser.feed(text);parser.close()
    return ' '.join(unicodedata.normalize('NFKC',unescape(' '.join(parser.parts))).split())


def source_receipt_for_spans(source_bytes, *,source_url,paper_version,spans,source_kind='RECEIVED_SOURCE_BYTES'):
    """Bind explicit byte spans; never searches elsewhere or invents a locator."""
    if not isinstance(source_bytes,bytes) or not 0<len(source_bytes)<=MAX_BYTES:raise CandidateError('SOURCE_BYTES_REQUIRED')
    if not _text(paper_version,256) or not _text(source_kind,128):raise CandidateError('PAPER_VERSION_REQUIRED')
    _public({'url':source_url,'paper_version':paper_version,'source_kind':source_kind})
    try:
        url=urlsplit(source_url)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment or any(re.search(r'key|token|secret|password',k,re.I) for k in parse_qs(url.query)):
            raise CandidateError('SOURCE_URL_INVALID')
    except (ValueError,TypeError):raise CandidateError('SOURCE_URL_INVALID') from None
    if not isinstance(spans,list) or not 1<=len(spans)<=24:raise CandidateError('SOURCE_SPANS_REQUIRED')
    locations={}
    for span in spans:
        if not isinstance(span,dict) or set(span)!={'locator','start_byte','end_byte'} or not _text(span['locator'],512):raise CandidateError('SOURCE_SPAN_INVALID')
        start,end=span['start_byte'],span['end_byte']
        if type(start) is not int or type(end) is not int or not 0<=start<end<=len(source_bytes) or end-start>16384 or span['locator'] in locations:raise CandidateError('SOURCE_SPAN_INVALID')
        _visible(source_bytes[start:end])
        locations[span['locator']]={'kind':'UTF8_BYTE_SPAN','start_byte':start,'end_byte':end,'context_sha256':_sha(source_bytes[start:end])}
    return {'schema':'research-source-receipt/1','actual_sha256':_sha(source_bytes),'source_url':source_url,
            'paper_version':paper_version,'source_kind':source_kind,'locations':locations,'bound_at_kst':_now()}


def _receipt_binding(receipt):
    if not isinstance(receipt,dict):return receipt
    return {k:receipt.get(k) for k in ('actual_sha256','source_url','paper_version','source_kind','locations')}


def _source_state(source_bytes,receipt,paper):
    if not isinstance(paper,dict) or not _text(paper.get('paper_version'),256):raise CandidateError('PAPER_VERSION_REQUIRED')
    _public(paper)
    if source_bytes is None:
        return {'status':'NOT_ACQUIRED','actual_sha256':None,'receipt_sha256':_digest(_receipt_binding(receipt)),
                'paper_context_sha256':_digest(paper),'declared_sha256':paper.get('source_sha256')},{}
    if not isinstance(source_bytes,bytes) or not 0<len(source_bytes)<=MAX_BYTES:raise CandidateError('SOURCE_BYTES_REQUIRED')
    _visible(source_bytes)
    # [수정: 0 이영 · Codex] 2026-10-01 04:44 KST — 선언 지문이 있으면 받은 바이트와 별도 대조하며, 선언만 있는 상태를 실제 원문 취득으로 올리지 않는다. 모의 지문 불일치 회귀로 검증한다.
    declared=paper.get('source_sha256')
    if declared is not None and (not _hash(declared) or declared!=_sha(source_bytes)):
        raise CandidateError('DECLARED_SOURCE_SHA256_MISMATCH')
    if not isinstance(receipt,dict) or receipt.get('actual_sha256')!=_sha(source_bytes):raise CandidateError('SOURCE_RECEIPT_SHA256_MISMATCH')
    _public(receipt)
    if receipt.get('paper_version')!=paper['paper_version'] or receipt.get('source_url')!=paper.get('source_url'):raise CandidateError('SOURCE_PAPER_CONTEXT_MISMATCH')
    locations=receipt.get('locations')
    if not isinstance(locations,dict) or not locations or len(locations)>24:raise CandidateError('LOCATOR_NOT_BOUND')
    contexts={}
    for locator,span in locations.items():
        if not _text(locator,512) or not isinstance(span,dict) or set(span)!={'kind','start_byte','end_byte','context_sha256'} or span['kind']!='UTF8_BYTE_SPAN':raise CandidateError('SOURCE_SPAN_INVALID')
        start,end=span['start_byte'],span['end_byte']
        if type(start) is not int or type(end) is not int or not 0<=start<end<=len(source_bytes) or end-start>16384 or _sha(source_bytes[start:end])!=span['context_sha256']:raise CandidateError('SOURCE_SPAN_SHA256_MISMATCH')
        contexts[locator]=_visible(source_bytes[start:end])
    return {'status':'SOURCE_BYTES_AND_LOCATIONS_BOUND','actual_sha256':_sha(source_bytes),'receipt_sha256':_digest(_receipt_binding(receipt)),
            'paper_context_sha256':_digest(paper),'source_kind':receipt.get('source_kind','RECEIVED_SOURCE_BYTES'),
            'publisher_original_bytes_verified':False},contexts


def _location(value):
    return isinstance(value,dict) and set(value)=={'source_id','locator','quote'} and _text(value.get('source_id'),128) and _text(value.get('locator'),512) and _text(value.get('quote'),4000)


def _spec_groups(spec):
    return {'denominator':spec.get('denominator'),'filters':spec.get('filters'),'unit':spec.get('unit'),
            'missing':{'policy':spec.get('missing_policy'),'tokens':spec.get('missing_tokens')},
            'calculation':{k:spec.get(k) for k in ('method','variable','reported_value','tolerance')},
            'source_location':spec.get('source_location')}


def _valid_value(field,value):
    if field in ('denominator','unit'):return _text(value,2000)
    if field=='source_location':return _location(value)
    if field=='filters':
        return isinstance(value,list) and len(value)<=8 and all(isinstance(f,dict) and set(f)=={'column','operator','value'} and _text(f['column'],128) and f['operator']=='eq' and (isinstance(f['value'],str) or type(f['value']) in (int,float)) for f in value)
    if field=='missing':return isinstance(value,dict) and set(value)=={'policy','tokens'} and value['policy'] in ('error','complete_case','not_applicable') and isinstance(value['tokens'],list) and len(value['tokens'])<=16 and all(isinstance(t,str) and len(t)<=32 for t in value['tokens']) and len(set(value['tokens']))==len(value['tokens'])
    if field=='calculation':return isinstance(value,dict) and set(value)=={'method','variable','reported_value','tolerance'} and isinstance(value['method'],str) and (value['variable'] is None or _text(value['variable'],128)) and type(value['reported_value']) in (int,float) and type(value['tolerance']) in (int,float) and value['tolerance']>=0
    return False


def _condition_contract(contract,paper,contexts):
    allowed={'contract_version','paper_version','source_location','fields','unsupported_operations'}
    if not isinstance(contract,dict) or not set(contract)<=allowed or not {'contract_version','paper_version','source_location','fields'}<=set(contract) or contract['contract_version']!=1:raise CandidateError('SOURCE_CONTRACT_INVALID')
    _public(contract)
    if contract['paper_version']!=paper['paper_version'] or not _location(contract['source_location']):raise CandidateError('SOURCE_CONTRACT_VERSION_OR_LOCATION_INVALID')
    known_id=paper.get('source_id') or paper.get('paper_doi') or paper.get('doi')
    if known_id and contract['source_location']['source_id']!=known_id:raise CandidateError('SOURCE_ID_NOT_BOUND')
    fields=contract['fields']
    if not isinstance(fields,dict) or set(fields)!=set(FIELDS):raise CandidateError('SOURCE_FIELDS_INVALID')
    operations=contract.get('unsupported_operations',[])
    if not isinstance(operations,list) or any(op not in UNSUPPORTED_OPERATIONS for op in operations):raise CandidateError('UNSUPPORTED_OPERATION_FLAGS_INVALID')
    proof={}
    top=contract['source_location'];top_text=contexts.get(top['locator'])
    top_bound=top_text is not None and _visible(top['quote'].encode()) in top_text
    for field,entry in fields.items():
        if not isinstance(entry,dict) or set(entry)!={'status','value','evidence'} or entry['status'] not in ('fact','hypothesis','missing'):raise CandidateError('FIELD_STATUS_INVALID')
        if entry['status']=='missing':
            if entry['value'] is not None or entry['evidence'] is not None:raise CandidateError('MISSING_FIELD_HAS_VALUE')
            proof[field]={'status':'MISSING','location_bound':False,'lexical_support':False};continue
        if not _valid_value(field,entry['value']):raise CandidateError('FIELD_VALUE_INVALID')
        ev=entry['evidence']
        if not isinstance(ev,dict) or set(ev)!={'locator','quote'} or not _text(ev['locator'],512) or not _text(ev['quote'],4000):raise CandidateError('FIELD_EVIDENCE_INVALID')
        context=contexts.get(ev['locator'])
        quote_text=_visible(ev['quote'].encode())
        bound=top_bound and context is not None and quote_text in context
        # Lexical safeguards catch explicit opposite labels; absence is unresolved, never inferred truth.
        support=True
        value=entry['value']
        if field in ('denominator','unit'):support=re.search(r'(?<![\w./%])'+re.escape(_visible(value.encode()))+r'(?![\w./%])',quote_text) is not None
        elif field=='filters' and value:
            support=all(str(f['column']) in quote_text and re.search(r'(?<!\w)'+re.escape(str(f['value']))+r'(?!\w)',quote_text) is not None for f in value)
        elif field=='calculation' and value['variable'] is not None:support=value['variable'] in quote_text
        elif field=='source_location':support=value==top
        proof[field]={'status':'LOCATION_BOUND' if bound else 'LOCATOR_OR_QUOTE_UNCONFIRMED',
                      'location_bound':bool(bound),'lexical_support':bool(support),
                      'context_sha256':None if context is None else _digest(context)}
    return proof


def _preview_spec(spec):
    result=deepcopy(spec)
    if isinstance(result.get('unresolved'),list):result['unresolved']=[x for x in result['unresolved'] if x not in SEMANTIC_MARKERS]
    return result


def freeze_candidates(candidates, *,source_bytes,source_receipt,paper_context,data_sha256,previous_set=None):
    """Re-freeze all alternatives against one current snapshot; never choose by numeric distance."""
    try:
        if not isinstance(candidates,list) or not 1<=len(candidates)<=MAX_CANDIDATES:raise CandidateError('CANDIDATE_COUNT_INVALID')
        _public(candidates)
        if not _hash(data_sha256):raise CandidateError('DATA_SHA256_REQUIRED')
        if previous_set is not None and not _intact(previous_set):raise CandidateError('PREVIOUS_SET_INTEGRITY_INVALID')
        source,contexts=_source_state(source_bytes,source_receipt,paper_context)
        engine=source_revision();rows=[];ids=set()
        for item in candidates:
            if not isinstance(item,dict) or set(item)!={'candidate_id','source_condition_contract','candidate_spec'} or not _text(item['candidate_id'],128) or item['candidate_id'] in ids:raise CandidateError('CANDIDATE_INPUT_INVALID')
            ids.add(item['candidate_id']);spec=item['candidate_spec'];contract=item['source_condition_contract']
            _public(spec)
            if not isinstance(spec,dict) or spec.get('data_fingerprint')!=data_sha256:raise CandidateError('CANDIDATE_SPEC_DATA_MISMATCH')
            proof=_condition_contract(contract,paper_context,contexts)
            base={'schema':SCHEMA,'candidate_id':item['candidate_id'],'source_condition_contract':deepcopy(contract),
                  'candidate_spec':deepcopy(spec),'field_proof':proof,'source_state':source,
                  'bindings':{'source_sha256':source['actual_sha256'],'source_receipt_sha256':source['receipt_sha256'],
                              'paper_context_sha256':source['paper_context_sha256'],'source_contract_sha256':_digest(contract),
                              'data_sha256':data_sha256,'spec_sha256':spec_sha256(spec),'engine_revision':engine},
                  'can_approve':False,'semantic_ready':False,'approved':False,'verified':False}
            base['base_sha256']=_digest(base);rows.append(base)
        pool_sha=_digest([{'candidate_id':r['candidate_id'],'base_sha256':r['base_sha256']} for r in rows])
        for row in rows:
            row['bindings']['candidate_set_sha256']=pool_sha
            row['frozen_sha256']=_digest(row)
            row.update(frozen_at_kst=_now(),status='FROZEN_UNCONFIRMED')
        if source_revision()!=engine:raise CandidateError('ENGINE_CHANGED_DURING_FREEZE')
        # [수정: 0 이영 · Codex] 2026-10-01 04:49 KST — 후보 재봉인 전후 모든 입력 지문을 분리해 남기고 반환 사전으로 기존 봉인값이 변하지 않게 복사한다. 추가 후보·근거 변경 회귀로 검증한다.
        previous={} if previous_set is None else {r['candidate_id']:r for r in previous_set.get('candidates',[])}
        binding_changes=[]
        for row in rows:
            before=None if row['candidate_id'] not in previous else dict(previous[row['candidate_id']]['bindings'],frozen_sha256=previous[row['candidate_id']]['frozen_sha256'])
            after=dict(row['bindings'],frozen_sha256=row['frozen_sha256'])
            binding_changes.append({'candidate_id':row['candidate_id'],'before_bindings':before,'after_bindings':after,
                                    'changed_bindings':list(after) if before is None else [k for k in after if before.get(k)!=after[k]]})
        removed=[cid for cid in previous if cid not in ids]
        return _seal({'schema':SCHEMA,'success':True,'status':'FROZEN','candidate_set_sha256':pool_sha,
                      'previous_candidate_set_sha256':None if previous_set is None else previous_set.get('candidate_set_sha256'),
                      'candidates':[_seal(r) for r in rows],'binding_changes':binding_changes,'removed_candidate_ids':removed,'can_approve':False,'semantic_ready':False,
                      'approved':False,'verified':False,'frozen_at_kst':_now(),'limits':list(LIMITS)})
    except (CandidateError,ValueError,TypeError,KeyError,OSError) as exc:
        return _blocked(str(exc) if isinstance(exc,CandidateError) else 'CANDIDATE_INPUT_INVALID')


def freeze_candidate(source_condition_contract,candidate_spec, *,source_bytes,source_receipt,paper_context,data_sha256,
                     candidate_id='candidate-1',existing_set=None):
    items=[]
    if existing_set is not None:
        if not _intact(existing_set):return _blocked('PREVIOUS_SET_INTEGRITY_INVALID')
        items=[{k:deepcopy(row[k]) for k in ('candidate_id','source_condition_contract','candidate_spec')} for row in existing_set.get('candidates',[])]
    items.append({'candidate_id':candidate_id,'source_condition_contract':source_condition_contract,'candidate_spec':candidate_spec})
    result=freeze_candidates(items,source_bytes=source_bytes,source_receipt=source_receipt,paper_context=paper_context,
                             data_sha256=data_sha256,previous_set=existing_set)
    if result.get('success'):result['candidate']=deepcopy(result['candidates'][-1]);result=_seal(result)
    return result


def compare_source_conditions(frozen_candidate,actual_spec, *,source_bytes,source_receipt,paper_context,data_sha256,
                              candidate_set,prior_approval=None):
    try:
        if not _valid_frozen(frozen_candidate) or not _intact(candidate_set) or frozen_candidate.get('schema')!=SCHEMA or candidate_set.get('schema')!=SCHEMA:raise CandidateError('FROZEN_INTEGRITY_INVALID')
        if not isinstance(candidate_set.get('candidates'),list) or not 1<=len(candidate_set['candidates'])<=MAX_CANDIDATES or any(not _valid_frozen(c) for c in candidate_set['candidates']):raise CandidateError('CANDIDATE_SET_INVALID')
        # [수정: 0 이영 · Codex] 2026-10-01 04:24 KST — 외부 묶음의 주장 SHA를 믿지 않고 모든 후보 base/frozen/집합 지문을 재산출한다. 비교와 계산 사이 코드변경도 차단하며 원시값은 반환하지 않는다.
        members=candidate_set['candidates']
        pool_sha=_digest([{'candidate_id':c['candidate_id'],'base_sha256':c['base_sha256']} for c in members])
        if pool_sha!=candidate_set.get('candidate_set_sha256') or len({c['candidate_id'] for c in members})!=len(members) or any(c['bindings'].get('candidate_set_sha256')!=pool_sha for c in members):
            raise CandidateError('CANDIDATE_SET_BINDING_INVALID')
        matching=[c for c in members if c['candidate_id']==frozen_candidate['candidate_id']]
        if len(matching)!=1 or matching[0]['frozen_sha256']!=frozen_candidate['frozen_sha256']:raise CandidateError('STALE_CANDIDATE_SET')
        source,contexts=_source_state(source_bytes,source_receipt,paper_context)
        contract=frozen_candidate['source_condition_contract']
        current={'source_sha256':source['actual_sha256'],'source_receipt_sha256':source['receipt_sha256'],
                 'paper_context_sha256':source['paper_context_sha256'],'source_contract_sha256':_digest(contract),
                 'data_sha256':data_sha256,'spec_sha256':spec_sha256(actual_spec),'engine_revision':source_revision(),
                 'candidate_set_sha256':candidate_set['candidate_set_sha256']}
        old=deepcopy(frozen_candidate['bindings'])
        changed=[key for key in current if old.get(key)!=current[key]]
        if changed:return _blocked('STALE_FROZEN_BINDINGS',agreement='STALE',changed_bindings=changed,before_bindings=old,after_bindings=current)
        if prior_approval is not None and (not isinstance(prior_approval,dict) or prior_approval.get('candidate_bindings')!=dict(current,frozen_sha256=frozen_candidate['frozen_sha256'])):
            return _blocked('STALE_APPROVAL',agreement='STALE')
        proof=_condition_contract(contract,paper_context,contexts)
        groups=_spec_groups(actual_spec);diffs=[];unresolved=[]
        for field in FIELDS:
            entry=contract['fields'][field]
            if entry['value'] is not None and not _same(field,entry['value'],groups[field]):diffs.append({'field':field,'reason':'SOURCE_CONDITION_DIFFERS_FROM_ACTUAL_SPEC'})
            if entry['status']!='fact' or not proof[field]['location_bound'] or not proof[field]['lexical_support']:unresolved.append(field)
        ops=contract.get('unsupported_operations',[])
        method=actual_spec.get('method');unsupported=ops or ([] if method in SUPPORTED_METHODS else ['METHOD_NOT_SUPPORTED_FOR_PREVIEW'])
        ready=validate_spec(_preview_spec(actual_spec))['ready']
        agreement='MISMATCH' if diffs else 'UNRESOLVED' if unresolved or source['status']=='NOT_ACQUIRED' else 'EXACT'
        can_preview=not diffs and source['status']!='NOT_ACQUIRED' and not unsupported and ready
        # A falsely labelled fact with absent/wrong lexical support is not a conditional hypothesis.
        if any(contract['fields'][f]['status']=='fact' and (not proof[f]['location_bound'] or not proof[f]['lexical_support']) for f in unresolved):can_preview=False
        return {'success':True,'status':'SOURCE_CONDITIONS_'+agreement,'agreement':agreement,'field_diffs':diffs,
                'unresolved_fields':unresolved,'field_proof':proof,'unsupported_operations':unsupported,
                'can_preview':can_preview,'can_calculate':False,'can_approve':False,'semantic_ready':False,
                'approved':False,'verified':False,'candidate_bindings':dict(current,frozen_sha256=frozen_candidate['frozen_sha256']),
                'before_bindings':old,'after_bindings':current,'limits':list(LIMITS)}
    except (CandidateError,ValueError,TypeError,KeyError,OSError) as exc:
        return _blocked(str(exc) if isinstance(exc,CandidateError) else 'SOURCE_COMPARISON_INPUT_INVALID')



def _observed_denominator(spec,header,rows):
    # [수정: 0 이영 · Codex] 2026-10-01 04:44 KST — 기존 행 선택·결측 처리만 재사용해 명시 n/전체 행 분모를 평균보다 먼저 대조한다. 자유 문구나 개인별 수를 행 수로 추론하지 않고 미지원으로 둔다.
    selected=select_rows(header,rows,spec['filters'])
    if spec['method']=='mean':
        _,info=numeric_table(header,selected,[spec['variable']],spec['missing_tokens'],spec['missing_policy'])
        count=info['rows_used'];basis='NUMERIC_ROWS_USED'
    else:
        info={'rows_selected':len(selected)}
        count=len(selected);basis='SELECTED_ROWS'
    counts={key:info[key] for key in ('rows_selected','rows_used','rows_dropped_missing') if key in info}
    counts['rows_total']=len(rows)
    denominator=spec['denominator'].strip()
    match=re.fullmatch(r'n\s*=\s*(0|[1-9][0-9]*)',denominator)
    if match:
        expected=int(match.group(1))
    elif denominator=='all CSV rows':
        expected=len(rows);basis='ALL_CSV_ROWS'
    else:
        return {'status':'UNSUPPORTED_DENOMINATOR_BASIS','basis':None,'expected_count':None,
                'observed_count':count,'count_unit':'CSV_ROWS_NOT_DISTINCT_PEOPLE'},counts
    return {'status':'OBSERVED_ROW_COUNT_MATCH' if count==expected else 'OBSERVED_ROW_COUNT_MISMATCH',
            'basis':basis,'expected_count':expected,'observed_count':count,
            'count_unit':'CSV_ROWS_NOT_DISTINCT_PEOPLE'},counts

def preview_candidate(frozen_candidate,raw_data, *,source_bytes,source_receipt,paper_context,candidate_set,
                      actual_spec=None,prior_approval=None):
    try:
        if not isinstance(raw_data,bytes) or not 0<len(raw_data)<=MAX_BYTES:raise CandidateError('CSV_BYTES_REQUIRED')
        spec=frozen_candidate.get('candidate_spec') if actual_spec is None else actual_spec
        agreement=compare_source_conditions(frozen_candidate,spec,source_bytes=source_bytes,source_receipt=source_receipt,
                    paper_context=paper_context,data_sha256=_sha(raw_data),candidate_set=candidate_set,prior_approval=prior_approval)
        if not agreement.get('can_preview'):return dict(agreement,calculation=None)
        _public(raw_data.decode('utf-8-sig'))
        header,rows=read_csv(raw_data)
        engine=source_revision()
        if engine!=frozen_candidate['bindings']['engine_revision']:
            raise CandidateError('ENGINE_CHANGED_BEFORE_PREVIEW')
        denominator_check,counts=_observed_denominator(spec,header,rows)
        if denominator_check['status']!='OBSERVED_ROW_COUNT_MATCH':
            mismatch=denominator_check['status']=='OBSERVED_ROW_COUNT_MISMATCH'
            return dict(agreement,status='DENOMINATOR_'+('MISMATCH' if mismatch else 'UNRESOLVED'),
                        agreement='MISMATCH' if mismatch else 'UNRESOLVED',
                        error='DENOMINATOR_OBSERVATION_MISMATCH' if mismatch else 'DENOMINATOR_BASIS_UNSUPPORTED',
                        field_diffs=agreement['field_diffs']+([{'field':'denominator','reason':'OBSERVED_ROW_COUNT_DIFFERS_FROM_EXPLICIT_DENOMINATOR'}] if mismatch else []),
                        unsupported_operations=agreement['unsupported_operations']+([] if mismatch else ['DENOMINATOR_BASIS_NOT_SUPPORTED']),
                        denominator_check=denominator_check,counts=counts,calculation=None,can_preview=False,
                        can_calculate=False,can_approve=False,semantic_ready=False,preview_executed=False)
        if source_revision()!=engine:raise CandidateError('ENGINE_CHANGED_BEFORE_PREVIEW')
        result=gate.evaluate(_preview_spec(spec),raw_data)
        if source_revision()!=engine:raise CandidateError('ENGINE_CHANGED_DURING_PREVIEW')
        calculation={key:deepcopy(result[key]) for key in ('verdict','reason_code','computed','reported','tolerance','data_sha256','spec_sha256') if key in result}
        # Keep aggregate counts only; error rows/cells and the dataset itself never leave the function.
        _public(calculation)
        return dict(agreement,status='CONDITIONAL_PREVIEW',calculation=calculation,counts=counts,
                    numerical_match=result.get('verdict')=='MATCH',paper_condition_match=None,
                    source_contract_matches_spec=agreement['agreement']=='EXACT',denominator_check=denominator_check,
                    formal_verification=False,executed=False,preview_executed=True,can_approve=False,semantic_ready=False,
                    frozen_sha256=frozen_candidate['frozen_sha256'],candidate_set_sha256=candidate_set['candidate_set_sha256'],
                    previewed_at_kst=_now())
    except (CandidateError,ValueError,TypeError,KeyError,UnicodeError,OSError,GateError) as exc:
        code=str(exc) if isinstance(exc,CandidateError) else 'CSV_PREVIEW_'+exc.code if isinstance(exc,GateError) else 'PREVIEW_INPUT_OR_DATA_INVALID'
        return _blocked(code,calculation=None)


def candidate_prompt_payload(candidate_set):
    """Safe bounded metadata/conditions; no CSV rows, previews, approval or previous numeric results."""
    if not _intact(candidate_set):raise CandidateError('CANDIDATE_SET_INVALID')
    result={'schema':SCHEMA,'candidate_set_sha256':candidate_set['candidate_set_sha256'],
            'candidates':[{'candidate_id':c['candidate_id'],'source_condition_contract':deepcopy(c['source_condition_contract']),
                           'data_sha256':c['bindings']['data_sha256'],'frozen_sha256':c['frozen_sha256']} for c in candidate_set['candidates']],
            'approved':False,'semantic_ready':False}
    _public(result)
    return result

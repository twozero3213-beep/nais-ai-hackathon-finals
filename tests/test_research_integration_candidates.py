"""Frozen-condition attacks and sufficient scalar controls; no model/network calls."""
# [작성: 0 이영 · Codex] 2026-10-01 04:26 KST — 같은 평균·다른 집단, 위치 오류, 지문/후보 변경과 충분한 정상 근거를 함께 검증한다. 합성 단위시험이며 논문·AI 성능 실측이 아니다.
from copy import deepcopy
import hashlib
import json
from unittest.mock import Mock

import pytest
from core import research_integration_candidates as candidates
from evidence_gate.spec import empty_spec

RAW=b'group,score\nA,10\nA,30\nB,18\nB,22\n'
PAPER={'source_id':'synthetic-source','paper_version':'published-synthetic-1','source_url':'https://example.org/synthetic'}
QUOTE='The mean of score in group A is 20 points (n=2). Missing policy: error. Tolerance: 0.'
SOURCE=('Methods\n'+QUOTE+'\nUnrelated section\nDifferent text without the target evidence.\n').encode()
LOCATION={'source_id':'synthetic-source','locator':'Methods-1','quote':QUOTE}


@pytest.fixture(autouse=True)
def engine(monkeypatch):
    monkeypatch.setattr(candidates,'source_revision',lambda:'engine-1')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def receipt(source=SOURCE,paper=PAPER,span_end=None):
    end=source.find(b'Unrelated section') if span_end is None else span_end
    if end<1:end=len(source)
    return candidates.source_receipt_for_spans(source,source_url=paper['source_url'],paper_version=paper['paper_version'],
            spans=[{'locator':'Methods-1','start_byte':0,'end_byte':end}],source_kind='SYNTHETIC_SOURCE_BYTES')


def spec(raw=RAW,group='A',reported=20,method='mean',location=LOCATION):
    s=empty_spec('SYNTHETIC-CLAIM')
    s.update(method=method,reported_value=reported,variable='score' if method=='mean' else None,
             filters=[{'column':'group','operator':'eq','value':group}] if group else [],
             missing_policy='error' if method=='mean' else 'not_applicable',missing_tokens=['NA',''],
             denominator='n=2' if group else 'all CSV rows',unit='points' if method=='mean' else 'observations',
             data_fingerprint=sha(raw),tolerance=0,source_location=deepcopy(location))
    return s


def contract(s=None,paper=PAPER,location=LOCATION):
    s=spec() if s is None else s
    values=candidates._spec_groups(s)
    return {'contract_version':1,'paper_version':paper['paper_version'],'source_location':deepcopy(location),
            'fields':{field:{'status':'fact','value':deepcopy(values[field]),
                             'evidence':{'locator':location['locator'],'quote':location['quote']}} for field in candidates.FIELDS}}


def freeze(s=None,source=SOURCE,paper=PAPER,c=None,rc=None,cid='candidate-1',existing=None):
    s=spec() if s is None else s
    c=contract(s,paper=paper,location=s['source_location']) if c is None else c
    r=receipt(source,paper) if rc is None and source is not None else rc
    return candidates.freeze_candidate(c,s,source_bytes=source,source_receipt=r,paper_context=paper,
                data_sha256=s['data_fingerprint'],candidate_id=cid,existing_set=existing)


def compare(pool,s=None,source=SOURCE,paper=PAPER,rc=None,prior=None,index=0):
    row=pool['candidates'][index]
    return candidates.compare_source_conditions(row,row['candidate_spec'] if s is None else s,
            source_bytes=source,source_receipt=receipt(source,paper) if rc is None and source is not None else rc,
            paper_context=paper,data_sha256=row['bindings']['data_sha256'],candidate_set=pool,prior_approval=prior)


def preview(pool,raw=RAW,source=SOURCE,paper=PAPER,rc=None,index=0):
    return candidates.preview_candidate(pool['candidates'][index],raw,source_bytes=source,
            source_receipt=receipt(source,paper) if rc is None and source is not None else rc,
            paper_context=paper,candidate_set=pool)


def test_sufficient_grounded_mean_has_preview_but_never_approval():
    pool=freeze();assert pool['success']
    check=compare(pool)
    assert check['agreement']=='EXACT' and check['can_preview']
    report=preview(pool)
    assert report['calculation']['computed']==20 and report['numerical_match']
    assert report['counts']=={'rows_selected':2,'rows_used':2,'rows_dropped_missing':0,'rows_total':4}
    assert not report['semantic_ready'] and not report['can_approve'] and not report['approved'] and not report['formal_verification']
    assert report['preview_executed'] and not report['executed']
    assert report['paper_condition_match'] is None and report['source_contract_matches_spec'] is True
    assert report['denominator_check']['count_unit']=='CSV_ROWS_NOT_DISTINCT_PEOPLE'


@pytest.mark.parametrize('case',['mean_A','mean_B','actual_mismatch','all_rows','filtered_rows','complete_case'])
def test_six_sufficient_normal_controls(case):
    raw=RAW
    if case=='mean_B':
        quote=QUOTE.replace('group A','group B');s=spec(group='B')
    elif case=='actual_mismatch':
        quote=QUOTE.replace('is 20','is 21');s=spec(reported=21)
    elif case=='all_rows':
        quote='We count all CSV rows: 4 observations without filtering. Missing policy: not_applicable. Tolerance: 0.'
        s=spec(group=None,reported=4,method='row_count')
    elif case=='filtered_rows':
        quote='We count group A rows: 2 observations (n=2). Missing policy: not_applicable. Tolerance: 0.'
        s=spec(reported=2,method='row_count')
    elif case=='complete_case':
        raw=b'group,score\nA,10\nA,30\nA,NA\nB,18\nB,22\n'
        quote='The mean of score in group A is 20 points (n=2). Missing policy: complete_case. Tolerance: 0.'
        s=spec(raw=raw);s['missing_policy']='complete_case'
    else:quote=QUOTE;s=spec()
    source=('Methods\n'+quote+'\nUnrelated section\nNot evidence.\n').encode()
    location=dict(LOCATION,quote=quote);s['source_location']=location
    c=contract(s,location=location)
    pool=freeze(s,source=source,c=c)
    assert pool['success']
    report=preview(pool,raw=raw,source=source)
    assert report['status']=='CONDITIONAL_PREVIEW' and report['agreement']=='EXACT'
    assert report['numerical_match'] is (case!='actual_mismatch')
    assert not report['semantic_ready'] and not report['can_approve']
    if case=='complete_case':
        assert report['counts']['rows_selected']==3 and report['counts']['rows_used']==2 and report['counts']['rows_dropped_missing']==1


def test_same_mean_wrong_group_is_source_mismatch_before_engine(monkeypatch):
    original=spec(group='A');wrong=spec(group='B');c=contract(original)
    pool=freeze(wrong,c=c)
    engine=Mock(side_effect=AssertionError('Do not compute a mismatching source condition'))
    monkeypatch.setattr(candidates.gate,'evaluate',engine)
    report=preview(pool)
    assert report['agreement']=='MISMATCH'
    assert report['field_diffs']==[{'field':'filters','reason':'SOURCE_CONDITION_DIFFERS_FROM_ACTUAL_SPEC'}]
    assert report['calculation'] is None and not report['can_approve']
    engine.assert_not_called()


def test_fact_B_with_existing_quote_A_is_unresolved_not_truth(monkeypatch):
    wrong=spec(group='B');pool=freeze(wrong)
    engine=Mock(side_effect=AssertionError('Wrong label is not supported by quoted A'))
    monkeypatch.setattr(candidates.gate,'evaluate',engine)
    report=preview(pool)
    assert report['agreement']=='UNRESOLVED' and 'filters' in report['unresolved_fields']
    assert report['field_proof']['filters']['lexical_support'] is False
    assert not report['can_preview'] and not report['can_approve']
    engine.assert_not_called()


@pytest.mark.parametrize('field,value',[('denominator','n=999'),('unit','mg'),('missing',{'policy':'complete_case','tokens':['NA','']}),
    ('calculation',{'method':'mean','variable':'score','reported_value':20,'tolerance':1})])
def test_source_contract_group_mismatch_even_with_numeric_match(field,value,monkeypatch):
    original=spec();c=contract(original);wrong=deepcopy(original)
    if field=='missing':wrong.update(missing_policy=value['policy'],missing_tokens=value['tokens'])
    elif field=='calculation':wrong['tolerance']=1
    else:wrong[field]=value
    pool=freeze(wrong,c=c)
    engine=Mock(side_effect=AssertionError('Source mismatch precedes arithmetic'))
    monkeypatch.setattr(candidates.gate,'evaluate',engine)
    result=preview(pool)
    assert result['agreement']=='MISMATCH' and any(x['field']==field for x in result['field_diffs'])
    assert not result['can_approve'];engine.assert_not_called()


def test_quote_present_elsewhere_does_not_satisfy_wrong_location(monkeypatch):
    source=SOURCE+b'Wrong position has unrelated content.'
    rc=receipt(source);start=len(SOURCE)
    other=candidates.source_receipt_for_spans(source,source_url=PAPER['source_url'],paper_version=PAPER['paper_version'],
          spans=[{'locator':'Wrong-position','start_byte':start,'end_byte':len(source)}])
    rc['locations'].update(other['locations'])
    c=contract();c['fields']['filters']['evidence']['locator']='Wrong-position'
    pool=freeze(source=source,c=c,rc=rc)
    engine=Mock(side_effect=AssertionError('No whole-document quote fallback'))
    monkeypatch.setattr(candidates.gate,'evaluate',engine)
    result=preview(pool,source=source,rc=rc)
    assert result['agreement']=='UNRESOLVED' and result['field_proof']['filters']['location_bound'] is False
    assert not result['can_preview'];engine.assert_not_called()


def test_declared_sha_without_bytes_is_not_acquired(monkeypatch):
    paper=dict(PAPER,source_sha256=sha(SOURCE));pool=freeze(source=None,paper=paper,rc={'actual_sha256':sha(SOURCE)})
    assert pool['success'] and pool['candidate']['source_state']['status']=='NOT_ACQUIRED'
    engine=Mock(side_effect=AssertionError('No source bytes'))
    monkeypatch.setattr(candidates.gate,'evaluate',engine)
    result=preview(pool,source=None,paper=paper,rc={'actual_sha256':sha(SOURCE)})
    assert result['agreement']=='UNRESOLVED' and not result['can_preview'];engine.assert_not_called()


def test_hypothesis_preview_is_conditional_and_never_closest_selection():
    c=contract();c['fields']['filters']['status']='hypothesis'
    pool=freeze(c=c)
    report=preview(pool)
    assert report['status']=='CONDITIONAL_PREVIEW' and report['agreement']=='UNRESOLVED'
    assert report['numerical_match'] and not report['semantic_ready'] and not report['can_approve']
    assert not hasattr(candidates,'select_closest_candidate')


def test_missing_source_field_stays_missing_in_conditional_preview():
    c=contract();c['fields']['denominator']={'status':'missing','value':None,'evidence':None}
    pool=freeze(c=c);report=preview(pool)
    assert report['agreement']=='UNRESOLVED' and 'denominator' in report['unresolved_fields']
    assert pool['candidate']['source_condition_contract']['fields']['denominator']['value'] is None
    assert not report['can_approve']


def test_added_evidence_re_freezes_and_retains_before_after_pool_sha():
    c=contract();c['fields']['filters']['status']='hypothesis';old=freeze(c=c)
    updated={'candidate_id':'candidate-1','source_condition_contract':contract(),'candidate_spec':spec()}
    new=candidates.freeze_candidates([updated],source_bytes=SOURCE,source_receipt=receipt(),paper_context=PAPER,data_sha256=sha(RAW),previous_set=old)
    assert new['previous_candidate_set_sha256']==old['candidate_set_sha256']
    assert new['candidate_set_sha256']!=old['candidate_set_sha256']
    assert compare(new)['agreement']=='EXACT'
    assert compare(old)['agreement']=='UNRESOLVED'
    assert old['candidate']['source_condition_contract']['fields']['filters']['status']=='hypothesis'


def test_add_candidate_invalidates_old_approval_and_frozen_members():
    one=freeze();two=freeze(cid='candidate-2',existing=one)
    assert two['success'] and len(two['candidates'])==2
    assert two['previous_candidate_set_sha256']==one['candidate_set_sha256']
    assert two['candidates'][0]['frozen_sha256']!=one['candidate']['frozen_sha256']
    result=candidates.compare_source_conditions(one['candidate'],spec(),source_bytes=SOURCE,source_receipt=receipt(),paper_context=PAPER,
                 data_sha256=sha(RAW),candidate_set=two)
    assert result['error']=='STALE_CANDIDATE_SET' and not result['can_approve']


def test_maximum_three_candidates_and_no_automatic_selection():
    pool=freeze()
    pool=freeze(cid='candidate-2',existing=pool)
    pool=freeze(cid='candidate-3',existing=pool)
    assert len(pool['candidates'])==3 and all(not c['can_approve'] for c in pool['candidates'])
    fourth=freeze(cid='candidate-4',existing=pool)
    assert fourth['error']=='CANDIDATE_COUNT_INVALID'
    assert 'selected_candidate' not in pool


def test_approval_bindings_cannot_activate_approval():
    pool=freeze();current=compare(pool)
    prior={'active':True,'approved':True,'candidate_bindings':current['candidate_bindings']}
    result=compare(pool,prior=prior)
    assert result['agreement']=='EXACT' and not result['can_approve'] and not result['semantic_ready'] and not result['approved']
    prior['candidate_bindings']['data_sha256']='0'*64
    assert compare(pool,prior=prior)['error']=='STALE_APPROVAL'


@pytest.mark.parametrize('dimension',['source','paper','data','spec','engine'])
def test_each_changed_binding_is_stale_and_retains_sha_dimensions(dimension,monkeypatch):
    pool=freeze();s=spec();paper=deepcopy(PAPER);source=SOURCE;data_sha=sha(RAW)
    if dimension=='source':source=SOURCE+b'New source material.'
    if dimension=='paper':paper['paper_version']='published-synthetic-2'
    if dimension=='data':data_sha=sha(RAW+b'\n')
    if dimension=='spec':s['tolerance']=1
    if dimension=='engine':monkeypatch.setattr(candidates,'source_revision',lambda:'engine-2')
    result=candidates.compare_source_conditions(pool['candidate'],s,source_bytes=source,source_receipt=receipt(source,paper),
            paper_context=paper,data_sha256=data_sha,candidate_set=pool)
    assert result['agreement']=='STALE' and result['before_bindings']!=result['after_bindings']
    assert result['changed_bindings'] and not result['can_preview']


def test_source_span_hash_tamper_blocked():
    pool=freeze();rc=receipt();rc['locations']['Methods-1']['context_sha256']='0'*64
    assert compare(pool,rc=rc)['error']=='SOURCE_SPAN_SHA256_MISMATCH'


def test_frozen_and_pool_hash_recomputed_not_claimed_by_input():
    pool=freeze();bad=deepcopy(pool['candidate']);bad['source_condition_contract']['fields']['unit']['value']='mg'
    bad=candidates._seal(bad)
    result=candidates.compare_source_conditions(bad,spec(),source_bytes=SOURCE,source_receipt=receipt(),paper_context=PAPER,data_sha256=sha(RAW),candidate_set=pool)
    assert result['error']=='FROZEN_INTEGRITY_INVALID'
    badpool=deepcopy(pool);badpool['candidate_set_sha256']='0'*64;badpool=candidates._seal(badpool)
    result=candidates.compare_source_conditions(pool['candidate'],spec(),source_bytes=SOURCE,source_receipt=receipt(),paper_context=PAPER,data_sha256=sha(RAW),candidate_set=badpool)
    assert result['error']=='CANDIDATE_SET_BINDING_INVALID'


def test_fake_confirmation_fields_are_rejected():
    c=contract();c['fields']['filters']['confirmed']=True
    assert freeze(c=c)['error']=='FIELD_STATUS_INVALID'
    c=contract();c['approved']=True
    assert freeze(c=c)['error']=='SOURCE_CONTRACT_INVALID'


@pytest.mark.parametrize('operation',['unit_conversion','per_subject_aggregation','weighted_calculation'])
def test_unsupported_operation_distinct_no_engine(operation,monkeypatch):
    c=contract();c['unsupported_operations']=[operation];pool=freeze(c=c)
    engine=Mock(side_effect=AssertionError('Do not infer unsupported operations'))
    monkeypatch.setattr(candidates.gate,'evaluate',engine)
    result=preview(pool)
    assert operation in result['unsupported_operations'] and not result['can_preview'];engine.assert_not_called()


def test_before_freezing_is_not_computable(monkeypatch):
    engine=Mock(side_effect=AssertionError('No unsealed calculation'))
    monkeypatch.setattr(candidates.gate,'evaluate',engine)
    result=candidates.preview_candidate({'candidate_spec':spec()},RAW,source_bytes=SOURCE,source_receipt=receipt(),paper_context=PAPER,candidate_set={})
    assert result['error']=='FROZEN_INTEGRITY_INVALID';engine.assert_not_called()


def test_engine_change_between_compare_and_gate_blocked(monkeypatch):
    pool=freeze();engine=Mock(side_effect=AssertionError('Do not run changed code'))
    monkeypatch.setattr(candidates.gate,'evaluate',engine)
    values=iter(['engine-1','engine-2'])
    monkeypatch.setattr(candidates,'source_revision',lambda:next(values))
    result=preview(pool)
    assert result['error']=='ENGINE_CHANGED_BEFORE_PREVIEW';engine.assert_not_called()


def test_non_numeric_data_error_does_not_expose_cells():
    raw=b'group,score\nA,DATA_ROW_SENTINEL_XYZ\nA,30\nB,18\nB,22\n'
    pool=freeze(spec(raw=raw));result=preview(pool,raw=raw)
    assert result['error']=='CSV_PREVIEW_BAD_VALUE' and result['calculation'] is None
    assert 'DATA_ROW_SENTINEL_XYZ' not in json.dumps(result)
    assert not result['can_approve']


def test_prompt_and_reports_exclude_csv_rows_and_prior_computed_values():
    pool=freeze();payload=candidates.candidate_prompt_payload(pool)
    text=json.dumps(payload)
    assert RAW.decode() not in text and 'computed' not in text and 'numerical_match' not in text
    assert 'candidate_spec' not in text and 'source_condition_contract' in text
    assert payload['approved'] is False and payload['semantic_ready'] is False


def test_only_observation_time_change_is_not_condition_change():
    pool=freeze();rc=receipt();rc['bound_at_kst']='2026-10-01T04:30:00+09:00'
    assert compare(pool,rc=rc)['agreement']=='EXACT'


def test_int_float_representation_matches_without_rounding():
    s=spec();s['reported_value']=20.0;s['tolerance']=0.0
    pool=freeze(s,c=contract(spec()))
    assert compare(pool)['agreement']=='EXACT'
    c=contract(spec());c['fields']['calculation']['value']['reported_value']=20.0001
    pool=freeze(s,c=c)
    assert compare(pool)['agreement']=='MISMATCH'


def test_receipt_rejects_unbounded_or_ambiguous_spans():
    with pytest.raises(candidates.CandidateError):
        candidates.source_receipt_for_spans(SOURCE,source_url=PAPER['source_url'],paper_version=PAPER['paper_version'],spans=[{'locator':'wrong','start_byte':0,'end_byte':len(SOURCE)+1}])
    with pytest.raises(candidates.CandidateError):
        candidates.source_receipt_for_spans(SOURCE,source_url='https://example.org?token=mock-value',paper_version=PAPER['paper_version'],spans=[{'locator':'wrong','start_byte':0,'end_byte':2}])


# [수정: 0 이영 · Codex] 2026-10-01 04:44 KST — 실제 행 분모·선언 원문 지문·인접 숫자/단위의 공격을 추가하고 의미 사실을 자동 확정하지 않는 정상 미리보기를 보존한다.
def test_same_mean_different_observed_denominator_blocks_before_scalar(monkeypatch):
    raw=b'group,score\nA,10\nA,30\nA,10\nA,30\n'
    pool=freeze(spec(raw=raw))
    engine=Mock(side_effect=AssertionError('The same mean with four rows is not n=2'))
    monkeypatch.setattr(candidates.gate,'evaluate',engine)
    result=preview(pool,raw=raw)
    assert result['agreement']=='MISMATCH' and result['error']=='DENOMINATOR_OBSERVATION_MISMATCH'
    assert result['denominator_check']['expected_count']==2 and result['denominator_check']['observed_count']==4
    assert result['calculation'] is None and not result['can_preview'] and not result['can_approve']
    engine.assert_not_called()


@pytest.mark.parametrize('denominator',['n=2 participants','two distinct people','2 subjects'])
def test_per_person_or_free_text_denominator_is_not_inferred_as_rows(denominator,monkeypatch):
    s=spec();s['denominator']=denominator
    quote=QUOTE.replace('n=2',denominator);source=('Methods\n'+quote+'\nUnrelated section\nEnd.').encode()
    s['source_location']=dict(LOCATION,quote=quote)
    pool=freeze(s,source=source,c=contract(s,location=s['source_location']))
    engine=Mock(side_effect=AssertionError('Distinct people require an explicit unsupported aggregation'))
    monkeypatch.setattr(candidates.gate,'evaluate',engine)
    result=preview(pool,source=source)
    assert result['error']=='DENOMINATOR_BASIS_UNSUPPORTED'
    assert result['agreement']=='UNRESOLVED' and not result['can_preview']
    assert result['denominator_check']['count_unit']=='CSV_ROWS_NOT_DISTINCT_PEOPLE'
    engine.assert_not_called()


def test_declared_source_sha_must_match_actual_received_bytes():
    paper=dict(PAPER,source_sha256='0'*64)
    assert freeze(paper=paper)['error']=='DECLARED_SOURCE_SHA256_MISMATCH'
    paper['source_sha256']=sha(SOURCE)
    assert freeze(paper=paper)['success']


@pytest.mark.parametrize('field,stated,actual',[('denominator','n=2','n=20'),('unit','mg','mg/kg')])
def test_lexical_substring_is_not_full_numeric_or_unit_support(field,stated,actual,monkeypatch):
    s=spec();s[field]=stated
    original='n=2' if field=='denominator' else 'points'
    quote=QUOTE.replace(original,actual);source=('Methods\n'+quote+'\nUnrelated section\nEnd.').encode()
    s['source_location']=dict(LOCATION,quote=quote)
    pool=freeze(s,source=source,c=contract(s,location=s['source_location']))
    engine=Mock(side_effect=AssertionError('Substring is not full condition support'))
    monkeypatch.setattr(candidates.gate,'evaluate',engine)
    result=preview(pool,source=source)
    assert result['agreement']=='UNRESOLVED' and result['field_proof'][field]['lexical_support'] is False
    assert not result['can_preview'];engine.assert_not_called()


# [수정: 0 이영 · Codex] 2026-10-01 04:49 KST — 전후 지문 기록과 반환값의 입력 불변성을 검증한다. 시험 결과는 모의 조건계약 범위이며 독립 AI 검증 완료를 뜻하지 않는다.
def test_refreeze_records_each_before_after_binding_dimension():
    old=freeze();new=freeze(cid='candidate-2',existing=old)
    changes=new['binding_changes']
    existing=changes[0];added=changes[1]
    assert existing['before_bindings']['frozen_sha256']==old['candidate']['frozen_sha256']
    assert existing['after_bindings']['candidate_set_sha256']==new['candidate_set_sha256']
    assert set(existing['changed_bindings'])=={'candidate_set_sha256','frozen_sha256'}
    assert added['before_bindings'] is None and added['after_bindings']['source_sha256']==sha(SOURCE)
    assert {'source_sha256','source_receipt_sha256','source_contract_sha256','paper_context_sha256','data_sha256','spec_sha256','engine_revision','candidate_set_sha256','frozen_sha256'}==set(added['after_bindings'])


def test_returned_metadata_mutation_does_not_change_frozen_inputs():
    pool=freeze();before=deepcopy(pool)
    report=compare(pool);report['before_bindings']['source_sha256']='0'*64
    payload=candidates.candidate_prompt_payload(pool)
    payload['candidates'][0]['source_condition_contract']['fields']['unit']['value']='mg'
    assert pool==before and compare(pool)['agreement']=='EXACT'

from pathlib import Path
import pandas as pd
from core.models import Claim
from core.provenance_case28 import candidate, ProvenanceRecord
from core.lifecycle_case28 import append_event, for_claim
from core.typed_contracts import build_typed_contract, check_evidence_sufficiency
from core.executor import execute_contract


def inferential_claim():
    c=Claim('T-01','처리군과 대조군은 유의하게 달랐다.',None,column='outcome_pct',group_column='group',group_a='T',group_b='C')
    c.decomposition={'claim_kind':'comparison'}
    c.method_candidate='welch_t'; c.method_candidate_source='system_candidate'
    c.semantic_confirmed=True
    c.missing_policy='complete_case'; c.missing_policy_confirmed=True
    c.analysis_population='all randomized'; c.estimand='mean difference'; c.variance_estimator='welch'; c.multiplicity_policy='none_reported'; c.analysis_spec_confirmed=True
    return c


def test_evidence_confirmation_does_not_confirm_method():
    c=inferential_claim()
    assert c.semantic_confirmed is True
    assert c.method_confirmed is False
    assert c.analysis_method == ''
    ctr=build_typed_contract(c,'x.csv','hash')
    chk=check_evidence_sufficiency(ctr,pd.DataFrame({'outcome_pct':[1,2],'group':['T','C']}))
    assert not chk.executable
    assert 'method confirmation' in chk.missing


def test_method_confirmation_makes_method_executable_when_other_requirements_complete():
    c=inferential_claim(); c.method_confirmed=True; c.analysis_method='welch_t'
    ctr=build_typed_contract(c,'x.csv','hash')
    df=pd.DataFrame({'outcome_pct':[1.,2.,3.,4.],'group':['T','T','C','C']})
    chk=check_evidence_sufficiency(ctr,df)
    assert chk.executable


def test_provenance_record_confirmation_is_explicit():
    r=candidate('welch_t',source='system_candidate',source_location='PDF p.4',score=.81)
    assert not r.confirmed
    r.confirm('HUMAN')
    assert r.confirmed and r.confirmed_by=='HUMAN' and r.confirmed_at


def test_lifecycle_is_claim_scoped_and_deduplicated():
    store=[]
    append_event(store,'C-1','EVIDENCE_PROPOSED',detail='outcome_pct')
    append_event(store,'C-1','EVIDENCE_PROPOSED',detail='outcome_pct')
    append_event(store,'C-2','EVIDENCE_PROPOSED',detail='age')
    assert len(store)==2
    assert len(for_claim(store,'C-1'))==1


def test_canonical_executor_has_no_version_delegate():
    text=Path('core/executor.py').read_text(encoding='utf-8')
    assert 'executor_case25' not in text and 'executor_case24 import' not in text


def test_canonical_presentation_has_no_version_delegate():
    text=Path('core/presentation.py').read_text(encoding='utf-8')
    assert 'presenter_case23 import' not in text

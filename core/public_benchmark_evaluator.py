"""Evaluation-only helpers for case33 blind public benchmark.

Production code never imports hidden gold. Tests pass gold explicitly into this evaluator after the
blind pipeline has completed. This separation prevents benchmark answers from leaking into proposal
or contract generation.
"""
from __future__ import annotations

def evaluate_blind_results(prediction:dict,gold:dict):
    pred={x['source_id']:x for x in prediction['claims']}; g=gold['gold']; cases=[]
    for cid,truth in g.items():
        p=pred.get(cid,{})
        should_block=truth['expected_action']=='BLOCK'
        proposal_scored=bool(truth.get('supported_after_human_confirmation'))
        case={
            'claim_id':cid,
            'claim_found':cid in pred,
            'action_correct':p.get('action')==truth['expected_action'],
            'correct_blocking':(p.get('action')=='BLOCK') if should_block else True,
            'contract_type_correct': (p.get('contract_type')==truth.get('contract_type')) if proposal_scored else True,
            'method_correct': (p.get('method')==truth.get('method')) if proposal_scored else True,
            'variables_correct': ({p.get('x'),p.get('y')}=={truth.get('x'),truth.get('y')}) if proposal_scored else True,
        }
        cases.append(case)
    n=len(cases) or 1
    metrics={k:sum(bool(c[k]) for c in cases)/n for k in ['claim_found','action_correct','correct_blocking','contract_type_correct','method_correct','variables_correct']}
    return {'n':len(cases),'metrics':metrics,'cases':cases}

def oracle_confirmed_execution(data_path, truth:dict):
    """Evaluation-only execution after hidden reference choices are applied.

    This is intentionally outside production. It separates proposal quality from executor quality:
    a human/oracle can supply the confirmed X/Y/method, after which the normal deterministic
    contract/executor path must reproduce the public-data result.
    """
    import pandas as pd
    from pathlib import Path
    from .models import Claim
    from .decision_provenance import proposed
    from .typed_contracts import build_typed_contract, check_evidence_sufficiency
    from .executor import execute_contract
    from .analysis_spec_case25 import build_analysis_spec
    from .provenance import dataframe_hash
    df=pd.read_csv(data_path)
    c=Claim(claim_id='ORACLE',text='oracle-confirmed public claim',claim_type='inferential')
    c.decomposition={'claim_kind':'correlation','x_hint':truth['x']}
    c.x_column=truth['x']; c.column=truth['y']; c.analysis_method=truth['method']; c.method_candidate=truth['method']
    er=proposed(truth['y'],source='hidden_evaluation_reference').select('EVALUATOR').confirm('EVALUATOR')
    mr=proposed(truth['method'],source='hidden_evaluation_reference').select('EVALUATOR').confirm('EVALUATOR')
    c.evidence_provenance=er.to_dict(); c.method_provenance=mr.to_dict(); c.semantic_confirmed=True; c.method_confirmed=True
    c.missing_policy='complete_case'; c.missing_policy_confirmed=True
    c.analysis_population='all available paired observations'; c.estimand='Pearson correlation'; c.variance_estimator='classical'; c.multiplicity_policy='none_reported'; c.analysis_spec_confirmed=True
    contract=build_typed_contract(c,Path(data_path).name,dataframe_hash(df)); check=check_evidence_sufficiency(contract,df)
    run=execute_contract(contract,df,build_analysis_spec(c)) if check.executable else {'state':'BLOCKED','reason':check.reason}
    return run

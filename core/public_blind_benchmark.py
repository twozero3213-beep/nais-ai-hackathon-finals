"""Blind public-research benchmark runner for case33.

case33 BENCHMARK ARCHITECTURE
FAILURE: case32's public benchmark used benchmark-specific calculations that already knew the
correct variables and methods. That proved arithmetic reproduction, not the general Evidence Gate
proposal/contract pipeline.
RISK: a benchmark can look perfect while bypassing the product path being evaluated.
WHY: production benchmark code must see only public-paper inputs and raw data. Hidden reference labels belong only to the evaluation layer and MUST NOT be imported here.
CHANGE: run public claim excerpts through the same semantic proposal and typed-contract routing
used by the app, then fail closed when the current contract family cannot represent the claim.
REGRESSION: tests/test_case33.py verifies production code does not reference hidden evaluation labels.
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from .paths import PROJECT_ROOT
from .models import Claim
from .semantic import decompose_claim, build_plan
from .typed_contracts import build_typed_contract, check_evidence_sufficiency, ContractType
from .provenance import dataframe_hash

INPUT_PATH=PROJECT_ROOT/'data'/'public_benchmark'/'source_claims_case33.json'
DATA_PATH=PROJECT_ROOT/'data'/'public_benchmark'/'penguins.csv'

UNSUPPORTED_PATTERNS={
    'principal component':'PCA is not represented by the current typed contract set',
    'missing values':'dataset-level missingness is not represented by the current typed contract set',
    'within species':'stratified/repeated association is not represented by the current typed contract set',
}

def load_public_inputs():
    return json.loads(INPUT_PATH.read_text(encoding='utf-8'))

def _generic_association_pair(text:str, df:pd.DataFrame):
    """Find two explicitly named numeric columns without study-specific aliases.

    WHY: public papers often use human-readable variable names while CSV uses snake_case.
    Matching explicit column-name tokens is a reusable schema rule, not a Palmer-specific mapping.
    """
    low=' '.join(str(text).lower().replace('_',' ').split())
    hits=[]
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        phrase=' '.join(col.lower().replace('_',' ').split())
        phrase=phrase.replace(' mm','').replace(' g','')
        if phrase and phrase in low:
            hits.append(col)
    return hits[:2]

def run_blind_public_pipeline(input_path=INPUT_PATH,data_path=DATA_PATH):
    spec=json.loads(Path(input_path).read_text(encoding='utf-8'))
    df=pd.read_csv(data_path); d_hash=dataframe_hash(df)
    rows=[]
    for item in spec['claims']:
        text=item['text']; low=text.lower()
        unsupported=next((reason for needle,reason in UNSUPPORTED_PATTERNS.items() if needle in low),None)
        decomp=decompose_claim(text,None); plan=build_plan(text,decomp,df)
        claim=Claim(claim_id=item['source_id'],text=text,original_value=None,column=plan.get('recommended_column',''),aggregation=plan.get('aggregation','mean'),claim_type='inferential')
        claim.source_page=item.get('page');claim.source_quote=text;claim.decomposition=decomp;claim.evidence_candidates=plan.get('candidates',[])
        claim.filters=[{'column':x['column'],'value':x['value']} for x in plan.get('filters',[])]
        claim.method_candidate=plan.get('aggregation','');claim.method_candidate_source='system_candidate'
        pair=_generic_association_pair(text,df)
        if decomp.get('claim_kind')=='correlation' and len(pair)==2:
            claim.x_column=pair[0];claim.column=pair[1]
            # Proposal only: do not silently confirm either evidence or method.
            claim.evidence_candidates=[{'column':pair[1],'score':0.7,'reason':'explicit variable name in public-paper claim'}]
        contract=build_typed_contract(claim,Path(data_path).name,d_hash)
        check=check_evidence_sufficiency(contract,df)
        action='BLOCK' if unsupported or not check.executable else 'EXECUTE'
        rows.append({
            'source_id':item['source_id'],'page':item.get('page'),'text':text,
            'decomposition':decomp,'proposal':plan,'contract_type':contract.contract_type.value,
            'x':getattr(contract,'x',''),'y':getattr(contract,'y',''),'method':contract.method,
            'action':action,'blocked_reason':unsupported or check.reason,
            'dataset_hash':d_hash,
        })
    return {'study_id':spec['study_id'],'article_url':spec['article_url'],'claims':rows}

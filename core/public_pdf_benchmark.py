"""case34 blind public-PDF pipeline.

Production receives PDF bytes and raw data only. Hidden reference labels are deliberately absent.
The same local Claim extraction, semantic proposal, typed-contract and fail-closed rules used by the
application are reused here.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from .pdf_claims import extract_pdf_pages, extract_numeric_claims
from .models import Claim
from .semantic import decompose_claim, build_plan
from .typed_contracts import build_typed_contract, check_evidence_sufficiency
from .provenance import dataframe_hash

# [작성: 전문가7] 2026-09-23
# 무엇을: Claim 문장에서 현재 production 엔진이 명시적으로 지원하지 않는 분석 가족을 보수적으로 식별한다.
# 왜: 모든 BLOCK을 같은 상태로 표시하면 사람 확인 후 진행 가능한 Claim과 현재 엔진 미지원 Claim이 혼동된다.
# 검증: tests/test_case35.py의 capability 분류 테스트로 확인.
def unsupported_capability_reason(text: str) -> str:
    """입력: Claim 원문. 출력: 명시적 미지원 사유, 없으면 빈 문자열."""
    low=str(text).lower()
    if any(k in low for k in ("principal component","pca","주성분")):
        return "PCA 검증계약은 현재 production 엔진에서 지원하지 않습니다."
    if any(k in low for k in ("within species","stratified","층화")):
        return "층화/하위집단별 연관성 검증계약은 현재 production 엔진에서 지원하지 않습니다."
    return ""

# [작성: 전문가4] 2026-09-23
# 무엇을: 실제 PDF bytes와 CSV를 일반 Claim 파이프라인으로 처리하는 블라인드 벤치마크 진입점.
# 왜: case33의 curated Claim 입력은 Claim extraction 성능을 평가하지 못했다. benchmark 전용 정답 계산 대신 production 경로를 재사용한다.
# 검증: tests/test_case34.py의 PDF fixture로 추출→계약→차단 경로를 실행해 통과.
def run_public_pdf_pipeline(pdf_bytes: bytes, data_path: str | Path, claim_limit: int = 200) -> dict:
    """입력: PDF bytes, CSV 경로. 출력: 추출 Claim과 proposal/contract/action 목록 dict."""
    data_path=Path(data_path); df=pd.read_csv(data_path); d_hash=dataframe_hash(df)
    pages=extract_pdf_pages(pdf_bytes); extracted=extract_numeric_claims(pages, limit=claim_limit); rows=[]
    for item in extracted:
        text=item['text']; decomp=decompose_claim(text,item.get('value')); plan=build_plan(text,decomp,df)
        c=Claim(claim_id=item['claim_id'],text=text,original_value=item.get('value'),source_page=item.get('page'),source_quote=text,claim_type=item.get('claim_type','inferential'),reported_p_value=item.get('p_value'),reported_p_operator=item.get('p_operator',''),reported_effect=item.get('reported_effect'),effect_kind=item.get('effect_kind',''),reported_ci95=item.get('ci95'))
        c.decomposition=decomp;c.evidence_candidates=plan.get('candidates',[]);c.filters=[{'column':x['column'],'value':x['value']} for x in plan.get('filters',[])];c.column=plan.get('recommended_column','');c.method_candidate=plan.get('aggregation','');c.method_candidate_source='system_candidate';c.x_column=plan.get('x_column','') or c.x_column;c.group_column=plan.get('group_column','') or c.group_column;c.group_a=plan.get('group_a','') or c.group_a;c.group_b=plan.get('group_b','') or c.group_b
        contract=build_typed_contract(c,data_path.name,d_hash); check=check_evidence_sufficiency(contract,df)
        # [작성: 전문가7] 2026-09-23
        # 무엇을: 블라인드 PDF benchmark에서도 사람 확인 전 실행을 금지.
        # 왜: gold나 자동확정으로 fail-closed 원칙을 우회하면 제품 성능을 과대평가한다.
        # 검증: tests/test_case34.py에서 미확정 Claim이 BLOCK인지 확인.
        unsupported=unsupported_capability_reason(text)
        if unsupported:
            support_state='UNSUPPORTED'; next_action='BLOCK_UNSUPPORTED'; blocked_reason=unsupported
        elif check.executable:
            support_state='READY'; next_action='EXECUTE'; blocked_reason=''
        else:
            support_state='REVIEWABLE'; next_action='BLOCK_HUMAN_CONFIRMATION'; blocked_reason=check.reason
        action='EXECUTE' if next_action=='EXECUTE' else 'BLOCK'
        rows.append({'claim_id':c.claim_id,'page':c.source_page,'text':c.text,'claim_type':c.claim_type,'decomposition':decomp,'proposal':plan,'contract_type':contract.contract_type.value,'method_candidate':c.method_candidate,'evidence_candidates':c.evidence_candidates,'support_state':support_state,'next_action':next_action,'action':action,'blocked_reason':blocked_reason,'dataset_hash':d_hash,'stage_trace':{'claim_extracted':True,'evidence_proposed':bool(c.evidence_candidates),'method_proposed':bool(c.method_candidate),'human_confirmed':False,'executed':False}})
    return {'schema_version':'case35-public-pdf-prediction-1','pages':len(pages),'extracted_claims':rows,'dataset_hash':d_hash,'claim_limit':claim_limit,'claim_limit_reached':len(extracted)>=claim_limit,'gold_accessed':False}

"""Claim lifecycle timeline helpers. Pure functions so UI/API clients can reuse them."""
from __future__ import annotations
from datetime import datetime, timezone

LABELS={
 "CLAIM_EXTRACTED":"Claim 추출","EVIDENCE_PROPOSED":"근거 후보 제안","EVIDENCE_CONFIRMED":"근거 확정",
 "METHOD_PROPOSED":"분석방법 후보","METHOD_CONFIRMED":"분석방법 확정","ANALYSIS_POLICY_CONFIRMED":"분석 명세 확정",
 "CONTRACT_BLOCKED":"실행 차단","CONTRACT_EXECUTED":"결정론적 재실행","REPRODUCTION_RESULT":"재현 결과",
 "VALUE_REVISED":"보고값 수정","REVERIFIED":"재검증","APPROVED":"최종 승인","SCOPE_SPEC_CONFIRMED":"범위 명세 확정"
}

def append_event(store:list, claim_id:str, name:str, *, actor="SYSTEM", detail="", source=""):
    item={"at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"claim_id":claim_id,"event":name,
          "label":LABELS.get(name,name),"actor":actor,"detail":detail,"source":source}
    key=(claim_id,name,actor,detail,source)
    if not any((x.get("claim_id"),x.get("event"),x.get("actor"),x.get("detail"),x.get("source"))==key for x in store):
        store.append(item)
    return item

def for_claim(store:list, claim_id:str):
    return [x for x in store if x.get("claim_id")==claim_id]

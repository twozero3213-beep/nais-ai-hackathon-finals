"""Claim lifecycle event names and helper for case25 auditability."""
EVENTS={
 'CLAIM_EXTRACTED','EVIDENCE_PROPOSED','EVIDENCE_SELECTED','EVIDENCE_CONFIRMED','METHOD_PROPOSED','METHOD_SELECTED','METHOD_CONFIRMED','CONTRACT_CREATED','HUMAN_CONFIRMED',
 'ANALYSIS_POLICY_CONFIRMED','CONTRACT_BLOCKED','CONTRACT_EXECUTED',
 'REPRODUCTION_RESULT','VALUE_REVISED','REVERIFIED','APPROVED','SCOPE_SPEC_CONFIRMED'
}
def emit(event_fn,logger,name,**fields):
    if name not in EVENTS: raise ValueError(f'unknown audit event: {name}')
    event_fn(logger,name,**fields)

"""Stable case25 execution boundary: typed evidence + analysis specification + deterministic engine."""
from .executor_case24 import execute_contract as _execute_case24
from .analysis_spec_case25 import check_analysis_spec

def execute_contract(contract,df,analysis_spec=None):
    """Fail closed before deterministic execution when analysis policy is incomplete.

    case25 SAFETY CHANGE — WHY: confirming evidence is not enough for inferential reproduction.
    The analysis specification is a separate gate and must not be bypassed by the executor.
    """
    if analysis_spec is not None:
        ok,missing,unsupported=check_analysis_spec(analysis_spec,contract.contract_type.value)
        if not ok:
            return {'state':'BLOCKED','reason':'분석 명세 미완성','missing':missing,'unsupported':unsupported,'result':None}
    return _execute_case24(contract,df)

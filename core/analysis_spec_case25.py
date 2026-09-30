"""Analysis-specification gate for Evidence Gate case25.

case25 SAFETY CHANGE
FAILURE: case24 could confirm a missing-data policy and then execute an inferential model even
when population/estimand/variance/multiplicity details were still unknown.
RISK: a numerically correct calculation under the wrong analysis specification can be
mislabelled as a reproduction failure.
WHY: reproduction requires the *reported analysis specification*, not merely the same test name.
CHANGE: inferential contracts receive an explicit specification object. Unknown material fields
are surfaced to the reviewer and execution is fail-closed until the reviewer confirms the
minimum supported specification.
REGRESSION: tests/test_case25.py covers blocked/unblocked paths.
"""
from dataclasses import dataclass, asdict, field

@dataclass
class AnalysisSpecification:
    population:str='unspecified'
    estimand:str='unspecified'
    missing_policy:str='unspecified'
    variance_estimator:str='unspecified'
    multiplicity_policy:str='unspecified'
    reference_levels:dict=field(default_factory=dict)
    interactions:list[str]=field(default_factory=list)
    transforms:dict=field(default_factory=dict)
    human_confirmed:bool=False
    def to_dict(self): return asdict(self)

SUPPORTED_MISSING={'complete_case'}

def build_analysis_spec(claim):
    return AnalysisSpecification(
        population=getattr(claim,'analysis_population','unspecified'),
        estimand=getattr(claim,'estimand','unspecified'),
        missing_policy=getattr(claim,'missing_policy','unspecified'),
        variance_estimator=getattr(claim,'variance_estimator','unspecified'),
        multiplicity_policy=getattr(claim,'multiplicity_policy','unspecified'),
        reference_levels=dict(getattr(claim,'reference_levels',{}) or {}),
        interactions=list(getattr(claim,'interaction_terms',[]) or []),
        transforms=dict(getattr(claim,'transform_spec',{}) or {}),
        human_confirmed=bool(getattr(claim,'analysis_spec_confirmed',False)),
    )

def check_analysis_spec(spec, contract_type):
    """Return (executable, missing, unsupported).

    The prototype requires explicit human confirmation plus a supported missing-data policy.
    Population/estimand/multiplicity remain auditable fields; 'unspecified' is allowed only after
    the reviewer explicitly confirms that the source does not report them. This prevents the UI
    from silently inventing details while keeping the prototype usable on incomplete papers.
    """
    if contract_type in {'DESCRIPTIVE','SCOPE'}: return True,[],[]
    missing=[]; unsupported=[]
    if not spec.human_confirmed: missing.append('analysis specification confirmation')
    if spec.missing_policy=='unspecified': missing.append('missing-data policy')
    elif spec.missing_policy not in SUPPORTED_MISSING: unsupported.append('missing-data policy:'+spec.missing_policy)
    return not missing and not unsupported,missing,unsupported

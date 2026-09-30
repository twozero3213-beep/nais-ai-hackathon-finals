"""Typed verification contracts for Evidence Gate case21.

case21 ARCHITECTURE CHANGE — WHY:
Blind Test 02 proved that one generic ``column + filter + mean`` contract is unsafe.
Correlation was rendered like a mean, logistic regression was rendered like a mean, and a
broad scope claim fell back to ``mean(age)``.  Different scientific claims require different
inputs, so case21 makes the contract type explicit before any statistical execution.

Invariant: a contract may be *proposed* by heuristics/AI, but it is executable only when its
claim-type-specific evidence requirements are complete and a human has confirmed the mapping.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from enum import Enum
from core.decision_provenance import is_confirmed
from core.semantic import dataset_scope_mismatch

class ContractType(str, Enum):
    DESCRIPTIVE="DESCRIPTIVE"
    COMPARATIVE="COMPARATIVE"
    ASSOCIATION="ASSOCIATION"
    REGRESSION="REGRESSION"
    SCOPE="SCOPE"

@dataclass
class ContractCheck:
    executable: bool
    missing: list[str] = field(default_factory=list)
    reason: str = ""

@dataclass
class BaseContract:
    claim_id: str
    contract_type: ContractType
    source_page: int|None
    source_quote: str
    dataset_name: str
    dataset_hash: str
    filters: list[dict] = field(default_factory=list)
    human_confirmed: bool = False
    method: str = ""
    method_confirmed: bool = True
    missing_policy: str = "unspecified"
    missing_policy_confirmed: bool = True
    analysis_spec: dict = field(default_factory=dict)
    def to_dict(self):
        d=asdict(self); d["contract_type"]=self.contract_type.value; return d

@dataclass
class DescriptiveContract(BaseContract):
    variable: str = ""
    aggregation: str = "mean"
    tolerance: float = .15
    weight_column: str = ""
    success_value: str = "1"
    reference_value: float = 0.0
    alpha: float = .05

@dataclass
class ComparativeContract(BaseContract):
    outcome: str = ""
    group_column: str = ""
    group_a: str = ""
    group_b: str = ""
    alpha: float = .05

@dataclass
class AssociationContract(BaseContract):
    x: str = ""
    y: str = ""
    alpha: float = .05

@dataclass
class RegressionContract(BaseContract):
    outcome: str = ""
    predictors: list[str] = field(default_factory=list)
    alpha: float = .05
    # [수정: 0 이영] 2026-09-30 22:44 KST — C09: 모형 설명변수 목록과 검산 대상 항을 분리하여 첫 변수로 오인하지 않는다.
    target_predictor: str = ""

@dataclass
class ScopeContract(BaseContract):
    endpoint: str = ""
    endpoint_candidate: str = ""
    subgroup_dimensions: list[str] = field(default_factory=list)
    timepoints: list[str] = field(default_factory=list)
    required_coverage: str = "all combinations"


def route_contract_type(claim) -> ContractType:
    """Route before execution; scope takes precedence over every numeric fallback.

    case21 BUGFIX — WHY: C-05 in Blind Test 02 contained broad universal language but no
    executable endpoint. case20 still generated ``mean(age)``. Routing SCOPE first prevents any
    descriptive fallback from manufacturing an irrelevant number.
    """
    d=claim.decomposition or {}
    if d.get("overclaim_signal"): return ContractType.SCOPE
    kind=d.get("claim_kind","")
    method=claim.analysis_method or getattr(claim,"method_candidate","") or claim.aggregation
    if kind=="correlation" or method in {"pearson_r","spearman_r","paired_t","wilcoxon_signed"}: return ContractType.ASSOCIATION
    if kind=="regression" or method in {"linear_regression","logistic_regression"}: return ContractType.REGRESSION
    if method in {"independent_t","welch_t","mannwhitney_u","chi_square","fisher_exact"}: return ContractType.COMPARATIVE
    return ContractType.DESCRIPTIVE


def build_typed_contract(claim,dataset_name,dataset_hash):
    ct=route_contract_type(claim)
    evidence_record=getattr(claim,"evidence_provenance",{}) or {}
    method_record=getattr(claim,"method_provenance",{}) or {}
    # case29 PROVENANCE CHANGE — WHY: booleans and provenance records could disagree in case28.
    # When a provenance record exists it is the source of truth; legacy booleans remain only as a
    # backward-compatible fallback for older saved/test Claims.
    evidence_confirmed=is_confirmed(evidence_record) if evidence_record else bool(claim.semantic_confirmed)
    # [수정: 0 이영] 2026-09-30 22:44 KST — C01/C03: 선택 방법을 단일화하고 1표본 t에도 추론 확인 정책을 적용한다.
    method=claim.analysis_method or getattr(claim,"method_candidate","") or claim.aggregation
    inferential=ct in {ContractType.COMPARATIVE,ContractType.ASSOCIATION,ContractType.REGRESSION} or method=="one_sample_t"
    method_confirmed=(True if not inferential else (is_confirmed(method_record) if method_record else bool(getattr(claim,"method_confirmed",False) or (getattr(claim,"analysis_method","") and not getattr(claim,"method_candidate","")))))
    common=dict(claim_id=claim.claim_id,contract_type=ct,source_page=claim.source_page,
                source_quote=claim.source_quote or claim.text,dataset_name=dataset_name,
                dataset_hash=dataset_hash,filters=list(claim.filters),
                human_confirmed=evidence_confirmed,method=method,
                method_confirmed=method_confirmed,
                missing_policy=getattr(claim,"missing_policy","unspecified"),
                missing_policy_confirmed=getattr(claim,"missing_policy_confirmed",False) if inferential else True,
                analysis_spec={
                    'population':getattr(claim,'analysis_population','unspecified'),
                    'estimand':getattr(claim,'estimand','unspecified'),
                    'missing_policy':getattr(claim,'missing_policy','unspecified'),
                    'variance_estimator':getattr(claim,'variance_estimator','unspecified'),
                    'multiplicity_policy':getattr(claim,'multiplicity_policy','unspecified'),
                    'multiplicity_count':getattr(claim,'multiplicity_count',0),
                    # [작성/수정: 전문가5·6] 2026-09-26 case62
                    # 무엇을: 감사 계약에도 전체 가족 입력 보존 / 왜: 실행 명세와 기록 일치.
                    'multiplicity_p_values':list(getattr(claim,'multiplicity_p_values',[]) or []),
                    'multiplicity_target_index':getattr(claim,'multiplicity_target_index',None),
                    'multiplicity_family_definition':getattr(claim,'multiplicity_family_definition',''),
                    'reference_levels':dict(getattr(claim,'reference_levels',{}) or {}),
                    'interactions':list(getattr(claim,'interaction_terms',[]) or []),
                    'transforms':dict(getattr(claim,'transform_spec',{}) or {}),
                    'human_confirmed':bool(getattr(claim,'analysis_spec_confirmed',False)),
                })
    if ct==ContractType.SCOPE:
        # A scope claim needs an endpoint and explicit coverage dimensions; never invent them.
        # case22 SAFETY CHANGE — WHY:
        # case21 displayed the heuristic metric hint as if it were a confirmed endpoint. A candidate
        # must not be promoted to evidence before human confirmation. Keep it separately as
        # ``endpoint_candidate`` and leave the executable endpoint empty.
        # case24 SAFETY CHANGE — WHY: Blind Test 03 broad language can mention "effect" without
        # naming an endpoint. case22 could surface a weak heuristic alias as a plausible endpoint.
        # Only expose a candidate when the evidence matcher produced a materially supported score.
        top=(claim.evidence_candidates or [{}])[0]
        candidate=claim.column if top.get("score",0)>=0.20 else ""
        # case26 RESOLUTION CHANGE
        # FAILURE: case25 could block a scope claim correctly but gave the reviewer no durable way to
        # complete the missing endpoint/subgroup/timepoint contract.
        # RISK: a fail-closed system that cannot be resolved becomes a dead end rather than a review workflow.
        # WHY: human-confirmed scope fields must be persisted separately from heuristic candidates.
        # CHANGE: confirmed scope fields live on Claim and are promoted only after explicit confirmation.
        confirmed=bool(getattr(claim,'scope_confirmed',False))
        common['human_confirmed']=confirmed
        return ScopeContract(**common,endpoint=getattr(claim,'scope_endpoint','') if confirmed else "",endpoint_candidate=candidate,
                             subgroup_dimensions=list(getattr(claim,'scope_subgroup_dimensions',[]) or []) if confirmed else [],
                             timepoints=list(getattr(claim,'scope_timepoints',[]) or []) if confirmed else [])
    if ct==ContractType.ASSOCIATION:
        return AssociationContract(**common,x=claim.x_column or claim.decomposition.get("x_hint","") or "",y=claim.column or "",alpha=claim.alpha)
    if ct==ContractType.REGRESSION:
        # [수정: 0 이영] 2026-09-30 22:44 KST — C09: 선택된 x_column을 검산 대상으로 보존하고 다중 항의 자동 첫 선택을 막는다.
        predictors=list(claim.decomposition.get('predictor_hints',[]) or ([claim.x_column] if claim.x_column else []))
        target=claim.x_column or claim.decomposition.get('x_hint','') or (predictors[0] if len(predictors)==1 else '')
        return RegressionContract(**common,outcome=claim.column or "",predictors=predictors,alpha=claim.alpha,target_predictor=target)
    if ct==ContractType.COMPARATIVE:
        return ComparativeContract(**common,outcome=claim.column or "",group_column=claim.group_column or "",group_a=claim.group_a or "",group_b=claim.group_b or "",alpha=claim.alpha)
    # [수정: 전문가5] 2026-09-25 case40
    # 종류: 오류수정
    # 재현 방법: Claim 가중치 열·성공값을 지정해도 typed contract에서 사라졌다.
    # 변경 전: 실행기가 기본값으로 계산해 원래 명세와 다른 수치가 나올 수 있었다.
    # 변경 후: 두 값을 계약에 명시하고 누락 가중치 열은 차단한다.
    # 왜: 원문→명세→실행의 수치 의미를 일치시킨다.
    # 영향: 기술통계 계약에 두 필드가 추가된다.
    return DescriptiveContract(**common,variable=claim.column or "",aggregation=method,tolerance=claim.tolerance,weight_column=claim.weight_column,success_value=claim.success_value,reference_value=float(getattr(claim,"mu0",0.0)),alpha=claim.alpha)


# [수정: 전문가5/6] 2026-09-26 case64
# 원인: Scope 실열/빈 자료 확인 누락 / 무엇·왜: 차원·시간열·관측을 실행 전 확인.
# 입력·출력: 누락 구조 -> 실행 불가 / 검증: test_scope_missing_structure_blocks.
def check_evidence_sufficiency(contract,df) -> ContractCheck:
    """Fail closed: incomplete evidence means BLOCKED, never a guessed calculation."""
    missing=[]
    cols=set(df.columns)
    # [수정: 0 이영] 2026-09-30 22:44 KST — C03: 계약 유형이 기술통계여도 1표본 t는 추론 확인을 생략하지 않는다.
    inferential=isinstance(contract,(ComparativeContract,AssociationContract,RegressionContract)) or (isinstance(contract,DescriptiveContract) and contract.method=="one_sample_t")
    # [수정: 재현성/Fail-closed] 2026-09-28 case72
    # 통계 명세 자체가 유효하지 않으면 계산하지 않는다. NaN/Inf/범위 밖 alpha·tolerance를
    # 결과 충돌이나 유의성으로 해석하면 같은 입력을 다른 실행환경에서 재현할 수 없다.
    import math
    if isinstance(contract,DescriptiveContract):
        # [수정: 0 이영] 2026-09-30 22:44 KST — C01: 수동 계약의 method/aggregation 모순도 계산 전에 차단한다.
        if contract.method and contract.method!=contract.aggregation: missing.append("consistent descriptive method")
        try: tol=float(contract.tolerance)
        except (TypeError,ValueError,OverflowError): tol=math.nan
        if not math.isfinite(tol) or tol < 0: missing.append("valid tolerance")
        if contract.method=="one_sample_t":
            try: alpha=float(contract.alpha)
            except (TypeError,ValueError,OverflowError): alpha=math.nan
            if not math.isfinite(alpha) or not (0 < alpha < 1): missing.append("valid alpha (0<alpha<1)")
    elif isinstance(contract,(ComparativeContract,AssociationContract,RegressionContract)):
        try: alpha=float(contract.alpha)
        except (TypeError,ValueError,OverflowError): alpha=math.nan
        if not math.isfinite(alpha) or not (0 < alpha < 1): missing.append("valid alpha (0<alpha<1)")
    if not contract.human_confirmed: missing.append("human semantic confirmation")
    for f in contract.filters:
        if f.get("column") not in cols: missing.append(f"filter column:{f.get('column')}")
    if isinstance(contract,DescriptiveContract):
        # [수정: 전문가4] 2026-09-25 case45
        # 종류: 오류수정 / 재현 방법: 전체 행·결측 셀 수에서 의미 없는 숫자형 열을 강제 / 변경 전: 모든 기술통계에 실열 필수 / 변경 후: 두 전체 데이터 방법에 명시적 __dataset__ 근거 허용 / 왜: 표본 분모 혼동 방지 / 영향: 다른 방법은 기존 열 검사 유지.
        if contract.aggregation in {"row_count","missing_cells"}:
            if contract.variable!="__dataset__":missing.append("whole-dataset evidence")
            # [수정: 전문가5] 2026-09-25 case46
            # 종류: 오류수정 / 재현 방법: 17변수 원문과 8열 CSV의 행 수 344 일치가 실행 허용 / 변경 전: 값만 비교 / 변경 후: 명시적 범위 차원 충돌을 계약에서 차단 / 왜: 다른 데이터 객체의 거짓 재현 방지 / 영향: 과거 344 성공은 REVIEW.
            mismatch=dataset_scope_mismatch(contract.source_quote,df)
            if mismatch:missing.append(mismatch)
        elif not contract.variable or contract.variable not in cols: missing.append("descriptive variable")
        if contract.aggregation=="weighted_mean" and (not contract.weight_column or contract.weight_column not in cols): missing.append("weight column")
    # case24 SAFETY CHANGE — WHY: case23 always executed inferential claims with complete-case deletion,
    # even when the paper's missing-data policy was unknown. That can reproduce the wrong estimand.
    # Inferential contracts now fail closed until a human explicitly confirms the analysis policy.
    if inferential and not contract.method_confirmed:
        missing.append("method confirmation")
    if inferential and not contract.missing_policy_confirmed:
        missing.append("missing-data policy confirmation")
    elif isinstance(contract,ComparativeContract):
        if not contract.outcome or contract.outcome not in cols: missing.append("outcome")
        if not contract.group_column or contract.group_column not in cols: missing.append("group column")
        if not contract.group_a: missing.append("group A")
        if not contract.group_b: missing.append("group B")
        if contract.group_column in cols and contract.group_a and contract.group_b:
            from .normalization import equivalent, filter_mask
            if equivalent(contract.group_a,contract.group_b): missing.append("distinct comparison groups")
            else:
                if not bool(filter_mask(df[contract.group_column],contract.group_a).any()): missing.append("observed group A")
                if not bool(filter_mask(df[contract.group_column],contract.group_b).any()): missing.append("observed group B")
    elif isinstance(contract,AssociationContract):
        if not contract.x or contract.x not in cols: missing.append("X variable")
        if not contract.y or contract.y not in cols: missing.append("Y variable")
    elif isinstance(contract,RegressionContract):
        if not contract.outcome or contract.outcome not in cols: missing.append("outcome")
        if not contract.predictors: missing.append("predictor")
        # [수정: 0 이영] 2026-09-30 22:44 KST — C09: 다중회귀는 명시된 대상 항만 검산하며 목록 밖 대상은 차단한다.
        target=contract.target_predictor or (contract.predictors[0] if len(contract.predictors)==1 else "")
        if not target or target not in contract.predictors: missing.append("regression target predictor")
        if contract.predictors:
            for p in contract.predictors:
                if p not in cols: missing.append(f"predictor:{p}")
    elif isinstance(contract,ScopeContract):
        # case21 policy: universal claims need explicit endpoint + dimensions + coverage plan.
        if not contract.endpoint or contract.endpoint not in cols: missing.append("scope endpoint")
        if not contract.subgroup_dimensions: missing.append("subgroup dimensions")
        if not contract.timepoints: missing.append("timepoints")
        for dimension in contract.subgroup_dimensions:
            if dimension not in cols: missing.append(f"subgroup column:{dimension}")
        if not any(col in cols for col in ("week","timepoint","visit","month")): missing.append("timepoint column")
        if df.empty: missing.append("scope observations")
    return ContractCheck(not missing,missing,"검증 계약 완성" if not missing else "필수 근거 부족: "+", ".join(missing))


def contract_summary(contract) -> str:
    if isinstance(contract,DescriptiveContract): return f"{contract.variable} · {contract.aggregation}"
    if isinstance(contract,ComparativeContract): return f"{contract.outcome} · {contract.group_column}: {contract.group_a} vs {contract.group_b} · {contract.method}"
    if isinstance(contract,AssociationContract): return f"X={contract.x} · Y={contract.y} · {contract.method}"
    if isinstance(contract,RegressionContract): return f"Y={contract.outcome} · X={', '.join(contract.predictors) or '미연결'} · {contract.method}"
    return f"endpoint 후보={contract.endpoint_candidate or contract.endpoint or '미연결'} · coverage={contract.required_coverage}"

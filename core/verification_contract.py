"""Compatibility facade for case21 typed verification contracts.

case21 WHY: team modules from case20 expect the legacy dataset/estimand shape. Keep those keys while
adding ``typed_contract`` so old consumers remain reusable and new consumers get the safer schema.
"""
from .typed_contracts import build_typed_contract

def build_contract(claim,dataset_name,dataset_hash):
    typed=build_typed_contract(claim,dataset_name,dataset_hash)
    return {
        'claim_id':claim.claim_id,
        'source':{'page':claim.source_page,'quote':claim.source_quote or claim.text},
        'estimand':{'population':claim.decomposition.get('population') or None,'variable':claim.column or None,'timepoint':claim.decomposition.get('timepoint') or None,'statistic':claim.analysis_method or claim.aggregation,'unit':claim.decomposition.get('unit') or None},
        'dataset':{'name':dataset_name,'sha256':dataset_hash},
        'filters':list(claim.filters),
        'method':{'id':claim.analysis_method or claim.aggregation},
        'parameters':{'tolerance':claim.tolerance,'alpha':claim.alpha},
        'human_semantic_confirmation':bool(claim.semantic_confirmed),
        'original_value':claim.original_value,'current_value':claim.current_value,
        'reported_inference':{'p_value':claim.reported_p_value,'p_operator':claim.reported_p_operator,'effect':claim.reported_effect,'effect_kind':claim.effect_kind,'ci95':claim.reported_ci95},
        'typed_contract':typed.to_dict(),
    }

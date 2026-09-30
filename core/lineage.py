"""Claim-level executable lineage for case19."""
from __future__ import annotations

def build_lineage(claim, dataset_name, dataset_hash, snapshot, gate_results, engine_version):
    return {
        "claim_id": claim.claim_id,
        "source": {"page":claim.source_page,"quote":claim.source_quote or claim.text},
        "claim": {"original_value":claim.original_value,"current_value":claim.current_value,"type":claim.claim_type,"reported_p_value":getattr(claim,"reported_p_value",None),"reported_effect":getattr(claim,"reported_effect",None),"effect_kind":getattr(claim,"effect_kind","")},
        "evidence": {"dataset":dataset_name,"dataset_hash":dataset_hash,"column":claim.column,"filters":claim.filters,"rows_used":snapshot.get("rows_used"),"expression":snapshot.get("expression")},
        "analysis": {"method":claim.analysis_method or claim.aggregation,"alpha":claim.alpha,"tolerance":claim.tolerance},
        "gates": [g.to_dict() if hasattr(g,"to_dict") else g for g in gate_results],
        "engine": engine_version,
        "revision_count": claim.revision_count,
        "status": claim.status.value,
    }

"""case20 blind-test benchmark helpers.

WHY: superiority over a general AI tool must be measured, not asserted. These metrics are
model-agnostic and compare extracted claims/mappings/results against a human answer key.
"""
from __future__ import annotations

def topk_hit(candidates,expected,k=3):
    return expected in [x.get('column') for x in candidates[:k]]

def filter_set(filters):
    return {(str(x.get('column')),str(x.get('value'))) for x in filters}

def score_case(pred,truth):
    checks={
        'column_top1': bool(pred.get('candidates')) and pred['candidates'][0].get('column')==truth.get('column'),
        'column_top3': topk_hit(pred.get('candidates',[]),truth.get('column'),3),
        'filters_exact': filter_set(pred.get('filters',[]))==filter_set(truth.get('filters',[])),
        'method': pred.get('method')==truth.get('method'),
    }
    checks['all']=all(checks.values());return checks

def summarize(results):
    if not results:return {}
    keys=['column_top1','column_top3','filters_exact','method','all']
    return {k:sum(bool(r.get(k)) for r in results)/len(results) for k in keys}|{'n':len(results)}

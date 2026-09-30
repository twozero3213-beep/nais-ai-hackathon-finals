"""Benchmark metrics for comparing proposal/verification workflows on labelled claim sets."""
def safe_div(a,b): return a/b if b else 0.0

def score_cases(cases):
    """Each case may contain booleans: claim_found, top1, top3, filter_exact, method_exact,
    should_block, blocked. Returns transparent aggregate metrics rather than an overall score.
    """
    n=len(cases)
    return {
      'n':n,
      'claim_recall':safe_div(sum(bool(x.get('claim_found')) for x in cases),n),
      'evidence_top1_accuracy':safe_div(sum(bool(x.get('top1')) for x in cases),n),
      'evidence_top3_recall':safe_div(sum(bool(x.get('top3')) for x in cases),n),
      'filter_exact_accuracy':safe_div(sum(bool(x.get('filter_exact')) for x in cases),n),
      'method_exact_accuracy':safe_div(sum(bool(x.get('method_exact')) for x in cases),n),
      'blocked_when_uncertain_accuracy':safe_div(sum((not x.get('should_block')) or bool(x.get('blocked')) for x in cases),n),
    }

"""case27 presentation safety helpers.

case27 BUGFIX — FAILURE: floating-point residue such as 1.776e-15 was shown to reviewers.
RISK: machine precision noise looks like a scientific discrepancy.
WHY: verification uses raw values; presentation uses an independent display epsilon.
CHANGE: normalize display-only near-zero values without changing verification tolerances or audit data.
REGRESSION: tests/test_case27.py.
"""
DISPLAY_EPSILON=1e-12

def display_zero(value:float|None, epsilon:float=DISPLAY_EPSILON):
    if value is None:return None
    return 0.0 if abs(float(value)) < epsilon else float(value)

def fmt_number(value, digits=4):
    if value is None:return "—"
    v=display_zero(value)
    return f"{v:.{digits}g}"

def provenance_label(source:str, confirmed:bool=False):
    if confirmed:return "사람 확인 완료"
    return {"pdf_reported":"논문에서 직접 확인","system_candidate":"시스템 후보","heuristic":"시스템 후보"}.get(source or "","출처 미확정")

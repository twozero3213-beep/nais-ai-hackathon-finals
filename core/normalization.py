# [작성: 전문가4] 2026-09-23 case36
# 무엇을: 필터·결측값 정규화의 canonical API를 제공한다.
# 왜: case24 버전명 모듈 import를 제거해 재사용성과 유지보수성을 높인다.
# 입력·출력: 기존 case35 호환 API와 동일.
# 검증: tests/test_case36.py 및 전체 회귀 테스트.
"""Deterministic data normalization used by case24 verification contracts.

case24 SAFETY CHANGE — WHY:
Blind Test 03 intentionally mixes numeric encodings (12 vs 12.0), case, whitespace,
and common binary/category labels. case22 compared filters with raw string equality, which can
silently drop valid rows. Normalization is centralized here so every executor uses the same
rules and future maintainers have one place to audit/change them.
"""
from __future__ import annotations
import math, re
import numpy as np
import pandas as pd

MISSING_TOKENS={"","na","n/a","nan","none","null","missing",".","-"}
CATEGORY_ALIASES={
    "female":{"female","f","woman","women","여성"},
    "male":{"male","m","man","men","남성"},
    "treatment":{"treatment","treated","tx","intervention","처리군"},
    "control":{"control","ctrl","comparison","대조군"},
    "yes":{"yes","y","true","1"},
    "no":{"no","n","false","0"},
}

def _text(v):
    return re.sub(r"\s+"," ",str(v).strip()).casefold()

def canonical_category(v):
    s=_text(v)
    if s in MISSING_TOKENS:return None
    for canonical,aliases in CATEGORY_ALIASES.items():
        if s in aliases:return canonical
    return s

def numeric_value(v):
    if v is None:return None
    s=_text(v).replace(",","").replace("%","")
    if s in MISSING_TOKENS:return None
    try:
        x=float(s)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None

def equivalent(a,b):
    """Compare filter values safely without guessing domain-specific recodes."""
    na,nb=numeric_value(a),numeric_value(b)
    if na is not None and nb is not None:return bool(np.isclose(na,nb,rtol=0,atol=1e-12))
    return canonical_category(a)==canonical_category(b)

def filter_mask(series:pd.Series,value):
    return series.map(lambda x: equivalent(x,value)).fillna(False)

def normalize_missing(df:pd.DataFrame)->pd.DataFrame:
    out=df.copy()
    for col in out.columns:
        if out[col].dtype==object:
            out[col]=out[col].map(lambda x: np.nan if canonical_category(x) is None else x)
    return out

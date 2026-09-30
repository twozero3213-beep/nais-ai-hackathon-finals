"""Dataset provenance helpers.

case17 CHANGE: provenance is a first-class evidence artifact: dataset fingerprint,
row counts before/after filters, selected variable and executable aggregation.
"""
from __future__ import annotations
import hashlib
import pandas as pd
from .normalization import filter_mask


def dataframe_hash(df: pd.DataFrame) -> str:
    payload = pd.util.hash_pandas_object(df, index=True).values.tobytes()
    schema = "|".join(f"{c}:{df[c].dtype}" for c in df.columns).encode("utf-8")
    return hashlib.sha256(schema + payload).hexdigest()


# [수정: 재현성] 2026-09-28 case72
# 실제 계산과 감사 snapshot이 동일한 정규화 필터를 사용해야 rows_used가 재현된다.
def evidence_snapshot(claim, df: pd.DataFrame, dataset_name: str, dataset_hash: str) -> dict:
    filtered = df
    for item in claim.filters:
        col, value = item.get("column"), item.get("value")
        if col in filtered.columns:
            filtered = filtered[filter_mask(filtered[col], value)]
    filters = " AND ".join(f"{x['column']}={x['value']}" for x in claim.filters) or "없음"
    expression = f"{claim.aggregation}({claim.column})" if claim.column else "미연결"
    return {
        "dataset": dataset_name or "연결된 CSV",
        "fingerprint": dataset_hash,
        "rows_total": int(len(df)),
        "rows_used": int(len(filtered)),
        "filters": filters,
        "column": claim.column or "미연결",
        "aggregation": claim.aggregation,
        "expression": expression,
    }

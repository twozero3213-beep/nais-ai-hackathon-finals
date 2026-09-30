"""허용된 결정론적 계산: CSV 해석·행 선택·행 수·평균·OLS.

형식 오류 값은 조용히 버리지 않는다. 문제 행 번호를 담아 GateError로 멈춘다.
"""

from __future__ import annotations

import csv
import io
import math
import re

NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


class GateError(ValueError):
    """계산을 멈춰야 하는 입력 문제. code는 판정 기록에 그대로 남는다."""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def read_csv(data):
    """UTF-8 CSV 바이트 → (헤더, 행 사전 목록). 행은 1부터 센 자료 행 번호를 함께 갖는다."""
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        header = next(reader, [])
        if not header or any(not h for h in header) or len(set(header)) != len(header):
            raise GateError("CSV_HEADER", "CSV 헤더가 없거나 비었거나 중복됨")
        rows = []
        for cells in reader:
            if not cells:
                continue
            if len(cells) != len(header):
                raise GateError("CSV_SHAPE", "열 수가 헤더와 다른 행이 있음", {"data_row": len(rows) + 1})
            rows.append(dict(zip(header, cells)))
    except (UnicodeError, csv.Error) as exc:
        raise GateError("CSV_PARSE", f"UTF-8 CSV 해석 실패: {exc}") from exc
    return header, rows


def parse_number(cell):
    """엄격한 10진 숫자만 받는다. '1,000'·' 12'·'nan'·'inf'는 숫자가 아니다."""
    if not NUMBER.fullmatch(cell):
        return None
    value = float(cell)
    return value if math.isfinite(value) else None


def select_rows(header, rows, filters):
    """filters(eq)를 모두 만족하는 (자료 행 번호, 행)."""
    absent = sorted({f["column"] for f in filters} - set(header))
    if absent:
        raise GateError("COLUMN_NOT_FOUND", "필터 열이 자료에 없음", {"columns": absent})
    selected, bad = [], []
    for number, row in enumerate(rows, start=1):
        keep = True
        for f in filters:
            cell = row[f["column"]]
            if isinstance(f["value"], str):
                keep = keep and cell == f["value"]
            else:
                parsed = parse_number(cell)
                if parsed is None:
                    bad.append({"data_row": number, "column": f["column"], "value": cell})
                    keep = False
                else:
                    keep = keep and parsed == f["value"]
        if keep:
            selected.append((number, row))
    if bad:
        raise GateError("BAD_VALUE", "숫자 필터 열에 숫자가 아닌 값이 있음", {"rows": bad[:20], "count": len(bad)})
    return selected


def numeric_table(header, selected, columns, missing_tokens, missing_policy):
    """선택 행에서 columns의 숫자 표를 만든다. 결측·형식 오류 처리 내역을 함께 돌려준다."""
    absent = sorted(set(columns) - set(header))
    if absent:
        raise GateError("COLUMN_NOT_FOUND", "분석 열이 자료에 없음", {"columns": absent})
    tokens = set(missing_tokens)
    table, missing_rows, bad = [], [], []
    for number, row in selected:
        values, has_missing = [], False
        for column in columns:
            cell = row[column]
            if cell in tokens:
                has_missing = True
                continue
            parsed = parse_number(cell)
            if parsed is None:
                bad.append({"data_row": number, "column": column, "value": cell})
            values.append(parsed)
        if has_missing:
            missing_rows.append(number)
        elif len(values) == len(columns) and None not in values:
            table.append(values)
    if bad:
        raise GateError("BAD_VALUE", "숫자 열에 결측 표기도 숫자도 아닌 값이 있음", {"rows": bad[:20], "count": len(bad)})
    if missing_rows and missing_policy == "error":
        raise GateError("MISSING_VALUES", "결측 정책 error인데 결측이 있음",
                        {"data_rows": missing_rows[:20], "count": len(missing_rows)})
    return table, {"rows_selected": len(selected), "rows_used": len(table),
                   "rows_dropped_missing": len(missing_rows), "dropped_data_rows": missing_rows[:20]}


def _mean(values):
    # [수정: 0 이영 · Claude] 2026-09-30 23:51 KST — 유한 값의 합이 float 범위를 넘으면 fsum이 OverflowError로 죽었다(1_이채우_경계검증 finite_mean_overflow).
    # 항마다 n으로 나눠 더하면 넘치지 않는다. 정상 범위에서는 기존과 같은 fsum 평균을 쓴다.
    n = len(values)
    try:
        return math.fsum(values) / n
    except OverflowError:
        try:
            return math.fsum(v / n for v in values)
        except OverflowError:
            raise GateError("NUMERIC_OVERFLOW", "평균 계산 중 수 범위를 넘음") from None


def mean(values):
    if not values:
        raise GateError("NO_OBSERVATIONS", "계산할 관측값이 없음")
    return _mean(values)


def _solve(matrix, vector):
    """부분 피벗 가우스-조던. 특이 행렬이면 GateError."""
    size = len(matrix)
    aug = [list(row) + [v] for row, v in zip(matrix, vector)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise GateError("SINGULAR_DESIGN", "설계행렬이 특이함(예측변수 공선성 등)")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        lead = aug[col][col]
        aug[col] = [v / lead for v in aug[col]]
        for r in range(size):
            if r != col and aug[r][col] != 0:
                factor = aug[r][col]
                aug[r] = [a - factor * b for a, b in zip(aug[r], aug[col])]
    return [row[-1] for row in aug]


def ols(table, predictors):
    """table 각 행 = [outcome, *predictors]. 절편 포함 최소제곱과 고전적 표준오차.

    [수정: 0 이영 · Claude] 2026-09-30 23:51 KST — 원자료 그대로 정규방정식을 풀면 예측변수에 큰 오프셋(예: 1e6)이 있을 때 계수가 틀리고(기울기 오차 5.7e-5)
    오프셋 1e8에서는 멀쩡한 자료를 '특이'로 멈췄다(1_이채우_경계검증 ols_offset_*). 예측변수·결과를 평균으로 중심화하고
    예측변수를 길이 1로 표준화한 뒤 풀어 절편을 되돌린다. 표준화한 상관행렬은 대각이 1이라 특이 판정이 자료 단위와 무관하다.
    """
    n, k = len(table), len(predictors)
    p = k + 1
    if n <= p:
        raise GateError("NO_OBSERVATIONS", f"관측 {n}개로 계수 {p}개를 추정할 수 없음")
    y = [row[0] for row in table]
    ybar = _mean(y)
    yc = [v - ybar for v in y]
    xbar, z, norm = [], [], []
    for j in range(k):
        column = [row[j + 1] for row in table]
        center = _mean(column)
        centered = [v - center for v in column]
        length = math.sqrt(math.fsum(v * v for v in centered))
        if length == 0.0 or not math.isfinite(length):
            raise GateError("SINGULAR_DESIGN", "설계행렬이 특이함(예측변수 공선성 등)")
        xbar.append(center)
        z.append([v / length for v in centered])
        norm.append(length)
    corr = [[math.fsum(a * b for a, b in zip(z[i], z[j])) for j in range(k)] for i in range(k)]
    g = _solve(corr, [math.fsum(a * b for a, b in zip(z[i], yc)) for i in range(k)])
    slopes = [g[j] / norm[j] for j in range(k)]
    intercept = ybar - math.fsum(s * m for s, m in zip(slopes, xbar))
    residuals = [yc[i] - math.fsum(g[j] * z[j][i] for j in range(k)) for i in range(n)]
    df = n - p
    sigma2 = math.fsum(e * e for e in residuals) / df
    inverse_cols = [_solve(corr, [1.0 if a == b else 0.0 for a in range(k)]) for b in range(k)]
    quad = math.fsum((xbar[i] / norm[i]) * inverse_cols[j][i] * (xbar[j] / norm[j]) for i in range(k) for j in range(k))
    estimates = [(intercept, sigma2 * (1.0 / n + quad))]
    estimates += [(slopes[j], sigma2 * inverse_cols[j][j] / (norm[j] * norm[j])) for j in range(k)]
    terms = {}
    for name, (b, variance) in zip(["(Intercept)", *predictors], estimates):
        se = math.sqrt(max(variance, 0.0))
        terms[name] = {"b": b, "se": se, "t": b / se if se > 0 else None}
    return {"terms": terms, "df": df, "n": n}

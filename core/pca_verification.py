"""Explicit, fail-closed PCA arithmetic for a confirmed Claim and CSV dataset.

Arithmetic agreement never proves source-scope binding or whole-paper reproduction.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math

import numpy as np


# [작성: 전문가5] 2026-09-25 case60
# 무엇을: 명시된 행렬의 PC1 설명분산을 계산 / 왜: 논문별 PCA 산술의 공통 경로 확보 / 입력·출력: 유한 숫자 행렬·표준화 방법 -> 백분율·고유값 / 검증: tests/test_case60_pca.py의 손계산 50%, tests/test_case59_monarch.py.
def pca_variance_matrix(matrix, scaling):
    if scaling not in {'correlation', 'covariance'}:
        raise ValueError('PCA 표준화 방법 미지원')
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or values.shape[0] < 3 or values.shape[1] < 2:
        raise ValueError('PCA는 3행 이상·2열 이상의 행렬이 필요합니다.')
    if not np.isfinite(values).all():
        raise ValueError('PCA 입력에 결측·비유한 수치가 있습니다.')
    if scaling == 'correlation' and np.any(np.ptp(values, axis=0) == 0):
        raise ValueError('상관행렬 PCA는 모든 열의 분산이 양수여야 합니다.')
    matrix_of_variation = (np.corrcoef(values, rowvar=False) if scaling == 'correlation'
                           else np.cov(values, rowvar=False))
    eigenvalues = np.linalg.eigvalsh(matrix_of_variation)[::-1]
    total = float(eigenvalues.sum())
    if not np.isfinite(eigenvalues).all() or total <= 0:
        raise ValueError('PCA 고유값 합계가 유효하지 않습니다.')
    return float(100 * eigenvalues[0] / total), eigenvalues


# [작성: 전문가5] 2026-09-25 case60
# 무엇을: CSV와 확인된 PCA 계약으로 제한된 산술 대조 / 왜: 원문·모집단·방법 누락 시 거짓 재현 차단 / 입력·출력: 원본 CSV bytes·명시 계약 -> BLOCK 또는 산술 대조 / 검증: tests/test_case60_pca.py.
# [수정: 전문가4] 2026-09-25 case60
# 종류: 오류수정 | 재현 방법: reported_percent에 10**400 입력 / 변경 전: OverflowError / 변경 후: BLOCK / 왜: 비정상 계약도 조용한 실행 없이 차단 / 영향: 정상 수치 결과 불변.
def verify_pca_csv(csv_bytes, contract):
    blocked = lambda reason: {'action': 'BLOCK', 'reason': reason, 'source_scope_verified': False,
                              'full_paper_reproduced': False}
    if not isinstance(csv_bytes, bytes) or not isinstance(contract, dict):
        return blocked('원자료 bytes와 분석 계약이 필요합니다.')
    required = {'claim_id', 'source_quote', 'source_location', 'dataset_sha256', 'columns',
                'filters', 'scaling', 'missing_policy', 'reported_percent',
                'rounding_decimals', 'human_confirmed', 'method_confirmed',
                'population_confirmed'}
    if required - contract.keys():
        return blocked('PCA 필수 계약 누락: ' + ', '.join(sorted(required - contract.keys())))
    if not all(contract.get(key) is True for key in ('human_confirmed', 'method_confirmed', 'population_confirmed')):
        return blocked('원문·방법·모집단 확인이 필요합니다.')
    if not all(isinstance(contract.get(key), str) and contract[key].strip()
               for key in ('claim_id', 'source_quote', 'source_location')):
        return blocked('Claim과 원문 위치가 필요합니다.')
    digest = hashlib.sha256(csv_bytes).hexdigest()
    if contract['dataset_sha256'] != digest:
        return blocked('원자료 SHA-256 불일치')
    columns = contract['columns']
    if not isinstance(columns, list) or len(columns) < 2 or not all(isinstance(c, str) and c for c in columns) or len(set(columns)) != len(columns):
        return blocked('PCA 열은 중복 없는 2개 이상의 이름이어야 합니다.')
    if not isinstance(contract['scaling'], str) or contract['scaling'] not in {'correlation', 'covariance'}:
        return blocked('PCA 표준화 방법 미지원')
    if not isinstance(contract['missing_policy'], str) or contract['missing_policy'] not in {'reject', 'complete_case'}:
        return blocked('결측 처리 방법 미지원')
    filters = contract['filters']
    if not isinstance(filters, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in filters.items()):
        return blocked('필터는 열 이름과 문자열 값으로 명시해야 합니다.')
    decimals = contract['rounding_decimals']
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 10:
        return blocked('보고값 소수 자릿수 미지원')
    try:
        reported = float(contract['reported_percent'])
    except (TypeError, ValueError, OverflowError):
        return blocked('보고 백분율이 숫자가 아닙니다.')
    if not math.isfinite(reported) or not 0 <= reported <= 100:
        return blocked('보고 백분율 범위 오류')
    try:
        with io.StringIO(csv_bytes.decode('utf-8-sig'), newline='') as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames or []
            if len(set(header)) != len(header):
                return blocked('중복 CSV 열 이름')
            missing_columns = (set(columns) | set(filters)) - set(header)
            if missing_columns:
                return blocked('CSV 열 없음: ' + ', '.join(sorted(missing_columns)))
            rows = list(reader)
    except (UnicodeDecodeError, csv.Error):
        return blocked('UTF-8 CSV를 읽을 수 없습니다.')
    matrix, selected, dropped = [], 0, 0
    for row in rows:
        if None in row:
            return blocked('CSV 행의 열 개수가 헤더보다 많습니다.')
        if not all(row.get(key) == value for key, value in filters.items()):
            continue
        selected += 1
        cells = [row.get(name) for name in columns]
        if any(value in ('', None) for value in cells):
            if contract['missing_policy'] == 'complete_case':
                dropped += 1
                continue
            return blocked('선택된 행에 결측 PCA 값이 있습니다.')
        try:
            values = [float(value) for value in cells]
        except (TypeError, ValueError):
            return blocked('선택된 행에 숫자가 아닌 PCA 값이 있습니다.')
        if not all(math.isfinite(value) for value in values):
            return blocked('선택된 행에 비유한 PCA 값이 있습니다.')
        matrix.append(values)
    try:
        computed, eigenvalues = pca_variance_matrix(matrix, contract['scaling'])
    except (ValueError, np.linalg.LinAlgError) as error:
        return blocked(str(error))
    tolerance = 0.5 * 10 ** -decimals
    matched = abs(computed - reported) <= tolerance
    return {
        'claim_id': contract['claim_id'],
        'action': 'ARITHMETIC_MATCH' if matched else 'ARITHMETIC_MISMATCH',
        'computed_percent': computed, 'reported_percent': reported,
        'rounding_tolerance_percentage_points': tolerance,
        'rows_selected': selected, 'rows_used': len(matrix), 'rows_missing_dropped': dropped,
        'columns': columns, 'filters': filters, 'scaling': contract['scaling'],
        'dataset_sha256': digest, 'eigenvalues_descending': [float(x) for x in eigenvalues],
        'source_scope_verified': False, 'full_paper_reproduced': False,
    }

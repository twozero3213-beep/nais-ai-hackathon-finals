"""Recalculate the author-scoped monarch size-PCA stage; whole-paper scope stays BLOCKed.

Run: python tools/reproduce_monarch.py [--output PATH]
Exit 2 means whole-paper reproduction is not approved. The author R script is not run.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.pca_verification import pca_variance_matrix

MONARCH = Path(__file__).resolve().parents[1] / 'data/evaluation/paper_pairs/monarch'
SOURCE_HASHES = {
    'adult_morphology.csv': 'd85aec46430c571546504a2c6b8982fd187b8d60f2d0e517f890b46bc349a39b',
    'wings_04.25.20.csv': '4208ca6ee43815c0da845fe59200b3ec1005cff0a778217b7eed4bf1c47a88f2',
    'global_monarch_wing_morphology.R': '8a25e90d0f8054c26f3fd1ac8914d46787f02816493a44f38903f85c719df308',
}
MISSING = {'', 'NA'}


# [작성: 전문가7] 2026-09-25 case59
# 무엇을: 저자 R 446-460행 공통환경 성체 필터·평균 재구성 / 왜: 다른 모집단과 혼동 방지 / 입력·출력: adult CSV 행 -> PCA 행렬·분모·CSV 행번호 / 검증: tests/test_case59_monarch.py.
def size_matrix(rows):
    selected = [(number, row) for number, row in enumerate(rows, start=2)
                if row['RArea'] not in MISSING]
    matrix, indices = [], []
    for number, row in selected:
        values = []
        for measure in ('Area', 'Length', 'Width'):
            sides = [float(row[side + measure]) for side in ('L', 'R')
                     if row[side + measure] not in MISSING]
            values.append(sum(sides) / len(sides) if sides else float('nan'))
        if not np.isfinite(values).all():
            raise ValueError('PCA inputs have missing/nonfinite values after the author filter')
        matrix.append(values)
        indices.append(str(number))
    audit = {'raw_rows': len(rows), 'right_area_observed_rows': len(selected),
             'right_area_missing_rows': len(rows) - len(selected),
             'complete_size_rows': len(matrix)}
    return np.asarray(matrix, dtype=float), audit, indices


# [작성: 전문가7] 2026-09-25 case59
# 무엇을: 원파일 지문·모집단·cor=TRUE PCA 감사 / 왜: 부분 일치와 전체 재현 분리 / 입력·출력: 저자 원파일 -> 결정적 감사 JSON / 검증: 독립 pandas+SVD 교차검산.
def audit_monarch(directory=MONARCH):
    directory = Path(directory)
    result = {
        'claim_id': 'MONARCH-SIZE-PC1-VARIANCE', 'decision': 'BLOCK',
        'reproduced': False, 'r_script_executed': False, 'integrity_ok': True,
        'paper_population_explicit': False,
        'population_binding': 'Author R lines 440-461 identify common-garden adults and 96.4%; the paper Data Analysis paragraph does not explicitly name the PCA population.',
        'paper_doi': '10.1073/pnas.2001283117',
        'source_url': 'https://www.sanramlab.org/pubs/Freedman_et_al_2020.pdf',
        'source_location': 'Materials and Methods, Data Analysis; PDF page 5 of 7, first paragraph',
        'source_hashes': {}, 'sample_audit': None, 'size_pc1': None, 'blockers': [],
    }
    for name, expected in SOURCE_HASHES.items():
        path = directory / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        result['source_hashes'][name] = actual
        if actual != expected:
            result['integrity_ok'] = False
            result['blockers'].append({'code': 'SOURCE_MISSING' if actual is None else 'SOURCE_HASH_MISMATCH',
                                       'required': f'Restore pinned {name}: {expected}'})
    if not result['integrity_ok']:
        return result
    with (directory / 'adult_morphology.csv').open(encoding='utf-8-sig', newline='') as file:
        matrix, audit, indices = size_matrix(list(csv.DictReader(file)))
    # The common-garden stage explicitly requests cor=TRUE, unlike wild-caught PCA.
    # [수정: 전문가5] 2026-09-25 case60
    # 종류: 효율화 | 재현 방법: 왕나비 전용 PCA를 새 임의 CSV PCA와 비교 / 변경 전: 전용 도구 안에서 고유값 계산 중복 / 변경 후: 검증된 공통 수치 함수 재사용 / 왜: 같은 분석조건을 논문별로 다시 짜지 않음 / 영향: 결과·분모·전체 BLOCK은 불변.
    computed, eigenvalues = pca_variance_matrix(matrix, 'correlation')
    match = abs(computed - 96.4) < 0.05
    result['sample_audit'] = audit
    result['size_pc1'] = {
        'status': 'MATCH_SCOPED_PCA' if match else 'MISMATCH',
        'reported_percent': 96.4, 'computed_percent': round(computed, 10),
        'percentage_point_difference': round(computed - 96.4, 10),
        'published_rounding_tolerance_percentage_points': 0.05,
        'denominator_rows': len(matrix),
        'variables': ['mean_available(LArea,RArea)', 'mean_available(LLength,RLength)',
                      'mean_available(LWidth,RWidth)'],
        'population': 'Common-garden adults; adult_morphology.csv with observed RArea',
        'author_code_location': 'global_monarch_wing_morphology.R lines 440-461',
        'method': 'Correlation PCA (author princomp cor=TRUE), available-side means',
        'eigenvalues_descending': [round(float(value), 12) for value in eigenvalues],
        'population_csv_rows_sha256': hashlib.sha256('\n'.join(indices).encode('utf-8')).hexdigest(),
    }
    if not match:
        result['blockers'].append({'code': 'PUBLISHED_VALUE_MISMATCH',
            'required': 'Resolve the publication/data/script version and covariance-versus-correlation specification with the authors; do not tune filters to the printed value.'})
    result['blockers'].append({'code': 'PAPER_POPULATION_SCOPE_NOT_EXPLICIT',
        'required': 'Treat this as a numeric match scoped to the author common-garden code, not evidence that the museum/wild-caught population or all paper analyses were reproduced.'})
    result['blockers'].append({'code': 'AUTHOR_R_ENVIRONMENT_NOT_EXECUTED',
        'required': 'Execute the pinned author script in a documented R/package environment and retain outputs before claiming full paper reproduction. Python translated only the size-PCA stage.'})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=MONARCH)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit_monarch(args.data_dir)
    output = json.dumps(result, indent=2, ensure_ascii=True) + '\n'
    if args.output:
        args.output.write_text(output, encoding='utf-8')
    print(output, end='')
    raise SystemExit(2 if result['decision'] == 'BLOCK' else 0)

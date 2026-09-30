"""Audit published horse claims; never substitute counts for an unfitted GLMM.

Run: python tools/reproduce_horse.py
Exit 2 means the inferential claim remains BLOCKed. No R model is run here.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

HORSE = Path(__file__).resolve().parents[1] / 'data/evaluation/paper_pairs/horse'
SOURCE_HASHES = {
    'Dados_Laize_ISAE2021.csv': '33bf5378de32b8c54c412ed4ea929f45174bc1981031f194813daed92f1fcbde',
    'running_script_Carmo_et_al.Rmd': 'bef787092de1ca6764f48fd0fcc2ffb26c12952b334a82d74d54af421cecae60',
}


# [작성: 전문가7] 2026-09-25 case57
# 무엇을: 그룹별 관측 사건·결측 집계 / 왜: 결측을 0으로 오인하지 않기 위해 / 입력·출력: 원자료 행·열·그룹 -> 사건·관측·결측 수 / 검증: tests/test_case57_paper.py.
def group_counts(rows, column, groups):
    """Count observed binary events, retaining NA in a separate denominator."""
    result = {}
    for group in groups:
        values = [row[column] for row in rows if row['GRUPO'] == group]
        observed = [value for value in values if value not in {'NA', ''}]
        if any(value not in {'0', '1'} for value in observed):
            raise ValueError(f'{column} contains nonbinary observations')
        result[group] = {
            'rows': len(values), 'observed': len(observed),
            'events': sum(map(int, observed)), 'missing': len(values) - len(observed),
        }
    return result


# [작성: 전문가7] 2026-09-25 case57
# 무엇을: 원파일 해시·논문 합계·모델 모집단 감사 / 왜: 단순 집계를 미실행 OR 재현으로 승격하지 않기 위해 / 입력·출력: 저자 CSV·Rmd -> BLOCK 및 부분 근거 JSON / 검증: tests/test_case57_paper.py.
def audit_horse(directory=HORSE):
    directory = Path(directory)
    result = {
        'claim_id': 'HORSE-LOWERED-NECK-OR', 'decision': 'BLOCK',
        'reproduced': False, 'computed_or': None,
        'reported': {'or': 0.05, 'ci95_printed': [0.00, 0.56], 'p_printed': 0.05},
        'source_location': 'Carmo et al. 2023, section 3.2, printed page 9; Abstract, page 1',
        'specification': 'data/evaluation/paper_pairs/horse/claim_spec.json',
        'integrity_ok': True, 'source_hashes': {},
        'sample_audit': None, 'table3_elevated_neck': None,
        'blockers': [
            {'code': 'MODEL_NOT_EXECUTED', 'required': 'Execute lme4::glmer(NECK_ABAIXO ~ GRUPO + (1|NOME), family=binomial, data=data_wth); retain coefficient, standard error and Wald z p-value.'},
            {'code': 'ENVIRONMENT_NOT_PINNED', 'required': 'Record R and lme4/readr versions, factor contrast/reference, na.action, optimizer and nAGQ. Paper states R 4.0.4; local Rmd has no package lock/sessionInfo.'},
            {'code': 'MODEL_DIAGNOSTICS_MISSING', 'required': 'Retain convergence/singularity diagnostics and profile likelihood CI, then compare unrounded results to the printed two-decimal OR, CI and p. Installing R alone must not clear this gate.'},
        ],
    }
    for name, expected in SOURCE_HASHES.items():
        source = directory / name
        if not source.is_file():
            result['integrity_ok'] = False
            result['blockers'].append({'code': 'SOURCE_MISSING', 'required': name})
            continue
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        result['source_hashes'][name] = actual
        if actual != expected:
            result['integrity_ok'] = False
            result['blockers'].append({'code': 'SOURCE_HASH_MISMATCH', 'required': f'Restore original {name}; expected SHA-256 {expected}.'})
    if not result['integrity_ok']:
        return result

    with (directory / 'Dados_Laize_ISAE2021.csv').open(encoding='utf-8-sig', newline='') as source:
        raw = list(csv.DictReader(source))
    selected = [(number, row) for number, row in enumerate(raw, start=2)
                if row['EXP_DAY'] not in {'4', '5', '7', '8'} and row['GRUPO'] != 'Controle']
    # R's normal na.omit model frame drops missing response/predictors; no imputation.
    missing = [(number, row) for number, row in selected
               if any(row[key] in {'NA', ''} for key in ('NOME', 'GRUPO', 'NECK_ABAIXO'))]
    complete = [row for number, row in selected if (number, row) not in missing]
    result['sample_audit'] = {
        'raw_rows': len(raw), 'filtered_rows': len(selected),
        'model_rows': len(complete), 'horses': len({row['NOME'] for row in complete}),
        'groups': group_counts([row for _, row in selected], 'NECK_ABAIXO', ('Baseline', 'Experimental')),
        'excluded_missing': [{'csv_row': number, 'horse': row['NOME'], 'day': int(row['EXP_DAY']), 'group': row['GRUPO']} for number, row in missing],
    }
    counts = group_counts(raw, 'NECK_SUPERELEVADO', ('Experimental', 'Controle'))
    totals_match = counts['Experimental']['events'] == 1 and counts['Controle']['events'] == 4
    result['table3_elevated_neck'] = {
        'claim_id': 'HORSE-TABLE3-ELEVATED-NECK',
        'source_location': 'Carmo et al. 2023, Table 3, printed page 8, Elevated neck column',
        'status': 'MATCH_DESCRIPTIVE_ONLY' if totals_match else 'MISMATCH',
        'groups': counts,
        'limitation': 'Observed binary event totals only; missing records are excluded and disclosed, not treated as zero. Does not reproduce lowered-neck OR, CI, p or other table columns.',
        'event_csv_rows': {group: [number for number, row in enumerate(raw, start=2)
                                  if row['GRUPO'] == group and row['NECK_SUPERELEVADO'] == '1']
                           for group in ('Experimental', 'Controle')},
    }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=HORSE)
    args = parser.parse_args()
    print(json.dumps(audit_horse(args.data_dir), indent=2, ensure_ascii=True))
    raise SystemExit(2)

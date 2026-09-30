"""Declarative developer-only cohort arithmetic; never executes author code."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# [작성: 전문가4·8] 2026-09-26 case62
# 무엇을: 중복 JSON 필드 거부 / 왜: 마지막 값으로 명세가 숨겨 바뀌는 경로 차단 / 입력·출력: key-value pairs -> dict / 검증: test_case62_cohort.
def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate manifest key: {key}')
        result[key] = value
    return result


# [작성: 전문가4] 2026-09-26 case61
# 무엇·왜: 숫자 계약 검증 / 입력·출력: 숫자 -> 유한 float / 검증: malformed·NaN·Inf 차단.
def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('Expected numeric cell or constant')
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError('Malformed numeric cell or constant') from exc
    if not math.isfinite(number):
        raise ValueError('Nonfinite numeric cell or constant')
    return number


# [작성: 전문가4] 2026-09-26 case61
# 무엇·왜: 명시적 열 계약 / 입력·출력: 목록 -> 검증된 목록 / 검증: 빈값·중복·암묵 열 차단.
def _columns(value):
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v for v in value) or len(set(value)) != len(value):
        raise ValueError('Expected nonempty unique explicit columns')
    return value


# [작성: 전문가4] 2026-09-26 case61
# 무엇·왜: 저자 제외 산술 재생 / 입력·출력: dict 또는 JSON 경로 -> 분모·해시·범위 제한 / 검증: test_case61_cohort.
# [수정: 전문가4·8] 2026-09-26 case62
# 종류: 오류수정 / 재현 방법: ../상위경로·True 스키마·중복키·1e308 합계 / 변경 전: 암묵 수용 또는 OverflowError / 변경 후: 명시 ValueError / 왜: 불명확 명세와 경계 예외 차단 / 영향: 명시 절대 로컬 경로와 유효 산술은 유지.
def run_cohort(manifest):
    if isinstance(manifest, (str, Path)):
        manifest = json.loads(Path(manifest).read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_object)
    if not isinstance(manifest, dict) or set(manifest) != {'schema', 'assets', 'columns', 'numeric_columns', 'missing_tokens', 'steps', 'reported_value'}:
        raise ValueError('Incomplete or unknown manifest fields')
    if type(manifest['schema']) is not int or manifest['schema'] != 1 or manifest['missing_tokens'] != ['', 'NA']:
        raise ValueError('Unsupported schema or missing-value policy')
    columns = _columns(manifest['columns'])
    numeric = _columns(manifest['numeric_columns'])
    if not set(numeric) <= set(columns):
        raise ValueError('Missing numeric column')
    reported = manifest['reported_value']
    if type(reported) is not int or reported < 0:
        raise ValueError('Expected nonnegative reported row count')
    steps = manifest['steps']
    if not isinstance(steps, list) or not steps:
        raise ValueError('Missing exclusion policy')
    allowed = {'complete_cases': {'name', 'op', 'columns'}, 'sum_columns_equals': {'name', 'op', 'columns', 'value'}, 'eq': {'name', 'op', 'column', 'value'}, 'inclusive_range': {'name', 'op', 'column', 'min', 'max'}}
    names = {'raw_rows'}
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get('op'), str) or step['op'] not in allowed or set(step) != allowed[step['op']]:
            raise ValueError('Unknown operation or malformed step')
        op, name = step['op'], step['name']
        if not isinstance(name, str) or not name or name in names:
            raise ValueError('Expected unique step name')
        names.add(name)
        fields = _columns(step['columns']) if 'columns' in step else _columns([step['column']])
        if not set(fields) <= set(columns):
            raise ValueError('Missing referenced column')
        if index == 0 and op != 'complete_cases':
            raise ValueError('Complete-case policy must be first')
        if op == 'complete_cases':
            if index != 0 or fields != columns:
                raise ValueError('Complete-case policy must list all columns in order')
        else:
            if not set(fields) <= set(numeric):
                raise ValueError('Arithmetic requires explicit numeric columns')
            for key in ('value', 'min', 'max'):
                if key in step: _number(step[key])
            if op == 'inclusive_range' and _number(step['min']) > _number(step['max']):
                raise ValueError('Inverted inclusive range')
    assets = manifest['assets']
    if not isinstance(assets, dict) or set(assets) != {'data', 'source', 'author_code'}:
        raise ValueError('Missing asset contract')
    payloads, hashes = {}, {}
    for role, asset in assets.items():
        if not isinstance(asset, dict) or set(asset) != {'path', 'sha256'} or not isinstance(asset['path'], str) or not asset['path'] or not isinstance(asset['sha256'], str) or len(asset['sha256']) != 64 or any(c not in '0123456789abcdef' for c in asset['sha256']):
            raise ValueError('Missing or malformed asset hash/path')
        asset_path = Path(asset['path'])
        resolved = (ROOT / asset_path).resolve()
        if not asset_path.is_absolute() and not resolved.is_relative_to(ROOT.resolve()):
            raise ValueError('Relative asset path outside project')
        try:
            payload = resolved.read_bytes()
        except OSError as exc:
            raise ValueError(f'Missing asset: {role}') from exc
        digest = hashlib.sha256(payload).hexdigest()
        if digest != asset['sha256']:
            raise ValueError(f'Asset hash mismatch: {role}')
        payloads[role], hashes[role] = payload, digest
    try:
        reader = csv.reader(io.StringIO(payloads['data'].decode('utf-8-sig'), newline=''), strict=True)
        header = next(reader, None)
        if header != columns:
            raise ValueError('CSV header differs from explicit column contract')
        rows = []
        for line, cells in enumerate(reader, 2):
            if len(cells) != len(columns):
                raise ValueError(f'Malformed CSV row width at line {line}')
            row = dict(zip(columns, cells))
            for col in numeric:
                if row[col] not in manifest['missing_tokens']:
                    row[col] = _number(row[col])
            rows.append(row)
    except (UnicodeError, csv.Error) as exc:
        raise ValueError('Malformed CSV encoding or syntax') from exc
    # All policy, assets and cells are validated before filtering starts.
    raw_count = len(rows)
    stages = [{'name': 'raw_rows', 'input_rows': raw_count, 'excluded_rows': 0, 'remaining_rows': raw_count}]
    for step in steps:
        before = len(rows)
        op = step['op']
        if op == 'complete_cases':
            rows = [r for r in rows if all(r[c] not in manifest['missing_tokens'] for c in step['columns'])]
        elif op == 'sum_columns_equals':
            try:
                sums = [math.fsum(r[c] for c in step['columns']) for r in rows]
            except OverflowError as exc:
                raise ValueError('Nonfinite row sum') from exc
            if any(not math.isfinite(total) for total in sums):
                raise ValueError('Nonfinite row sum')
            rows = [r for r, total in zip(rows, sums) if total == _number(step['value'])]
        elif op == 'eq':
            rows = [r for r in rows if r[step['column']] == _number(step['value'])]
        else:
            rows = [r for r in rows if _number(step['min']) <= r[step['column']] <= _number(step['max'])]
        stages.append({'name': step['name'], 'input_rows': before, 'excluded_rows': before - len(rows), 'remaining_rows': len(rows)})
    return {'schema': 1, 'evidence_class': 'DEVELOPER_EVALUATION', 'engine': 'Python stdlib declarative cohort arithmetic; author R not executed', 'asset_sha256': hashes, 'manifest_sha256': hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest(), 'stages': stages, 'final_rows': len(rows), 'reported_value': reported, 'arithmetic_difference': len(rows) - reported, 'arithmetic_match': len(rows) == reported, 'source_scope_verified': False, 'full_paper_reproduced': False, 'human_verified': False, 'registration_status': 'PENDING', 'production_gate_approved': False}


# [작성: 전문가4] 2026-09-26 case61
# 무엇·왜: 독립 CLI 재실행 / 입력·출력: manifest 경로 -> JSON stdout / 검증: 실제 계약 targeted test.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    print(json.dumps(run_cohort(args.manifest), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Compare eight preregistered synthetic expectations with the existing registry engine."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from core.paths import PROJECT_ROOT
from tools.case_registry import audit_registry
from tools.independent_replay import _load_json


EXPECTATIONS = PROJECT_ROOT / 'data/evaluation/fixed_demo_expectations.json'
EXPECTATIONS_SHA256 = '4b94ab174fa11a7964dbea3b3e03a359aa35ffbc51562b637be80cfe8bc67b17'
NUMERIC_FIELDS = ('value', 'independent_value', 'rows_used', 'observations_used')


def run_fixed_demo_evaluation(expectations_path=EXPECTATIONS, *, expected_sha256=EXPECTATIONS_SHA256):
    """Run only fixed input mappings; a caller-supplied hash permits negative-control tests."""
    raw = Path(expectations_path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) > 2 * 1024 * 1024 or digest != expected_sha256:
        raise ValueError('고정 기대값 파일 크기 또는 SHA256이 다릅니다.')
    plan = _load_json(raw)
    cases = plan['cases']
    if (plan['schema'] != 'NAIS_FIXED_DEMO_EXPECTATIONS_1' or
            [case['id'] for case in cases] != [f'G{n:02d}' for n in range(1, 9)]):
        raise ValueError('고정 8건 기대값 순서 또는 스키마가 다릅니다.')
    source = plan['inputs']['source_text'].encode('utf-8')
    data = plan['inputs']['csv_text'].encode('utf-8')
    with TemporaryDirectory(prefix='nais-fixed-demo-') as directory:
        root = Path(directory)
        (root / 'source.txt').write_bytes(source)
        (root / 'data.csv').write_bytes(data)
        base = dict(plan['baseline_registration'], source_file='source.txt',
                    source_sha256=hashlib.sha256(source).hexdigest(), data_file='data.csv',
                    data_sha256=hashlib.sha256(data).hexdigest())
        manifest = root / 'registry.json'
        manifest.write_text(json.dumps({'schema': 1, 'cases': [
            dict(base, claim_id=case['id'], **case['overrides']) for case in cases
        ]}, ensure_ascii=False), encoding='utf-8')
        actual_report = audit_registry(manifest, root=root)
    if [row['claim_id'] for row in actual_report['results']] != [case['id'] for case in cases]:
        raise ValueError('고정 8건의 실제 결과 수 또는 Claim ID 순서가 다릅니다.')
    comparisons = []
    for case, actual in zip(cases, actual_report['results']):
        expected = case['expected']
        differences = [field for field, value in expected.items()
                       if field not in ('reason_contains', 'no_calculation') and actual.get(field) != value]
        if expected.get('reason_contains') not in (None, '') and expected['reason_contains'] not in actual.get('reason', ''):
            differences.append('reason_contains')
        if expected.get('no_calculation') and any(field in actual for field in NUMERIC_FIELDS):
            differences.append('no_calculation')
        comparisons.append({'id': case['id'], 'label': case['label'], 'input_changes': case['overrides'],
                            'expected': expected, 'actual': actual, 'passed': not differences,
                            'different_fields': differences})
    return {'schema': 1, 'scope': plan['scope'], 'expected_basis': plan['expected_basis'],
            'synthetic': True, 'human_approval': False, 'new_model_calls': 0,
            'inputs': plan['inputs'], 'baseline_registration': plan['baseline_registration'],
            'expectations_sha256': digest, 'source_sha256': hashlib.sha256(source).hexdigest(),
            'data_sha256': hashlib.sha256(data).hexdigest(),
            'reference_expectations': Path(expectations_path).resolve() == EXPECTATIONS.resolve() and digest == EXPECTATIONS_SHA256,
            'case_count': len(cases), 'passed_count': sum(row['passed'] for row in comparisons),
            'failed_count': sum(not row['passed'] for row in comparisons),
            'expected_status_counts': dict(Counter(case['expected']['action'] for case in cases)),
            'actual_status_counts': dict(Counter(row['action'] for row in actual_report['results'])),
            'all_passed': all(row['passed'] for row in comparisons), 'cases': comparisons,
            'limitations': '합성 4행의 지원 등록 산술·차단 검사만 완료. 논문 전체 재현, 사람 의미 승인, 실제 AI 실력·오류율·범용 AI 우위는 측정하지 않음.'}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = run_fixed_demo_evaluation()
    payload = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(payload, encoding='utf-8')
    else:
        print(payload)
    raise SystemExit(0 if report['all_passed'] else 1)

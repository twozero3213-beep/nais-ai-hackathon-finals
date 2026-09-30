"""현재 계산 경로의 경계 관찰. 제품 로직·승인·외부 서비스는 변경하지 않는다.

실행: python -B 1_이채우_경계검증.py --output <결과.json>
산술 일치와 근거 충분성은 별개다. 출력은 관찰 기록이며 제품 통과 인증이 아니다.
"""
import argparse
import copy
import hashlib
import json
import platform
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evidence_gate.compute import ols
from evidence_gate.gate import evaluate
from evidence_gate.spec import empty_spec

ROOT = Path(__file__).resolve().parent


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def synthetic_spec(data, method, **fields):
    spec = empty_spec('BOUNDARY-SYNTHETIC')
    spec.update(method=method, filters=[], data_fingerprint=fingerprint(data), tolerance=1e-9,
                source_location={'source_id': 'SYNTHETIC', 'locator': 'test definition',
                                 'quote': 'Synthetic boundary observation, not a research finding.'})
    spec.update(fields)
    return spec


def capture(call):
    try:
        return {'returned': call()}
    except Exception as exc:
        return {'exception': type(exc).__name__, 'message': str(exc)}


def observe():
    data = (ROOT / 'evidence_gate/fixtures/penguins_raw.csv').read_bytes()
    spec = json.loads((ROOT / 'evidence_gate/examples/penguins_raw_rows.spec.json').read_text(encoding='utf-8'))
    observations = {'penguin_rows': capture(lambda: evaluate(spec, data))}
    changed = data.replace(data.split(b'\n')[1] + b'\n', b'', 1)
    observations['changed_csv'] = capture(lambda: evaluate(spec, changed))
    irrelevant = copy.deepcopy(spec)
    irrelevant['source_location']['quote'] = 'This sentence does not state a penguin count.'
    observations['quote_without_count'] = capture(lambda: evaluate(irrelevant, data))
    malformed = dict(spec, method=[])
    observations['method_array'] = capture(lambda: evaluate(malformed, data))
    nonfinite = dict(spec, reported_value=float('nan'))
    observations['nonfinite_report'] = capture(lambda: evaluate(nonfinite, data))
    mean_data = b'x\n1\n3\n'
    mean_spec = synthetic_spec(mean_data, 'mean', variable='x', missing_policy='error',
                               missing_tokens=[''], reported_value=2)
    observations['unconfirmed_scope'] = capture(lambda: evaluate(mean_spec, mean_data))
    huge = b'x\n1e308\n1e308\n'
    huge_spec = synthetic_spec(huge, 'mean', variable='x', missing_policy='error',
                               missing_tokens=[''], reported_value=1e308)
    observations['finite_mean_overflow'] = capture(lambda: evaluate(huge_spec, huge))
    aligned = b'Species,v\nB,1\nA,2\nC,3\n'
    align_spec = synthetic_spec(aligned, 'row_alignment', data_id_column='Species',
                                reference_ids_source='synthetic-reference-list')
    # 합성 확인 객체로 승인 결속의 경계만 관찰한다. 실제 연구자 승인이 아니다.
    approval = {'reorder': {'approver': 'SYNTHETIC_REVIEWER', 'basis': 'first synthetic reference order'}}
    observations['reference_order_1'] = capture(lambda: evaluate(align_spec, aligned,
        reference_ids=['A', 'B', 'C'], approvals=approval))
    observations['changed_reference_same_approval'] = capture(lambda: evaluate(align_spec, aligned,
        reference_ids=['C', 'A', 'B'], approvals=approval))
    for offset in (1000000, 100000000):
        table = [[float(y), float(offset + y)] for y in range(1, 6)]
        observations[f'ols_offset_{offset}'] = {
            'reference_slope': 1, 'reference_intercept': -offset,
            'observation': capture(lambda: ols(table, ['x']))}
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): fingerprint(p.read_bytes())
              for p in sorted((ROOT / 'evidence_gate').rglob('*'))
              if p.is_file() and '__pycache__' not in p.parts}
    return {'contributor_version': 1,
            'recorded_at_kst': datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),
            'python': platform.python_version(), 'status': 'OBSERVATIONS_NOT_RELEASE_CERTIFICATION',
            'scope': 'Local arithmetic and boundary observations; no model calls or external requests',
            'engine_file_sha256': hashes, 'observations': observations}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(observe(), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('Boundary observations saved; this is not a product pass certificate.')

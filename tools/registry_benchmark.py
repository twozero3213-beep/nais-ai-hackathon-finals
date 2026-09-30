"""Measure preconfigured registry execution; no human registration-time claim."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tempfile

from core.source_revision import source_revision

ROOT = Path(__file__).resolve().parents[1]


# [작성: 전문가4] 2026-09-26 case65
# 무엇/왜: 코드 내용과 측정 환경을 함께 결속, Git/override 라벨은 내용 아님 / 입출력: 실행환경 -> 안정적 provenance / 검증: tests/test_case65_benchmark.py.
def benchmark_provenance():
    packages = {}
    for name in ('pandas', 'numpy', 'scipy', 'statsmodels', 'streamlit', 'pypdf'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {'source_revision': source_revision().split('|', 1)[0],
            'environment': {'python': sys.version, 'executable': Path(sys.executable).name,
                            'platform': platform.platform(), 'processor': platform.processor(),
                            'packages': packages, 'thread_env': {name: os.environ.get(name, '') for name in
                                ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')}}}


# [작성: 전문가4·7] 2026-09-26 case63: 수치·분모·차단 결과까지 비교해 반복 중 결과 변동을 숨기지 않음.
def _fingerprint(result):
    return hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')).hexdigest()


# [작성: 전문가4·7] 2026-09-26 case63: 새 프로세스와 이미 import된 프로세스의 반복 실행을 분리.
# [수정: 전문가4] 2026-09-26 case65: 무엇/왜: 시작·worker·종료 코드환경 일치 확인 / 입출력: 등록 -> provenance 포함 측정 / 검증: case65 benchmark 시험.
def benchmark_registry(manifest=ROOT/'data/evaluation/registered_cases.json', root=None, repeats=3):
    if type(repeats) is not int or repeats < 1:
        raise ValueError('repeats must be an integer >= 1')
    root = Path(ROOT if root is None else root).resolve()
    if not root.is_dir():
        raise ValueError('root directory does not exist')
    manifest = Path(manifest).resolve()
    # [수정: 전문가4·7] 2026-09-26 case63: 실제 source/data bytes까지 측정 기록에 결속.
    from tools.change_impact import snapshot_registry
    snapshot_hash = snapshot_registry(manifest, root=root)['content_sha256']
    provenance = benchmark_provenance()
    measured_at = datetime.now(timezone.utc).isoformat()
    command = [sys.executable, '-m', 'tools.registry_benchmark', '--worker',
               '--manifest', str(manifest), '--root', str(root)]
    environment = dict(os.environ, PYTHONIOENCODING='utf-8')
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True,
                               encoding='utf-8', check=True, timeout=300)
    cold_wall = time.perf_counter() - started
    cold = json.loads(completed.stdout)
    if cold.get('provenance') != provenance:
        raise ValueError('cold worker code/environment differ')
    from tools.case_registry import audit_registry, load_registry
    raw, cases = load_registry(manifest)
    started = time.perf_counter()
    warmup = audit_registry(manifest, root=root)
    warmup_seconds = time.perf_counter() - started
    expected = _fingerprint(cold['result'])
    if _fingerprint(warmup) != expected:
        raise ValueError('cold/warmup results differ')
    durations = []
    per_case = {case['claim_id']:Counter() for case in cases}
    for _ in range(repeats):
        started = time.perf_counter()
        result = audit_registry(manifest, root=root)
        durations.append(time.perf_counter() - started)
        if _fingerprint(result) != expected:
            raise ValueError('repeated numeric/status results differ')
        for row in result['results']:
            per_case[row['claim_id']][row['action']] += 1
    if snapshot_registry(manifest, root=root)['content_sha256'] != snapshot_hash:
        raise ValueError('registered inputs changed during benchmark')
    if benchmark_provenance() != provenance:
        raise ValueError('code/environment changed during benchmark')
    return {
        'schema':1, 'measured_at_utc':measured_at,
        'provenance':provenance,
        'snapshotcontent_sha256':snapshot_hash,
        'manifest_sha256':hashlib.sha256(raw).hexdigest(),
        'manifest_bytes':len(raw), 'manifest_lines':len(raw.splitlines()),
        'case_count':len(cases), 'case_top_level_field_count':sum(len(c) for c in cases),
        'unique_dataset_contents':len({c.get('data_sha256') for c in cases if isinstance(c.get('data_sha256'),str)}),
        'unique_dataset_references':len({(c.get('data_file'), c.get('data_sha256')) for c in cases if isinstance(c.get('data_file'),str) and isinstance(c.get('data_sha256'),str)}),
        'unique_source_data_pairs':len({(c.get('source_sha256'), c.get('data_sha256')) for c in cases if isinstance(c.get('source_sha256'),str) and isinstance(c.get('data_sha256'),str)}),
        'dataset_count_definition':'registered SHA256 content identities; references use (path, data hash), source/data pairs use (source hash, data hash). Renamed identical CSVs count once as contents. These counts do not certify independent papers or datasets; invalid/missing non-string fields are excluded.',
        'source_code_changes_required':0,
        'source_code_changes_basis':'preconfigured mapping config only; supported count_rows/mean/missing_cells use existing shared engines; excludes shared case63 implementation cost, source acquisition, unsupported methods and human scope review',
        'registration_time_measured':False,
        'measurement_scope':'local machine execution of preconfigured mappings, not human registration time or a general paper reproducibility benchmark',
        'clock':'time.perf_counter',
        'cold':{'runs':1, 'fresh_process_wall_seconds':cold_wall,
                'provenance':cold['provenance'],
                'import_and_audit_seconds':cold['import_and_audit_seconds'],
                'definition':'fresh Python process; OS filesystem cache is not cleared; wall includes process startup and output'},
        'warm':{'repeats':repeats, 'warmup_seconds':warmup_seconds,
                'seconds':durations, 'median_seconds':statistics.median(durations),
                'definition':'same process after imports and one excluded warmup; includes file reads, hashing and both engines'},
        'environment':provenance['environment'],
        'results_identical':True, 'result_sha256':expected,
        'status_counts':dict(Counter(r['action'] for r in result['results'])),
        'per_case_status_counts':{key:dict(value) for key,value in per_case.items()},
        'results':result['results'],
    }


# [작성: 전문가4] 2026-09-26 case65
# 무엇/왜: 동일 등록의 복제 부하만 반복 측정 / 입출력: 명세·규모 목록 -> 합성 규모별 기록 / 검증: case65 시험, 독립 논문 증가 아님 명시.
# [수정: 전문가4] 2026-09-26 case65: 무엇/왜: 임시 명세도 root 내부 생성해 기존 경계 준수 / 입출력: root -> 자동정리 임시폴더 / 검증: 실제 5사례 선행 FAIL→PASS.
def benchmark_scalability(manifest, root=None, counts=(5, 25, 100), repeats=3):
    from tools.case_registry import load_registry
    _, cases = load_registry(manifest)
    if not cases or not counts or any(type(count) is not int or count < 1 for count in counts):
        raise ValueError('nonempty cases and positive integer counts required')
    measurements = []
    with tempfile.TemporaryDirectory(prefix='evidence-scale-', dir=ROOT if root is None else Path(root).resolve()) as directory:
        for count in counts:
            copied = [dict(cases[i % len(cases)], claim_id=f'SYNTHETIC-{i:04d}') for i in range(count)]
            path = Path(directory) / f'cases-{count}.json'
            path.write_text(json.dumps({'schema': 1, 'cases': copied}, ensure_ascii=False), encoding='utf-8')
            measurements.append(benchmark_registry(path, root=root, repeats=repeats))
    return {'schema': 1, 'synthetic_replication': True, 'base_case_count': len(cases),
            'scope': 'Repeated copies of existing developer mappings; not independent papers, new datasets, human registration time, or accuracy evidence.',
            'measurements': measurements}


# [작성: 전문가4/6] 2026-09-29 case92
# 무엇을: 같은 전후검사로 선택/전체 재계산 측정 / 왜: 검사 범위가 다른 시간 비교 방지 / 입력·출력: 이전snapshot·명세→반복시간·대응결과 동일 / 검증: test_case92 및 실제 4명세 측정. 사람시간·AI 비교 아님.
def benchmark_author_changes(manifests, previous, root=None, repeats=3):
    from tools.change_impact import execute_author_model_changes, snapshot_author_models
    if type(repeats) is not int or not 1 <= repeats <= 20:
        raise ValueError('repeats must be an integer from 1 to 20')
    root = Path(ROOT if root is None else root).resolve()
    before = snapshot_author_models(manifests, root=root)
    provenance = benchmark_provenance()
    samples = []; expected = None; durations = {'selected':[], 'full':[]}
    # ponytail: 로컬 warm 반복만 측정. 서버 동시성/콜드 프로세스 성능은 별도 실험이 필요.
    for index in range(repeats + 1):
        order = ['selected', 'full'] if index % 2 == 0 else ['full', 'selected']
        runs = {}; elapsed = {}
        for mode in order:
            started = time.perf_counter()
            runs[mode] = execute_author_model_changes(previous, manifests, root=root, full=mode == 'full')
            elapsed[mode] = time.perf_counter() - started
        complete = dict(zip(runs['full']['executed_manifests'], runs['full']['reports'], strict=True))
        subset = dict(zip(runs['selected']['executed_manifests'], runs['selected']['reports'], strict=True))
        if any(name not in complete or value != complete[name] for name, value in subset.items()):
            raise ValueError('Selective/full corresponding results differ')
        identity = _fingerprint(runs)
        if expected is not None and identity != expected:
            raise ValueError('Benchmark inputs or repeated results changed')
        expected = identity
        if index:
            samples.append({'order':order, 'seconds':elapsed})
            for mode in durations: durations[mode].append(elapsed[mode])
    if before != snapshot_author_models(manifests, root=root) or provenance != benchmark_provenance():
        raise ValueError('Benchmark input/code/environment changed')
    return {'schema':1, 'measured_at_utc':datetime.now(timezone.utc).isoformat(),
            'scope':'Local warm execution; both modes include planning, input/code/environment pre/post checks and fresh arithmetic. Not human time or general-AI comparison.',
            'provenance':provenance, 'current_snapshot_sha256':before['content_sha256'],
            'previous_snapshot_sha256':previous['content_sha256'], 'repeats':repeats,
            'warmup_pairs_excluded':1, 'samples':samples, 'corresponding_results_identical':True,
            'result_sha256':expected,
            'executed_models':{mode:sum(len(r['results']) for r in run['reports']) for mode,run in runs.items()},
            'executed_manifests':{mode:run['executed_manifests'] for mode,run in runs.items()},
            'median_seconds':{mode:statistics.median(values) for mode,values in durations.items()},
            'human_time_measured':False, 'general_ai_advantage_measured':False}


# [작성: 전문가4·7] 2026-09-26 case63: 안정된 모듈 CLI, 측정 worker의 import도 명시 시간에 포함.
# [수정: 전문가4] 2026-09-26 case65: 무엇/왜: worker provenance와 선택 합성규모 CLI / 입출력: 인자 -> 측정 JSON / 검증: case65 측정 명령.
# [수정: 전문가4/6] 2026-09-29 case92
# 종류: 검증방법추가 / 재현 방법: 선택/전체 검사의 범위가 다른 시간 비교 / 변경 전: 일반등록만 / 변경 후: 저자명세 동조건 측정 분기 / 왜: 같은 실행계약 비교 / 영향: 기존 명령 유지·새 인자 명시 실행; test_case92.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT/'data/evaluation/registered_cases.json')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--scale-counts', nargs='+', type=int)
    parser.add_argument('--author-manifests', nargs='+')
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    if args.author_manifests:
        if not args.previous or args.worker or args.scale_counts:
            parser.error('Author benchmark needs --previous; no worker/scale mode')
        from tools.independent_replay import _load_json
        with args.previous.open('rb') as handle: raw = handle.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024: parser.error('Previous snapshot exceeds 2MiB')
        output = benchmark_author_changes(args.author_manifests, _load_json(raw), args.root, args.repeats)
    elif args.worker:
        started = time.perf_counter()
        from tools.case_registry import audit_registry
        result = audit_registry(args.manifest, root=args.root)
        output = {'result':result, 'import_and_audit_seconds':time.perf_counter()-started,
                  'provenance':benchmark_provenance()}
    elif args.scale_counts:
        output = benchmark_scalability(args.manifest, root=args.root, counts=args.scale_counts, repeats=args.repeats)
    else:
        output = benchmark_registry(args.manifest, root=args.root, repeats=args.repeats)
    text = json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        print(text, end='')


if __name__ == '__main__':
    main()

"""Track exact registered inputs; no source authenticity or human approval claim.

Snapshots bind their own content, not their author. An attacker rewriting content
and every digest cannot be detected without an external trusted record/signature.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath

from tools.independent_replay import _load_json, _finite

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ('ADDED', 'REMOVED', 'UNCHANGED', 'REEXECUTION_REQUIRED', 'BLOCKED_INPUT')
LIMITATIONS = ('Input identity and declared-hash consistency only; not source truth, '
               'human approval, arithmetic verification or generic-AI superiority. '
               'Rewriting content and all hashes together is not detected.')


# [작성: 전문가4/8] 2026-09-26 case63: 명세 키 순서와 무관한 유한 JSON 정규화.
def _digest(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError('Invalid canonical JSON') from exc
    return hashlib.sha256(raw).hexdigest()


# [작성: 전문가4/8] 2026-09-26 case63: SHA-256 형식 검증, 작성자 인증으로 사용하지 않음.
def _is_hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


# [작성: 전문가4/8] 2026-09-26 case63: Windows/Unix 절대·상위경로와 symlink 탈출 차단.
def _relative(value):
    return (isinstance(value, str) and bool(value) and '\\' not in value
            and not Path(value).is_absolute() and not PureWindowsPath(value).drive
            and ':' not in value and '..' not in Path(value).parts)


# [작성: 전문가4/8] 2026-09-26 case63: 지정 root 내부 실제 bytes만 해시, 오류에 로컬 경로 미노출.
# [수정: 전문가4] 2026-09-29 case92
# 종류: 오류수정 / 재현 방법: 8MiB+1 참조 / 변경 전: 무제한 read_bytes / 변경 후: 한도+1 읽기 후 차단 / 왜: 검산 전 메모리 고갈 방지 / 영향: 과대 참조만 차단, 정상 지문 동일; test_case92.
def _reference(case, kind, root):
    path, declared = case.get(kind + '_file'), case.get(kind + '_sha256')
    result = dict(path=path, declared_sha256=declared, actual_sha256=None, status='BLOCKED_INPUT')
    if not _relative(path):
        result['reason'] = 'INVALID_RELATIVE_PATH'
        return result
    try:
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise ValueError('outside root')
        with target.open('rb') as handle:
            raw = handle.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            result['reason'] = 'FILE_TOO_LARGE'
            return result
        result['actual_sha256'] = hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, RuntimeError):
        result['reason'] = 'UNREADABLE_OR_OUTSIDE_ROOT'
        return result
    if not _is_hash(declared) or declared != result['actual_sha256']:
        result['reason'] = 'DECLARED_HASH_MISMATCH'
    else:
        result.update(status='CONSISTENT', reason='DECLARED_HASH_MATCH')
    return result


# [작성: 전문가4/8] 2026-09-26 case63: 추가 파일 의존성은 추측하지 않고 차단.
# [수정:전문가4] 2026-09-27 case69 목적: 미추적 전처리 의존성 차단; 입력: 계약메타; 출력: unknown 여부; 검증: raw/code를 추적하지 않는 snapshot의 false UNCHANGED 회귀.
# [수정:전문가4] 2026-09-27 case69 종류: 미추적 의존성 차단 / 재현: 동일 계약 false UNCHANGED / 전후: CONSISTENT→BLOCKED_INPUT / 왜: raw/code 추적 미구현 / 영향: preprocessing_contract 포함명세만.
def _unknown_dependencies(metadata):
    return 'preprocessing_contract' in metadata or any((key.endswith(('_file', '_files', '_path', '_paths'))
                or key in ('dependencies', 'inputs'))
               and key not in ('source_file', 'data_file') for key in metadata)


# [작성: 전문가4/8] 2026-09-26 case63: 전체 case 메타데이터를 결속, 공유 파일 Claim 각각 참조 보존.
def snapshot_registry(manifest, root=None):
    """Return schema-1 snapshot; root defaults to project root, never manifest parent.

    A CONSISTENT reference means only byte/hash consistency. Pending scope and
    unsupported numerical methods remain visible in metadata, not approved here.
    Malformed registry structure raises ValueError; bad files block their claims.
    Extra *_file(s), *_path(s), dependencies or inputs fields block affected claims
    because this version resolves only source_file and data_file dependencies.
    """
    root = Path(root if root is not None else ROOT).resolve()
    manifest = Path(manifest)
    if not manifest.is_absolute():
        manifest = root / manifest
    if not manifest.resolve().is_relative_to(root):
        raise ValueError('Manifest outside root')
    registry = _load_json(manifest.read_bytes())
    if (not isinstance(registry, dict) or type(registry.get('schema')) is not int
            or registry['schema'] != 1 or not isinstance(registry.get('cases'), list)):
        raise ValueError('Invalid registry schema')
    claims, ids = [], set()
    for case in registry['cases']:
        if not isinstance(case, dict):
            raise ValueError('Invalid claim object')
        cid = case.get('claim_id')
        if not isinstance(cid, str) or not cid.strip() or cid in ids:
            raise ValueError('Invalid or duplicate claim ID')
        ids.add(cid)
        # Canonical hash rejects overflowed numbers; all case fields are bound.
        metadata_hash = _digest(case)
        refs = {kind: _reference(case, kind, root) for kind in ('source', 'data')}
        blocked = _unknown_dependencies(case) or any(r['status'] != 'CONSISTENT' for r in refs.values())
        claims.append(dict(claim_id=cid, metadata=case, metadata_sha256=metadata_hash,
                           references=refs, status='BLOCKED_INPUT' if blocked else 'CONSISTENT'))
    metadata = {key: value for key, value in registry.items() if key != 'cases'}
    snapshot = dict(schema=1, registry_metadata=metadata, registry_metadata_sha256=_digest(metadata),
                    claims=sorted(claims, key=lambda c: c['claim_id']))
    snapshot['content_sha256'] = _digest(snapshot)
    return snapshot


# [작성: 전처리 추적 담당] 2026-09-28 case83 / 무엇·왜: source/data/raw/code 참조검증 재사용 / 입출력: ref·명세→일관성 / 검증: 경로·해시·상태 결속.
# [수정: 전문가4] 2026-09-29 case92
# 종류: 오류수정 / 재현 방법: 과대 입력 snapshot / 변경 전: 새 사유 거부 / 변경 후: FILE_TOO_LARGE 차단 상태 수용 / 왜: 읽기/기록검증 계약 일치 / 영향: 수치실행/승인 없이 차단계획 전달; test_case92.
def _validate_reference(ref, path, declared_hash):
    if not isinstance(ref, dict) or set(ref) != {'path', 'declared_sha256', 'actual_sha256', 'status', 'reason'}:
        raise ValueError('Invalid snapshot reference')
    actual, declared = ref['actual_sha256'], ref['declared_sha256']
    if (ref['path'] != path
            or declared != declared_hash
            or actual is not None and not _is_hash(actual)):
        raise ValueError('Invalid snapshot reference binding')
    consistent = _relative(ref['path']) and _is_hash(declared) and actual == declared
    if ref['status'] != ('CONSISTENT' if consistent else 'BLOCKED_INPUT'):
        raise ValueError('Invalid snapshot reference status')
    if not isinstance(ref['reason'], str) or ref['reason'] not in {'INVALID_RELATIVE_PATH', 'UNREADABLE_OR_OUTSIDE_ROOT',
                              'DECLARED_HASH_MISMATCH', 'DECLARED_HASH_MATCH', 'FILE_TOO_LARGE'}:
        raise ValueError('Invalid snapshot reason')
    if consistent != (ref['reason'] == 'DECLARED_HASH_MATCH'):
        raise ValueError('Invalid snapshot consistency reason')
    return consistent


# [작성: 전문가4/8] 2026-09-26 case63: 과거 snapshot 구조·메타해시·참조결속·상태 자체일관성 확인.
# [수정: 전처리 추적 담당] 2026-09-28 case83 / 무엇·왜: 같은 엄격검증으로 opt-in schema2 결속 / 입출력: snapshot→Claim색인 / 검증: schema1 회귀·재해시변조 거부.
def _validate(snapshot, *, preprocessing=False):
    if (not isinstance(snapshot, dict) or set(snapshot) != {
            'schema', 'registry_metadata', 'registry_metadata_sha256', 'claims', 'content_sha256'}
            or type(snapshot['schema']) is not int or snapshot['schema'] != (2 if preprocessing else 1)
            or not isinstance(snapshot['claims'], list)
            or not isinstance(snapshot['registry_metadata'], dict)):
        raise ValueError('Invalid snapshot schema')
    registry_metadata = snapshot['registry_metadata']
    if (type(registry_metadata.get('schema')) is not int or registry_metadata['schema'] != 1
            or 'cases' in registry_metadata):
        raise ValueError('Invalid snapshot registry metadata')
    if (snapshot['registry_metadata_sha256'] != _digest(registry_metadata)
            or snapshot['content_sha256'] != _digest({k: v for k, v in snapshot.items() if k != 'content_sha256'})):
        raise ValueError('Snapshot digest mismatch')
    claims = {}
    for row in snapshot['claims']:
        keys = {'claim_id', 'metadata', 'metadata_sha256', 'references', 'status'}
        if preprocessing:
            keys.add('preprocessing')
        if not isinstance(row, dict) or set(row) != keys:
            raise ValueError('Invalid snapshot claim')
        cid, metadata, refs = row['claim_id'], row['metadata'], row['references']
        if (not isinstance(cid, str) or not cid.strip() or cid in claims
                or not isinstance(metadata, dict) or metadata.get('claim_id') != cid
                or row['metadata_sha256'] != _digest(metadata)
                or not isinstance(refs, dict) or set(refs) != {'source', 'data'}):
            raise ValueError('Invalid snapshot claim binding')
        checked_metadata = metadata
        if preprocessing:
            checked_metadata = {k: v for k, v in metadata.items() if k != 'preprocessing_contract'}
        blocked = _unknown_dependencies(checked_metadata)
        for kind, ref in refs.items():
            consistent = _validate_reference(ref, metadata.get(kind + '_file'), metadata.get(kind + '_sha256'))
            blocked = blocked or not consistent
        if preprocessing:
            _validate_preprocessing(row)
            blocked = blocked or row['preprocessing']['status'] == 'BLOCKED_INPUT'
        if row['status'] != ('BLOCKED_INPUT' if blocked else 'CONSISTENT'):
            raise ValueError('Invalid snapshot claim status')
        claims[cid] = row
    return claims


# [작성: 전문가4/8] 2026-09-26 case63: 수치일치와 무관하게 입력 변경마다 재실행 필요 기록.
# [수정: 전처리 추적 담당] 2026-09-28 case83 / 무엇·왜: 기존 비교엔진에서 엄격 전처리refs 전파 / 입출력: 동종snapshot→변경Claim / 검증: raw/code 변경·독립Claim 보존.
def compare_snapshots(previous, current, *, _preprocessing=False):
    """Return sorted results + all action counts; invalid snapshots raise ValueError.

    BLOCKED_INPUT takes priority over added/removed/changed when either available
    claim has untrusted dependencies. UNCHANGED is never a human approval.
    """
    old, new = _validate(previous, preprocessing=_preprocessing), _validate(current, preprocessing=_preprocessing)
    registry_changed = previous['registry_metadata_sha256'] != current['registry_metadata_sha256']
    results = []
    for cid in sorted(old.keys() | new.keys()):
        before, after = old.get(cid), new.get(cid)
        changed = []
        if before is None or after is None:
            action = 'ADDED' if before is None else 'REMOVED'
            changed.append('claim_added' if before is None else 'claim_removed')
        else:
            if registry_changed:
                changed.append('registry_metadata')
            if before['metadata_sha256'] != after['metadata_sha256']:
                changed.append('case_metadata')
            for kind in ('source', 'data'):
                a, b = before['references'][kind], after['references'][kind]
                for key, label in [('path', 'reference'), ('actual_sha256', 'bytes'),
                                   ('declared_sha256', 'declared_hash'), ('status', 'consistency')]:
                    if a[key] != b[key]:
                        changed.append(kind + '_' + label)
            if _preprocessing:
                pa, pb = before['preprocessing'], after['preprocessing']
                if (pa['status'], pa['reason']) != (pb['status'], pb['reason']):
                    changed.append('preprocessing_status')
                for kind in ('raw', 'author_code'):
                    a, b = pa['dependencies'].get(kind), pb['dependencies'].get(kind)
                    if a is None or b is None:
                        if a != b:
                            changed.append('preprocessing_' + kind + '_reference')
                        continue
                    for key, label in [('path', 'reference'), ('actual_sha256', 'bytes'),
                                       ('declared_sha256', 'declared_hash'), ('status', 'consistency')]:
                        if a[key] != b[key]:
                            changed.append('preprocessing_' + kind + '_' + label)
            action = 'REEXECUTION_REQUIRED' if changed else 'UNCHANGED'
        if any(row is not None and row['status'] == 'BLOCKED_INPUT' for row in (before, after)):
            action = 'BLOCKED_INPUT'
        results.append(dict(claim_id=cid, action=action, changed_inputs=sorted(changed)))
    return dict(schema=2 if _preprocessing else 1, results=results,
                counts={action: sum(row['action'] == action for row in results) for action in ACTIONS},
                human_approval=False, limitations=LIMITATIONS,
                previous_sha256=previous['content_sha256'], current_sha256=current['content_sha256'])


# [작성: 전처리 추적 담당] 2026-09-28 case83 / 무엇·왜: 실제 실행계약의 선언 형식만 엄격 점검 / 입출력: case→raw/code 선언 또는 None / 검증: 자유목록·추가키·비유한·경로 차단.
def _contract_refs(case):
    if 'preprocessing_contract' not in case:
        return {}
    contract = case['preprocessing_contract']
    keys = {'kind', 'raw', 'author_code', 'column', 'excluded_value', 'missing_policy',
            'projection', 'source_rows', 'selected_rows'}
    if not isinstance(contract, dict) or set(contract) != keys:
        return None
    column, projection = contract['column'], contract['projection']
    if (contract['kind'] != 'numeric_not_equal_projection' or contract['missing_policy'] != 'drop'
            or not isinstance(column, str) or not column.isidentifier()
            or not isinstance(projection, list) or not projection
            or any(not isinstance(v, str) or not v for v in projection)
            or len(set(projection)) != len(projection)
            or any(type(contract[k]) is not int or contract[k] < 0 for k in ('source_rows', 'selected_rows'))
            or contract['selected_rows'] > contract['source_rows']):
        return None
    try:
        threshold = _finite(contract['excluded_value'])
    except (ValueError, TypeError, OverflowError):
        return None
    for kind, fields in [('raw', {'path', 'sha256'}),
                         ('author_code', {'path', 'sha256', 'quote', 'executed'})]:
        ref = contract[kind]
        if (not isinstance(ref, dict) or set(ref) != fields
                or not _relative(ref['path']) or not _is_hash(ref['sha256'])):
            return None
    author = contract['author_code']
    if author['executed'] is not False or author['quote'] != f'filter({column} != {threshold:g})':
        return None
    return {kind: contract[kind] for kind in ('raw', 'author_code')}


# [작성: 전처리 추적 담당] 2026-09-28 case83 / 무엇·왜: SHA일치 외 실제 raw→파생행 검증 재사용 / 입출력: case/root→명시 의존성 상태 / 검증: 같은 평균·다른 투영 차단.
def _snapshot_preprocessing(case, root):
    declared = _contract_refs(case)
    if declared == {}:
        return dict(dependencies={}, status='NOT_DECLARED', reason='NOT_DECLARED')
    if declared is None:
        return dict(dependencies={}, status='BLOCKED_INPUT', reason='INVALID_PREPROCESSING_CONTRACT')
    refs = {kind: _reference({'source_file': ref['path'], 'source_sha256': ref['sha256']},
                            'source', root) for kind, ref in declared.items()}
    result = dict(dependencies=refs, status='BLOCKED_INPUT', reason='DEPENDENCY_BLOCKED')
    if any(ref['status'] != 'CONSISTENT' for ref in refs.values()):
        return result
    # [작성: 전처리 추적 담당] 2026-09-28 case83 / 무엇·왜: 순환import 회피 후 안정 계약검증 호출 / 입출력: 검증bytes→명시 투영일치 / 검증: 저자코드 실행 없이 행순서·분모 대조.
    from tools.case_registry import _verify_preprocessing, _verified_bytes
    try:
        derived = _verified_bytes(case['data_file'], case['data_sha256'], root)
        _verify_preprocessing(case['preprocessing_contract'], derived, root)
    except (KeyError, ValueError, TypeError, OSError, UnicodeError, OverflowError, RuntimeError):
        result['reason'] = 'PREPROCESSING_VERIFICATION_FAILED'
    else:
        result.update(status='CONSISTENT', reason='VERIFIED_DECLARED_PROJECTION')
    return result


# [작성: 전처리 추적 담당] 2026-09-28 case83 / 무엇·왜: 과거 schema2 내부상태·엄격계약 결속 / 입출력: snapshot Claim→검증 / 검증: 재해시 경로·상태·누락ref 변조 거부.
def _validate_preprocessing(row):
    value = row['preprocessing']
    if not isinstance(value, dict) or set(value) != {'dependencies', 'status', 'reason'}:
        raise ValueError('Invalid preprocessing snapshot')
    deps, declared = value['dependencies'], _contract_refs(row['metadata'])
    if not isinstance(deps, dict):
        raise ValueError('Invalid preprocessing dependencies')
    if declared == {}:
        if value != dict(dependencies={}, status='NOT_DECLARED', reason='NOT_DECLARED'):
            raise ValueError('Invalid undeclared preprocessing state')
        return
    if declared is None:
        if value != dict(dependencies={}, status='BLOCKED_INPUT', reason='INVALID_PREPROCESSING_CONTRACT'):
            raise ValueError('Invalid unsupported preprocessing state')
        return
    if set(deps) != set(declared):
        raise ValueError('Invalid preprocessing dependency binding')
    consistent = all([_validate_reference(deps[k], ref['path'], ref['sha256'])
                      for k, ref in declared.items()])
    if not consistent:
        expected = ('BLOCKED_INPUT', 'DEPENDENCY_BLOCKED')
    elif value['reason'] == 'VERIFIED_DECLARED_PROJECTION':
        if row['references']['data']['status'] != 'CONSISTENT':
            raise ValueError('Verified preprocessing has blocked derived input')
        expected = ('CONSISTENT', 'VERIFIED_DECLARED_PROJECTION')
    else:
        expected = ('BLOCKED_INPUT', 'PREPROCESSING_VERIFICATION_FAILED')
    if (value['status'], value['reason']) != expected:
        raise ValueError('Invalid preprocessing verification state')


# [작성: 전처리 추적 담당] 2026-09-28 case83 / 무엇·왜: schema1 안정 API 보존하며 실제계약 opt-in 추적 / 입출력: schema1등록/root→schema2snapshot / 검증: 기존 전처리 차단 유지·선택API만 검증.
def snapshot_registry_with_preprocessing(manifest, root=None):
    """Schema-2 lineage for the existing numeric_not_equal_projection contract.

    Source/data hashing and registry parsing reuse schema 1. Raw/code hashing is
    followed by the existing projection verifier; this is declared arithmetic
    scope only, never author intent, full reproduction or human approval.
    Unsupported contracts and other dependencies remain blocked.
    """
    root = Path(ROOT if root is None else root).resolve()
    snapshot = snapshot_registry(manifest, root)
    snapshot['schema'] = 2
    for row in snapshot['claims']:
        metadata = row['metadata']
        row['preprocessing'] = _snapshot_preprocessing(metadata, root)
        checked = {k: v for k, v in metadata.items() if k != 'preprocessing_contract'}
        blocked = (_unknown_dependencies(checked)
                   or row['preprocessing']['status'] == 'BLOCKED_INPUT'
                   or any(ref['status'] != 'CONSISTENT' for ref in row['references'].values()))
        row['status'] = 'BLOCKED_INPUT' if blocked else 'CONSISTENT'
    snapshot['content_sha256'] = _digest({k: v for k, v in snapshot.items() if k != 'content_sha256'})
    _validate(snapshot, preprocessing=True)
    return snapshot


# [작성: 전처리 추적 담당] 2026-09-28 case83 / 무엇·왜: 미추적 과거schema와 비교 fail-closed / 입출력: schema2 두개→기존 영향판정 / 검증: schema1 혼합 거부·blocked 우선.
def compare_snapshots_with_preprocessing(previous, current):
    """Strict schema-2 comparison; schema-1 history needs a new baseline."""
    result = compare_snapshots(previous, current, _preprocessing=True)
    result['limitations'] = LIMITATIONS + (' Declared preprocessing projection is checked at snapshot creation; '
        'historical bytes are not replayed during comparison. Not author intent or full reproduction.')
    return result


# [작성: 실행검증 담당] 2026-09-29 case91 / 무엇: 중첩명세 미추적 의존성 검사 / 왜: 하위 의존성 누락으로 거짓 무변경 방지 / 입력·출력: JSON값→미추적 여부 / 검증: test_case91_execution 중첩의존성.
def _author_unknown(value):
    if isinstance(value, dict):
        return _unknown_dependencies(value) or any(_author_unknown(v) for v in value.values())
    return isinstance(value, list) and any(_author_unknown(v) for v in value)


# [작성: 실행검증 담당] 2026-09-29 case91 / 무엇: 기존 엄격 snapshot에 저자명세·모형ID 결속 검사 / 왜: 재해시 상태변조·모형누락 차단 / 입력·출력: snapshot→검증된 모형색인 또는 오류 / 검증: test_case91_execution 지문·상태·scope·누락 반례.
def _validate_author_snapshot(snapshot):
    claims = _validate(snapshot)
    if not claims:
        raise ValueError('Empty author-model snapshot')
    metadata = snapshot['registry_metadata']
    if set(metadata) != {'schema', 'kind', 'provenance'} or metadata['kind'] != 'AUTHOR_MODEL_INPUTS':
        raise ValueError('Invalid author-model snapshot metadata')
    provenance = metadata['provenance']
    if (not isinstance(provenance, dict) or set(provenance) != {'source_revision', 'environment'}
            or not isinstance(provenance['source_revision'], str)
            or not provenance['source_revision'].startswith('srcsha256:')
            or not _is_hash(provenance['source_revision'][10:])
            or not isinstance(provenance['environment'], dict)
            or set(provenance['environment']) != {'python', 'executable', 'platform', 'processor', 'packages', 'thread_env'}):
        raise ValueError('Invalid author-model execution provenance')
    manifests = {}
    for row in claims.values():
        case = row['metadata']
        keys = {'claim_id', 'author_manifest', 'manifest_sha256', 'manifest_spec', 'model_id',
                'source_file', 'source_sha256', 'data_file', 'data_sha256'}
        spec = case.get('manifest_spec')
        if (not isinstance(spec, dict) or type(spec.get('schema')) is not int or spec['schema'] != 1
                or spec.get('scope') != 'AUTHOR_ANALYSIS_DATASET_ONLY'
                or not isinstance(spec.get('models'), list) or not 1 <= len(spec['models']) <= 10):
            raise ValueError('Invalid author-model manifest binding')
        ids = [m.get('model_id') if isinstance(m, dict) else None for m in spec['models']]
        if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('Invalid snapshot author-model IDs')
        unsupported = (_author_unknown(spec)
                       or bool(set(spec) - {'schema', 'scope', 'source_file', 'source_sha256',
                                            'data_file', 'data_sha256', 'models', 'derivations'}))
        if unsupported:
            keys.add('dependencies')
        if (set(case) != keys or unsupported and case['dependencies'] != 'UNTRACKED_AUTHOR_DEPENDENCY'
                or not _relative(case['author_manifest']) or not _is_hash(case['manifest_sha256'])
                or not isinstance(spec.get('models'), list)
                or any(not isinstance(m, dict) for m in spec['models'])
                or not isinstance(case['model_id'], str) or not case['model_id'].strip()
                or sum(m.get('model_id') == case['model_id'] for m in spec['models']) != 1
                or case['claim_id'] != case['author_manifest'] + '::' + case['model_id']
                or any(case[k] != spec.get(k) for k in ('source_file', 'source_sha256', 'data_file', 'data_sha256'))):
            raise ValueError('Invalid author-model snapshot binding')
        identity = (case['manifest_sha256'], _digest(spec))
        if case['author_manifest'] in manifests and manifests[case['author_manifest']] != identity:
            raise ValueError('Inconsistent author-model manifest identity')
        manifests[case['author_manifest']] = identity
    for manifest in manifests:
        rows = [r['metadata'] for r in claims.values() if r['metadata']['author_manifest'] == manifest]
        if {r['model_id'] for r in rows} != {m.get('model_id') for m in rows[0]['manifest_spec']['models']}:
            raise ValueError('Incomplete author-model snapshot')
    return claims


# [작성: 실행검증 담당] 2026-09-29 case91 / 무엇: 저자명세·원문·자료·실행코드·환경의 결정적 snapshot / 왜: 수치캐시 없이 변경경계 식별 / 입력·출력: 명세목록·root→모형별 입력snapshot / 검증: test_case91_execution 실제4명세·의존성차단.
def snapshot_author_models(manifests, root=None):
    """Bind model inputs and execution identity; no numerical audit is performed."""
    from tools.author_model_audit import benchmark_provenance
    root = Path(ROOT if root is None else root).resolve()
    if not isinstance(manifests, (list, tuple)) or not manifests:
        raise ValueError('Nonempty author manifest list required')
    provenance = benchmark_provenance()
    claims, seen = [], set()
    for name in manifests:
        path = Path(name)
        path = (path if path.is_absolute() else root / path).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 65536:
            raise ValueError('Invalid author manifest location or size')
        relative = path.relative_to(root).as_posix()
        if relative in seen:
            raise ValueError('Duplicate author manifest')
        seen.add(relative)
        raw = path.read_bytes()
        if len(raw) > 65536:
            raise ValueError('Author manifest size exceeded')
        spec = _load_json(raw)
        if (not isinstance(spec, dict) or type(spec.get('schema')) is not int or spec['schema'] != 1
                or spec.get('scope') != 'AUTHOR_ANALYSIS_DATASET_ONLY'
                or not isinstance(spec.get('models'), list) or not 1 <= len(spec['models']) <= 10):
            raise ValueError('Invalid author-model manifest schema')
        ids = [m.get('model_id') if isinstance(m, dict) else None for m in spec['models']]
        if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('Invalid author-model IDs')
        unsupported = (_author_unknown(spec)
                       or bool(set(spec) - {'schema', 'scope', 'source_file', 'source_sha256',
                                            'data_file', 'data_sha256', 'models', 'derivations'}))
        refs = {kind: _reference(spec, kind, root) for kind in ('source', 'data')}
        for mid in ids:
            case = {k: spec.get(k) for k in ('source_file', 'source_sha256', 'data_file', 'data_sha256')}
            case.update(claim_id=relative + '::' + mid, author_manifest=relative,
                        manifest_sha256=hashlib.sha256(raw).hexdigest(), manifest_spec=spec, model_id=mid)
            if unsupported:
                case['dependencies'] = 'UNTRACKED_AUTHOR_DEPENDENCY'
            blocked = unsupported or any(r['status'] != 'CONSISTENT' for r in refs.values())
            claims.append(dict(claim_id=case['claim_id'], metadata=case, metadata_sha256=_digest(case),
                               references=refs, status='BLOCKED_INPUT' if blocked else 'CONSISTENT'))
    metadata = dict(schema=1, kind='AUTHOR_MODEL_INPUTS', provenance=provenance)
    snapshot = dict(schema=1, registry_metadata=metadata, registry_metadata_sha256=_digest(metadata),
                    claims=sorted(claims, key=lambda r: r['claim_id']))
    snapshot['content_sha256'] = _digest(snapshot)
    _validate_author_snapshot(snapshot)
    if benchmark_provenance() != provenance:
        raise ValueError('Code/environment changed while snapshotting')
    return snapshot


# [작성: 실행검증 담당] 2026-09-29 case91 / 무엇: 기존엔진으로 영향모형·차단·명세단위 재실행 계획 / 왜: 무변경·옛보고의 산술성공 승격 방지 / 입력·출력: 이전·현재snapshot·선택명세→영향목록·재실행명세 / 검증: test_case91_execution 필터·코드환경변경·실제재계산.
def compare_author_model_snapshots(previous, current, manifest_filter=None):
    """Plan whole-manifest reruns. Caller must run audit_models for fresh numbers.

    A trusted baseline is required: digest consistency cannot authenticate a
    historical snapshot whose content and every digest were rewritten together.
    """
    old, new = _validate_author_snapshot(previous), _validate_author_snapshot(current)
    available = {r['metadata']['author_manifest'] for r in [*old.values(), *new.values()]}
    if manifest_filter is not None:
        if (not isinstance(manifest_filter, (list, tuple)) or not manifest_filter
                or any(not isinstance(p, str) or p not in available for p in manifest_filter)
                or len(set(manifest_filter)) != len(manifest_filter)):
            raise ValueError('Invalid author manifest filter')
        available = set(manifest_filter)
    plan = compare_snapshots(previous, current)
    before = previous['registry_metadata']['provenance']
    after = current['registry_metadata']['provenance']
    results = []
    for row in plan['results']:
        cid = row['claim_id']; case = (new.get(cid) or old[cid])['metadata']
        if case['author_manifest'] not in available:
            continue
        changed = set(row['changed_inputs']) - {'registry_metadata'}
        changed.update(k for k in ('source_revision', 'environment') if before[k] != after[k])
        reasons = set()
        for record in (old.get(cid), new.get(cid)):
            if record is None:
                continue
            if 'dependencies' in record['metadata']:
                reasons.add('UNTRACKED_AUTHOR_DEPENDENCY')
            reasons.update(kind + ':' + ref['reason'] for kind, ref in record['references'].items()
                           if ref['status'] != 'CONSISTENT')
        results.append(dict(row, manifest=case['author_manifest'], model_id=case['model_id'],
                            changed_inputs=sorted(changed), blocking_reasons=sorted(reasons),
                            rerun_required=row['action'] in {'ADDED', 'REEXECUTION_REQUIRED'}))
    blocked_manifests = {r['manifest'] for r in results if r['action'] == 'BLOCKED_INPUT'}
    plan.update(results=results,
                counts={a: sum(r['action'] == a for r in results) for a in ACTIONS},
                affected_model_ids=[r['claim_id'] for r in results if r['action'] != 'UNCHANGED'],
                rerun_manifests=sorted({r['manifest'] for r in results if r['rerun_required']} - blocked_manifests),
                arithmetic_verified=False, human_approval=False,
                limitations=LIMITATIONS + ' UNCHANGED does not verify current arithmetic. Whole-manifest reruns must execute audit_models; previous reports are not promoted.')
    return plan


# [작성: 전문가4/5] 2026-09-29 case92
# 무엇을: 로컬 명세목록의 선택/전체 재실행 공통 경로 / 왜: UI 고정 논문 없이 같은 안전계약 재사용 / 입력·출력: 이전snapshot·명세·root→새 보고 / 검증: test_case92 합성 b1.2·선택/전체 동일·중간변조.
def execute_author_model_changes(previous, manifests, root=None, *, full=False, execute=True):
    from tools.author_model_audit import audit_models
    root = Path(ROOT if root is None else root).resolve()
    current = snapshot_author_models(manifests, root=root)
    plan = compare_author_model_snapshots(previous, current)
    paths = {r['metadata']['author_manifest'] for r in current['claims']}
    if {r['metadata']['author_manifest'] for r in previous['claims']} != paths:
        raise ValueError('이전 기록과 현재 명세 목록이 다릅니다.')
    blocked = {r['manifest'] for r in plan['results'] if r['action'] == 'BLOCKED_INPUT'}
    selected = sorted(paths - blocked) if full else plan['rerun_manifests']
    selected = selected if execute else []
    reports = [audit_models(root / name, root=root) for name in selected]
    if selected and (current != snapshot_author_models(manifests, root=root)
                     or any(r.get('execution_identity_verified') is not True for r in reports)):
        raise ValueError('재검산 중 입력·코드·환경이 변경되어 계산 결과를 폐기했습니다.')
    return {'current_snapshot':current, 'impact':plan, 'reports':reports,
            'executed_manifests':selected, 'fresh_execution':bool(selected), 'human_approval':False}


# [수정: 전문가4] 2026-09-29 case92
# 종류: 효율화 / 재현 방법: 웹 밖 변경 재실행 필요 / 변경 전: 일반 명세 비교만 / 변경 후: 명시된 저자명세 snapshot·실행 선택 / 왜: 공통 함수 재사용 / 영향: --execute 명시 전 계산 없음; CLI 실행 시험.
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data/evaluation/registered_cases.json')
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--author-manifests', nargs='+', help='Local author-model manifests; defaults to snapshot only')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--execute', action='store_true', help='Execute changed author manifests against --previous')
    parser.add_argument('--full', action='store_true', help='With --execute, rerun all nonblocked author manifests')
    args = parser.parse_args()
    if (args.execute or args.full) and (not args.author_manifests or not args.previous):
        parser.error('--execute/--full require --author-manifests and --previous')
    if args.author_manifests:
        if args.previous:
            with args.previous.open('rb') as handle: raw = handle.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024: parser.error('Previous snapshot exceeds 2MiB')
            result = execute_author_model_changes(_load_json(raw), args.author_manifests, args.root,
                                                  full=args.full, execute=args.execute)
        else:
            result = snapshot_author_models(args.author_manifests, root=args.root)
    else:
        snapshot = snapshot_registry(args.manifest, root=args.root)
        result = (compare_snapshots(_load_json(args.previous.read_bytes()), snapshot)
                  if args.previous else snapshot)
    output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(output, encoding='utf-8')
    else:
        print(output)

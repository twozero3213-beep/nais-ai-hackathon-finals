"""[0 이영] 팀의 비공개 입력 묶음을 사전 봉인 지문과 대조해 로컬에 복원한다."""
# 수정 이유: 원본 비교 입력을 바꾸거나 연락처를 공개하지 않고 팀의 재현 경로를 제공한다.
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def restore(archive, root=ROOT):
    root = Path(root).resolve()
    archive = Path(archive)
    metadata = json.loads((root / 'docs/0_이영_공개범위.json').read_text('utf-8'))
    if archive.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('ARCHIVE_SIZE_LIMIT')
    digest = lambda raw: hashlib.sha256(raw).hexdigest()
    if digest(archive.read_bytes()) != metadata['private_bundle_sha256']:
        raise ValueError('PRIVATE_BUNDLE_HASH_MISMATCH')
    target = (root / 'finals/evidence').resolve()
    seal_raw = (target / 'seal.json').read_bytes()
    seal = json.loads(seal_raw)
    expected = dict(seal['files'])
    expected['seal.json'] = digest(seal_raw)
    ready = []
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError('ARCHIVE_MEMBER_MISMATCH')
        if sum(info.file_size for info in bundle.infolist()) > 64 * 1024 * 1024:
            raise ValueError('EXPANDED_SIZE_LIMIT')
        for name, fingerprint in expected.items():
            destination = (target / name).resolve()
            if not destination.is_relative_to(target):
                raise ValueError('PATH_OUTSIDE_SEALED_INPUTS')
            raw = bundle.read(name)
            if digest(raw) != fingerprint:
                raise ValueError('SEALED_INPUT_HASH_MISMATCH')
            if destination.exists() and digest(destination.read_bytes()) != fingerprint:
                raise ValueError('EXISTING_INPUT_CONFLICT')
            ready.append((destination, raw))
    written = 0
    for destination, raw in ready:
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as handle:
                handle.write(raw)
            written += 1
    return {'status': 'VERIFIED', 'files_verified': len(ready), 'files_restored': written,
            'original_inputs_modified': False}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(restore(args.archive), ensure_ascii=False))
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as exc:
        code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({'status': 'BLOCKED', 'code': code}, ensure_ascii=False))
        raise SystemExit(2)

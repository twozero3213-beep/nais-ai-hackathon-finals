"""Run after extraction; hashes detect changes, not publisher identity."""
import hashlib
import json
from pathlib import Path


# [작성: 복구 운영] 2026-09-29 case95 / 재추출 파일→manifest 대조 / 누락·변조·탈출경로 거부.
def verify(root=None):
    root=Path(root or Path(__file__).resolve().parents[1]).resolve()
    manifest_path=root/'recovery_manifest.json'
    if manifest_path.stat().st_size>8*1024*1024:raise ValueError('Manifest too large')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema')!=1 or not isinstance(manifest.get('files'),dict):raise ValueError('Invalid manifest')
    if len(manifest['files'])>100000:raise ValueError('Too many files')
    for rel,expected in manifest['files'].items():
        path=(root/rel).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('Missing or invalid path: '+rel)
        with path.open('rb') as stream:digest=hashlib.file_digest(stream, 'sha256').hexdigest()
        if path.stat().st_size!=expected['bytes'] or digest!=expected['sha256']:
            raise ValueError('Changed file: '+rel)
    return len(manifest['files'])


if __name__=='__main__':print('Verified files:',verify())

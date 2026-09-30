"""Portable source/data recovery ZIP; secrets and runtime records are excluded."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git','.venv','venv','__pycache__','.pytest_cache','team_data','logs','node_modules'}
PRIVATE = {'.env','secrets.toml','recovery_manifest.json'}
# Public Google Sites HTML contains browser configuration IDs beginning AIza;
# that prefix alone is not proof of a private credential. Preserve source captures.
SECRET = re.compile(rb'(?<![A-Za-z0-9_])(?:github_pat_[A-Za-z0-9_]{30,}|ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{35,}|(?:AKIA|ASIA)[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')


# [작성: 복구 운영] 2026-09-29 case95 / 소스→검증 가능한 ZIP / 변경 중 파일·비밀키 감지 시 완료 파일을 만들지 않는다.
def create_bundle(output, root=ROOT):
    root=Path(root).resolve(); output=Path(output).resolve()
    if output.is_relative_to(root) or output.exists():
        raise ValueError('프로젝트 밖의 새 ZIP 경로를 지정하세요.')
    files={}
    paths=[]
    for base, directories, names in os.walk(root, followlinks=False):
        base=Path(base)
        # Do not traverse private/runtime trees just to discard their contents later.
        directories[:]=sorted(name for name in directories if name not in SKIP
            and not (base/name).is_symlink() and not (base/name).is_junction())
        paths.extend(base/name for name in names)
    for path in sorted(paths):
        rel=path.relative_to(root)
        if path.is_symlink() or not path.is_file():continue
        if path.name.lower() in PRIVATE or path.name.startswith('.env') or path.suffix in {'.db','.sqlite','.sqlite3','.pyc','.zip'} or path.name.endswith(('-wal','-shm')):continue
        raw=path.read_bytes()
        if SECRET.search(raw):raise ValueError('비밀키 패턴 포함 파일: '+rel.as_posix())
        files[rel.as_posix()]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    manifest={'schema':1,
        'version':(root/'VERSION').read_text().strip(),'files':files,
        'scope':'source and public research data; not credentials, private runtime DBs, complete chat history, or installed programs',
        'validation':'snapshot hash/ZIP integrity only; see RELEASE_CHECK.md and external test receipts for executed tests'}
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix(output.suffix+'.partial')
    if temporary.exists():raise ValueError('기존 미완료 ZIP을 확인한 뒤 다른 경로를 사용하세요.')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for rel,expected in files.items():
            raw=(root/rel).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=expected['sha256']:
                raise ValueError('작업 중 파일이 변경됐습니다. 작업을 멈춘 뒤 새 ZIP을 만드세요: '+rel)
            archive.writestr(zipfile.ZipInfo(root.name+'/'+rel),raw,compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
        archive.writestr(zipfile.ZipInfo(root.name+'/recovery_manifest.json'),json.dumps(manifest,ensure_ascii=False,indent=2),compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:raise ValueError('ZIP 무결성 오류')
    temporary.replace(output)
    return {'path':str(output),'files':len(files),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    print(json.dumps(create_bundle(parser.parse_args().output),ensure_ascii=False))

"""[3 조지현] 실행 당시 코드·환경 지문. 승인/과학적 타당성 인증은 아니다."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CODE_FILES = (
    'finals/app.py', 'finals/finals_pipeline.py', 'finals/finals_cases.py',
    'finals/finals_provider.py', 'finals/finals_privacy.py', 'finals/finals_explain.py',
    'finals/finals_provenance.py', 'core/statistics.py', 'core/verifier.py',
    'core/normalization.py', 'core/typed_contracts.py', 'core/models.py',
)


def execution_snapshot() -> dict:
    """절대경로/설정/비밀/문서 본문은 읽거나 내보내지 않는다."""
    files = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE_FILES}
    raw = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        tracked = subprocess.run(['git', 'ls-files', '--error-unmatch', '--', *CODE_FILES], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        clean = tracked and subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *CODE_FILES], cwd=ROOT, stderr=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.CalledProcessError):
        commit, clean = None, None
    versions = {}
    for package in ('streamlit', 'pandas', 'numpy', 'scipy', 'jsonschema'):
        try: versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: versions[package] = 'UNAVAILABLE'
    return {'code_commit': commit, 'tracked_code_matches_commit': clean,
            'code_files_sha256': files, 'execution_fingerprint': hashlib.sha256(raw).hexdigest(),
            'python_version': platform.python_version(), 'dependencies': versions,
            'scope': 'SELECTED_EXECUTION_FILES_AND_ENVIRONMENT_NOT_IDENTITY_OR_DEPLOYMENT_ATTESTATION'}

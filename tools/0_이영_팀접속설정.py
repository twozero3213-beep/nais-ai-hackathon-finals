"""Create ignored team-login secrets from four hidden, interactive passwords."""
# [작성: 0 이영] 2026-09-30 22:52 KST — 기존 인증·RBAC를 재사용하고 평문 비밀번호 저장·기존 비밀설정 덮어쓰기를 방지합니다.
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.rbac import Role
from core.team_workspace import MEMBERS, password_hash

DEFAULT_TARGET = ROOT / ".streamlit" / "secrets.toml"
ROLES = {member: Role.ADMIN.value if member == "이영" else Role.REVIEWER.value for member in MEMBERS}
_HASH_PATTERN = re.compile(r"pbkdf2_sha256\$[a-f0-9]{32}\$[a-f0-9]{64}\Z")


# [작성: 0 이영] 2026-09-30 22:52 KST — 빈값·제어문자·짧거나 단일 종류인 입력을 비밀번호 원문 없이 거부합니다.
def validate_password(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("비밀번호는 비어 있을 수 없습니다.")
    if len(value) < 12 or len(value) > 256:
        raise ValueError("비밀번호는 12~256자로 입력하세요.")
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("앞뒤 공백과 제어문자는 사용할 수 없습니다.")
    categories = sum((any(char.islower() for char in value),
                      any(char.isupper() for char in value),
                      any(char.isdecimal() for char in value),
                      any(not char.isalnum() and not char.isspace() for char in value)))
    if categories < 3:
        raise ValueError("영문 대소문자·숫자·기호 중 3종 이상을 포함하세요.")


# [작성: 0 이영] 2026-09-30 22:52 KST — 네 명이 각각 확인 입력하고 기존 PBKDF2 해시만 보관하며 echo fallback을 차단합니다.
def collect_password_hashes(reader=None) -> dict[str, str]:
    reader = reader or getpass.getpass
    hashes, used = {}, set()
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        for member in MEMBERS:
            while True:
                value = reader(f"{member} 개인 비밀번호: ")
                try:
                    validate_password(value)
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    continue
                confirmation = reader(f"{member} 비밀번호 확인: ")
                if value != confirmation:
                    print("확인 입력이 일치하지 않습니다. 다시 입력하세요.", file=sys.stderr)
                    continue
                fingerprint = hashlib.sha256(value.encode("utf-8")).digest()
                if fingerprint in used:
                    print("팀원마다 서로 다른 비밀번호를 입력하세요.", file=sys.stderr)
                    continue
                hashes[member] = password_hash(value)
                used.add(fingerprint)
                del value, confirmation
                break
    return hashes


# [작성: 0 이영] 2026-09-30 22:52 KST — 승인 가능한 ADMIN은 이영으로 고정하고 나머지는 REVIEWER로 저장합니다.
def render_secrets(hashes: dict[str, str]) -> str:
    if set(hashes) != set(MEMBERS) or any(not _HASH_PATTERN.fullmatch(value) for value in hashes.values()):
        raise ValueError("네 명의 올바른 비밀번호 해시가 필요합니다.")
    # [수정: 0 이영] 2026-09-30 22:57 KST — 생성될 비밀 설정에도 실제 생성 시각을 한국시간으로 남깁니다.
    created = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    lines = [f"# [작성: 0 이영] {created} — 팀 개별 접속 설정. 평문 비밀번호는 저장하지 않습니다.",
             "[team]", 'branch = "team-data"', "", "[team.roles]"]
    lines += [f"{json.dumps(member, ensure_ascii=False)} = {json.dumps(ROLES[member])}" for member in MEMBERS]
    lines += ["", "[team.password_hashes]"]
    lines += [f"{json.dumps(member, ensure_ascii=False)} = {json.dumps(hashes[member])}" for member in MEMBERS]
    return "\n".join(lines) + "\n"


# [작성: 0 이영] 2026-09-30 22:52 KST — 모든 입력 성공 후 배타적으로 새 파일을 생성하여 존재 파일·동시 생성·심볼릭 링크를 덮어쓰지 않습니다.
def create_secrets(target: Path = DEFAULT_TARGET, reader=None) -> Path:
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("기존 비밀 설정은 덮어쓰지 않습니다.")
    content = render_secrets(collect_password_hashes(reader))
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # 방금 생성한 미완성 파일만 정리합니다. 기존 설정은 O_EXCL에서 거부됩니다.
        target.unlink(missing_ok=True)
        raise
    return target


def main() -> int:
    if DEFAULT_TARGET.exists() or DEFAULT_TARGET.is_symlink():
        print("기존 .streamlit/secrets.toml을 보존했습니다. 덮어쓰지 않습니다.", file=sys.stderr)
        return 1
    if not sys.stdin.isatty():
        print("비밀번호는 입력을 숨길 수 있는 사용자 터미널에서만 설정하세요.", file=sys.stderr)
        return 2
    print("네 명의 개별 비밀번호를 숨김 입력합니다. 12~256자, 문자 종류 3종 이상이 필요합니다.")
    try:
        create_secrets(DEFAULT_TARGET)
    except FileExistsError:
        print("설정 파일이 이미 생겨 보존했습니다. 덮어쓰지 않습니다.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError, getpass.GetPassWarning):
        print("숨김 입력을 완료하지 못해 설정 생성을 중단했습니다.", file=sys.stderr)
        return 130
    except (OSError, ValueError):
        print("설정 파일을 만들지 못했습니다. 기존 파일과 쓰기 권한을 확인하세요.", file=sys.stderr)
        return 2
    print(".streamlit/secrets.toml에 해시·역할을 저장했습니다. 평문 비밀번호는 저장하지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

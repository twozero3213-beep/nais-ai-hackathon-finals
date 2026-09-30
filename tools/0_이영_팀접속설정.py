"""Create ignored team-login secrets from four hidden, interactive passwords."""
# [작성: 0 이영] 2026-09-30 22:52 KST — 기존 인증·RBAC를 재사용하고 평문 비밀번호 저장·기존 비밀설정 덮어쓰기를 방지합니다.
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.rbac import Role
from core.team_workspace import MEMBERS, password_hash

DEFAULT_TARGET = ROOT / ".streamlit" / "secrets.toml"
PRIVATE_ROOT = ROOT.parents[1] / "공유 기록" / "비공개"
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


# [작성: 0 이영] 2026-10-01 00:57 KST — 사용자 요청의 자동 생성만 별도 비공개 폴더에 저장한다. 값은 반환·출력하지 않고 기존 설정/키 파일은 읽지 않는다.
def _write_private_file(target: Path, content: str) -> None:
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def generate_access_bundle(private_root: Path = PRIVATE_ROOT, generator=None) -> dict:
    private_root = Path(private_root)
    resolved = private_root.resolve()
    if private_root.is_symlink() or resolved == ROOT or ROOT in resolved.parents:
        raise ValueError("접속 안내는 제품 저장소 밖 비공개 폴더에만 저장하세요.")
    # OS cryptographic randomness; password strength and uniqueness are still checked.
    generator = generator or (lambda: secrets.token_urlsafe(24))
    passwords, used = {}, set()
    for member in MEMBERS:
        for _ in range(128):
            value = generator()
            try:
                validate_password(value)
            except ValueError:
                continue
            if value in used:
                continue
            passwords[member] = value
            used.add(value)
            break
        else:
            raise ValueError("강한 개별 암호 생성에 실패했습니다.")
    config = render_secrets({member: password_hash(value) for member, value in passwords.items()})
    created = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d_%H%M%S")
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = private_root / ("0_이영_팀접속_" + created + "_" + secrets.token_hex(6))
    folder.mkdir(mode=0o700, exist_ok=False)
    created_files = []
    try:
        config_path = folder / "0_이영_Cloud설정.toml"
        _write_private_file(config_path, config)
        created_files.append(config_path)
        instructions = []
        for member in MEMBERS:
            path = folder / ("0_이영_" + member + "_개인접속안내.txt")
            content = ("비공개 개인 접속 안내 — 팀원에게 직접 전달하세요.\n"
                       "팀원: " + member + "\n개인 접속 암호: " + passwords[member] + "\n"
                       "공개 채팅·로그·Git에 복사하지 마세요. Cloud 설정은 해시 파일만 사용합니다.\n"
                       "팀 저장·수정·검토 권한은 유지하며 최종 승인 권한은 이영에게 있습니다.\n")
            _write_private_file(path, content)
            created_files.append(path)
            instructions.append(path)
    except BaseException:
        # Remove only our newly created files, never existing configuration or external data.
        for path in created_files:
            path.unlink(missing_ok=True)
        folder.rmdir()
        raise
    finally:
        passwords.clear()
        used.clear()
    return {"configuration": config_path, "member_instructions": instructions}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="개별 팀 접속 설정을 비공개로 준비합니다.")
    parser.add_argument("--generate", action="store_true", help="암호를 자동 생성하고 비공개 파일 경로만 출력")
    options = parser.parse_args(argv or [])
    if options.generate:
        try:
            bundle = generate_access_bundle(PRIVATE_ROOT)
        except (OSError, ValueError):
            print("비공개 설정 생성에 실패했습니다. 기존 파일은 덮어쓰지 않습니다.", file=sys.stderr)
            return 2
        print(str(bundle["configuration"]))
        for path in bundle["member_instructions"]:
            print(str(path))
        return 0
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
    raise SystemExit(main(sys.argv[1:]))

"""Role-based authorization for Evidence Gate.

case73 SECURITY / DCL NOTE
SQLite has no server-side GRANT/REVOKE model. Evidence Gate therefore enforces
least privilege at the application boundary and persists role assignments in the
normalized schema. UI visibility is never treated as authorization: callers must
check ``can()`` before a privileged state transition.
"""
from enum import Enum

class Role(str, Enum):
    VIEWER='VIEWER'; ANALYST='ANALYST'; REVIEWER='REVIEWER'; APPROVER='APPROVER'; ADMIN='ADMIN'

PERMISSIONS={
    Role.VIEWER:{'read'},
    Role.ANALYST:{'read','analyze','propose'},
    Role.REVIEWER:{'read','analyze','propose','review'},
    Role.APPROVER:{'read','review','approve'},
    Role.ADMIN:{'read','analyze','propose','review','approve','admin'},
}

# [수정: 0 이영] 2026-10-01 03:03 KST — Role Enum을 문자열화해 VIEWER를 REVIEWER로 승격/ADMIN을 강등하던 오류를 막는다. 미정의·비문자 역할은 거부하며 안전한 고정 오류만 반환한다.
def normalize_role(value):
    if isinstance(value, Role):
        return value
    if not isinstance(value, str):
        raise ValueError('Unknown role')
    try:
        return Role(value.strip().upper())
    except ValueError:
        raise ValueError('Unknown role') from None


def can(role, permission):
    if not isinstance(permission, str):
        return False
    try:
        return permission in PERMISSIONS[normalize_role(role)]
    except ValueError:
        return False

def require_permission(role, permission):
    if not can(role,permission):
        # [수정: 0 이영] 2026-10-01 03:03 KST — 잘못된 역할의 권한 실패도 PermissionError로 통일하고 caller 원값은 오류에 반사하지 않는다.
        try:
            label = normalize_role(role).value
        except ValueError:
            label = 'UNKNOWN'
        raise PermissionError(f'{label} role cannot {permission}')

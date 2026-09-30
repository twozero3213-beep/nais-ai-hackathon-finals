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

def normalize_role(value):
    try:return Role(str(value).upper())
    except ValueError:return Role.REVIEWER

def can(role, permission): return permission in PERMISSIONS[normalize_role(role)]

def require_permission(role, permission):
    if not can(role,permission):
        raise PermissionError(f'{normalize_role(role).value} role cannot {permission}')

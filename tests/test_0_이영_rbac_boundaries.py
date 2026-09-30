"""RBAC role representations must preserve privileges and reject unknown roles."""
# [작성: 0 이영] 2026-10-01 03:03 KST — 잘못된 역할/Enum에 대한 재현을 권한 전부와 정상 문자열/승인 흐름으로 검증한다. 인증 설정·비밀번호·외부 전송을 사용하지 않는다.
import pytest

from core.rbac import Role, can, normalize_role, require_permission


EXPECTED = {
    Role.VIEWER: {'read'},
    Role.ANALYST: {'read', 'analyze', 'propose'},
    Role.REVIEWER: {'read', 'analyze', 'propose', 'review'},
    Role.APPROVER: {'read', 'review', 'approve'},
    Role.ADMIN: {'read', 'analyze', 'propose', 'review', 'approve', 'admin'},
}
PERMISSIONS = ('read', 'analyze', 'propose', 'review', 'approve', 'admin')


@pytest.mark.parametrize('role', list(Role))
@pytest.mark.parametrize('representation', ['enum', 'upper', 'lower', 'padded'])
@pytest.mark.parametrize('permission', PERMISSIONS)
def test_valid_roles_preserve_exact_permission_matrix(role, representation, permission):
    forms = {'enum': role, 'upper': role.value, 'lower': role.value.lower(),
             'padded': ' ' + role.value + ' '}
    supplied = forms[representation]
    assert normalize_role(supplied) is role
    assert can(supplied, permission) is (permission in EXPECTED[role])
    if permission in EXPECTED[role]:
        assert require_permission(supplied, permission) is None
    else:
        with pytest.raises(PermissionError):
            require_permission(supplied, permission)


class FakeAdmin:
    def __str__(self):
        return 'ADMIN'


@pytest.mark.parametrize('role', [None, '', 'UNKNOWN', 'Role.ADMIN', 'OWNER', 0, True,
                                 [], {}, FakeAdmin()])
@pytest.mark.parametrize('permission', PERMISSIONS)
def test_unknown_or_nonstring_role_never_inherits_any_permission(role, permission):
    with pytest.raises(ValueError, match='Unknown role'):
        normalize_role(role)
    assert can(role, permission) is False
    with pytest.raises(PermissionError, match='UNKNOWN role cannot'):
        require_permission(role, permission)


@pytest.mark.parametrize('permission', [None, '', 'destroy', [], {}, True])
def test_unknown_permissions_are_denied_even_for_admin(permission):
    assert can(Role.ADMIN, permission) is False
    with pytest.raises(PermissionError):
        require_permission(Role.ADMIN, permission)


def test_unknown_role_is_not_echoed_in_error():
    supplied = 'synthetic-private-role-setting'
    with pytest.raises(PermissionError) as failure:
        require_permission(supplied, 'approve')
    assert supplied not in str(failure.value)


def test_viewer_enum_is_read_only_and_admin_enum_can_approve():
    assert can(Role.VIEWER, 'read')
    assert not can(Role.VIEWER, 'review') and not can(Role.VIEWER, 'propose')
    assert require_permission(Role.ADMIN, 'approve') is None

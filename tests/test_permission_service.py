"""Unit tests for community permission_service."""
import pytest
from services.permission_service import (
    DEFAULT_PERMISSIONS,
    VALID_ROLES,
    VALID_PERMISSIONS,
    PermissionServiceError,
    get_default_permissions,
    normalize_permissions,
    can_edit,
    can_chat,
    can_use_terminal,
    can_invite,
    can_kick,
    can_manage_files,
    is_role_at_least,
    validate_role,
)


class TestDefaultPermissions:
    def test_host_has_all_permissions(self):
        perms = DEFAULT_PERMISSIONS['host']
        for key in VALID_PERMISSIONS:
            assert perms[key] is True, f'host should have {key}=True'

    def test_observer_cannot_edit(self):
        perms = DEFAULT_PERMISSIONS['observer']
        assert perms['edit'] is False
        assert perms['chat'] is True  # observers can still chat
        assert perms['invite'] is False

    def test_collaborator_can_edit_and_chat(self):
        perms = DEFAULT_PERMISSIONS['collaborator']
        assert perms['edit'] is True
        assert perms['chat'] is True
        assert perms['terminal'] is False


class TestGetDefaultPermissions:
    def test_returns_copy_not_reference(self):
        a = get_default_permissions('host')
        b = get_default_permissions('host')
        assert a == b
        assert a is not b  # different objects

    def test_raises_on_invalid_role(self):
        with pytest.raises(PermissionServiceError):
            get_default_permissions('admin')


class TestNormalizePermissions:
    def test_merges_overrides(self):
        result = normalize_permissions({'edit': False, 'chat': True}, 'host')
        assert result['edit'] is False  # overridden
        assert result['chat'] is True
        assert result['terminal'] is True  # host default preserved

    def test_ignores_unknown_keys(self):
        result = normalize_permissions({'unknown': True}, 'observer')
        assert 'unknown' not in result
        assert result['edit'] is False  # observer default

    def test_returns_full_matrix(self):
        result = normalize_permissions(None, 'collaborator')
        assert set(result.keys()) == set(VALID_PERMISSIONS)


class TestCanFunctions:
    def test_can_edit_host(self):
        assert can_edit(DEFAULT_PERMISSIONS['host']) is True

    def test_cannot_edit_observer(self):
        assert can_edit(DEFAULT_PERMISSIONS['observer']) is False

    def test_can_chat_all_roles(self):
        for role in VALID_ROLES:
            assert can_chat(DEFAULT_PERMISSIONS[role]) is True, f'{role} should be able to chat'

    def test_can_kick_only_host(self):
        assert can_kick(DEFAULT_PERMISSIONS['host']) is True
        assert can_kick(DEFAULT_PERMISSIONS['collaborator']) is False
        assert can_kick(DEFAULT_PERMISSIONS['observer']) is False

    def test_missing_key_defaults_false(self):
        assert can_edit({}) is False
        assert can_chat({}) is False  # empty perms means no permissions
        assert can_use_terminal({}) is False
        assert can_invite({}) is False
        assert can_kick({}) is False
        assert can_manage_files({}) is False


class TestIsRoleAtLeast:
    def test_host_above_all(self):
        assert is_role_at_least('host', 'host') is True
        assert is_role_at_least('host', 'collaborator') is True
        assert is_role_at_least('host', 'observer') is True

    def test_collaborator_above_observer(self):
        assert is_role_at_least('collaborator', 'host') is False
        assert is_role_at_least('collaborator', 'collaborator') is True
        assert is_role_at_least('collaborator', 'observer') is True

    def test_observer_bottom(self):
        assert is_role_at_least('observer', 'host') is False
        assert is_role_at_least('observer', 'collaborator') is False
        assert is_role_at_least('observer', 'observer') is True

    def test_unknown_role_returns_false(self):
        assert is_role_at_least('nobody', 'observer') is False


class TestValidateRole:
    def test_valid_roles_pass(self):
        for role in VALID_ROLES:
            validate_role(role)  # should not raise

    def test_invalid_role_raises(self):
        with pytest.raises(PermissionServiceError):
            validate_role('superadmin')


class TestConstants:
    def test_three_roles(self):
        assert VALID_ROLES == frozenset({'host', 'collaborator', 'observer'})

    def test_six_permission_keys(self):
        assert VALID_PERMISSIONS == frozenset({
            'edit', 'chat', 'terminal', 'invite', 'kick', 'manageFiles',
        })

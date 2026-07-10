"""Permission and role management for community collaboration rooms."""
from typing import Dict, Any


class PermissionServiceError(Exception):
    pass


# Mirrors frontend DEFAULT_PERMISSIONS in types/index.ts
DEFAULT_PERMISSIONS: Dict[str, Dict[str, bool]] = {
    'host': {
        'edit': True,
        'chat': True,
        'terminal': True,
        'invite': True,
        'kick': True,
        'manageFiles': True,
    },
    'collaborator': {
        'edit': True,
        'chat': True,
        'terminal': False,
        'invite': False,
        'kick': False,
        'manageFiles': False,
    },
    'observer': {
        'edit': False,
        'chat': True,
        'terminal': False,
        'invite': False,
        'kick': False,
        'manageFiles': False,
    },
}

VALID_ROLES = frozenset(DEFAULT_PERMISSIONS.keys())
VALID_PERMISSIONS = frozenset(next(iter(DEFAULT_PERMISSIONS.values())).keys())


def get_default_permissions(role: str) -> Dict[str, bool]:
    """Return the default permission matrix for a role."""
    if role not in VALID_ROLES:
        raise PermissionServiceError(f'invalid role: {role}')
    return dict(DEFAULT_PERMISSIONS[role])


def normalize_permissions(permissions: Dict[str, bool], role: str) -> Dict[str, bool]:
    """Merge provided permissions over the role defaults."""
    base = get_default_permissions(role)
    if permissions:
        for key, value in permissions.items():
            if key in VALID_PERMISSIONS:
                base[key] = bool(value)
    return base


def can_edit(permissions: Dict[str, bool]) -> bool:
    return bool(permissions.get('edit', False))


def can_chat(permissions: Dict[str, bool]) -> bool:
    return bool(permissions.get('chat', False))


def can_use_terminal(permissions: Dict[str, bool]) -> bool:
    return bool(permissions.get('terminal', False))


def can_invite(permissions: Dict[str, bool]) -> bool:
    return bool(permissions.get('invite', False))


def can_kick(permissions: Dict[str, bool]) -> bool:
    return bool(permissions.get('kick', False))


def can_manage_files(permissions: Dict[str, bool]) -> bool:
    return bool(permissions.get('manageFiles', False))


def is_role_at_least(role: str, minimum: str) -> bool:
    """Check if role has privileges at least as high as minimum.

    Privilege order: host > collaborator > observer
    """
    order = {'observer': 0, 'collaborator': 1, 'host': 2}
    return order.get(role, -1) >= order.get(minimum, -1)


def validate_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise PermissionServiceError(f'invalid role: {role}')

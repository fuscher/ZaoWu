"""Room lifecycle and persistence service for community collaboration."""
import os
import json
import uuid
import random
import string
import threading
import socket
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple

from .permission_service import (
    DEFAULT_PERMISSIONS,
    normalize_permissions,
    validate_role,
    VALID_ROLES,
    PermissionServiceError,
)


class RoomServiceError(Exception):
    pass


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOMS_FILE = os.path.join(BASE_DIR, 'community_rooms.json')
DATA_DIR = os.path.join(BASE_DIR, 'data', 'collaboration')
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')

ABSOLUTE_MAX_USERS = 10
INVITE_CODE_LENGTH = 6

_room_lock = threading.RLock()


def _read_settings() -> Dict[str, Any]:
    defaults = {
        'communityMaxUsers': 5,
        'communityDefaultRole': 'collaborator',
        'communityFileSizeLimitKB': 512,
        'communityInactiveTimeoutMinutes': 120,
    }
    if not os.path.exists(SETTINGS_FILE):
        return defaults
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        for key, val in defaults.items():
            if key not in saved:
                saved[key] = val
        return saved
    except (json.JSONDecodeError, IOError):
        return defaults


def _default_max_users() -> int:
    return min(max(1, int(_read_settings().get('communityMaxUsers', 5))), ABSOLUTE_MAX_USERS)


def _default_role() -> str:
    role = _read_settings().get('communityDefaultRole', 'collaborator')
    if role not in VALID_ROLES:
        role = 'collaborator'
    return role


def _room_inactive_timeout_minutes() -> int:
    return max(10, int(_read_settings().get('communityInactiveTimeoutMinutes', 120)))


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_rooms() -> Dict[str, Any]:
    if not os.path.exists(ROOMS_FILE):
        return {'rooms': []}
    try:
        with open(ROOMS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {'rooms': []}


def _write_rooms(data: Dict[str, Any]) -> None:
    _ensure_data_dir()
    with _room_lock:
        tmp = ROOMS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ROOMS_FILE)


def _generate_invite_code(length: int = INVITE_CODE_LENGTH) -> str:
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def _generate_token() -> str:
    return uuid.uuid4().hex


def _get_local_ip() -> str:
    """Best-effort local IP detection for LAN collaboration."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return '127.0.0.1'


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _new_room(
    name: str,
    project_id: str,
    host_id: str,
    host_address: Optional[str],
    max_users: Optional[int] = None,
    default_role: Optional[str] = None,
) -> Dict[str, Any]:
    if default_role is None:
        default_role = _default_role()
    validate_role(default_role)
    if max_users is None:
        max_users = _default_max_users()
    max_users = min(max(1, max_users), ABSOLUTE_MAX_USERS)
    if not host_address:
        host_address = f'{_get_local_ip()}:5000'
    now = _now_ms()
    return {
        'id': str(uuid.uuid4()),
        'name': name,
        'project_id': project_id,
        'host_id': host_id,
        'host_address': host_address,
        'status': 'active',
        'invite_code': _generate_invite_code(),
        'max_users': max_users,
        'default_role': default_role,
        'created_at': now,
        'updated_at': now,
    }


def list_rooms(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List rooms, optionally filtered by status.

    When status is omitted, only returns active rooms.
    Pass status=None to get all rooms (including closed).
    """
    data = _read_rooms()
    rooms = data.get('rooms', [])
    if status is None:
        rooms = [r for r in rooms if r.get('status') == 'active']
    elif status != 'all':
        rooms = [r for r in rooms if r.get('status') == status]
    return rooms


def get_room(room_id: str) -> Optional[Dict[str, Any]]:
    data = _read_rooms()
    return next((r for r in data.get('rooms', []) if r['id'] == room_id), None)


def create_room(
    name: str,
    project_id: str,
    host_id: str,
    host_address: Optional[str] = None,
    max_users: Optional[int] = None,
    default_role: Optional[str] = None,
) -> Dict[str, Any]:
    room = _new_room(name, project_id, host_id, host_address, max_users, default_role)
    data = _read_rooms()
    data['rooms'].append(room)
    _write_rooms(data)
    return room


def update_room(room_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    data = _read_rooms()
    room = next((r for r in data.get('rooms', []) if r['id'] == room_id), None)
    if not room:
        raise RoomServiceError('room not found')

    if 'name' in patch:
        room['name'] = str(patch['name'])
    if 'maxUsers' in patch:
        max_users = min(max(1, int(patch['maxUsers'])), ABSOLUTE_MAX_USERS)
        room['max_users'] = max_users
    if 'defaultRole' in patch:
        validate_role(patch['defaultRole'])
        room['default_role'] = patch['defaultRole']

    room['updated_at'] = _now_ms()
    _write_rooms(data)
    return room


def close_room(room_id: str) -> None:
    data = _read_rooms()
    room = next((r for r in data.get('rooms', []) if r['id'] == room_id), None)
    if not room:
        raise RoomServiceError('room not found')
    room['status'] = 'closed'
    room['updated_at'] = _now_ms()
    _write_rooms(data)

    # Trigger community_ws cleanup callback (search registration, etc.)
    try:
        from community_ws import _room_close_callbacks
        if cb := _room_close_callbacks.pop(room_id, None):
            cb()
    except Exception:
        pass


def refresh_room_activity(room_id: str) -> None:
    data = _read_rooms()
    room = next((r for r in data.get('rooms', []) if r['id'] == room_id), None)
    if room:
        room['updated_at'] = _now_ms()
        _write_rooms(data)


def generate_invite_code(room_id: str) -> str:
    data = _read_rooms()
    room = next((r for r in data.get('rooms', []) if r['id'] == room_id), None)
    if not room:
        raise RoomServiceError('room not found')
    room['invite_code'] = _generate_invite_code()
    room['updated_at'] = _now_ms()
    _write_rooms(data)
    return room['invite_code']


# In-memory user/session state (temporary, not persisted across restarts)
_users_by_room: Dict[str, Dict[str, Dict[str, Any]]] = {}
_sessions: Dict[str, Dict[str, Any]] = {}
_host_user_map: Dict[str, str] = {}  # room_id -> host user UUID (created by routes/community.py)


def _get_room_users(room_id: str) -> Dict[str, Dict[str, Any]]:
    if room_id not in _users_by_room:
        _users_by_room[room_id] = {}
    return _users_by_room[room_id]


def _assign_user_color() -> str:
    colors = [
        '#ef4444', '#f97316', '#f59e0b', '#84cc16',
        '#10b981', '#06b6d4', '#3b82f6', '#8b5cf6',
        '#d946ef', '#f43f5e',
    ]
    return random.choice(colors)


def join_room(
    room_id: str,
    invite_code: str,
    user_name: str,
) -> Tuple[Dict[str, Any], str]:
    room = get_room(room_id)
    if not room:
        raise RoomServiceError('room not found')
    if room['status'] != 'active':
        raise RoomServiceError('room is not active')
    if room['invite_code'] != invite_code.upper():
        raise RoomServiceError('invalid invite code')

    users = _get_room_users(room_id)
    if len(users) >= room['max_users']:
        raise RoomServiceError('room is full')

    user_id = str(uuid.uuid4())
    role = room['default_role']
    user = {
        'id': user_id,
        'name': user_name or f'User {len(users) + 1}',
        'color': _assign_user_color(),
        'role': role,
        'status': 'online',
        'permissions': normalize_permissions(None, role),
    }
    users[user_id] = user

    token = _generate_token()
    _sessions[token] = {
        'room_id': room_id,
        'user_id': user_id,
        'created_at': _now_ms(),
    }

    refresh_room_activity(room_id)
    return user, token


def leave_room(room_id: str, user_id: str) -> None:
    """Handle a user leaving a room.

    If the leaving user is the host, the room is closed and all users are
    removed — the host's departure ends the session for everyone. Otherwise
    the user is simply marked offline.
    """
    room = get_room(room_id)

    # Check if the leaver is the host — match by host_id (machine UUID) or
    # by the _host_user_map entry (routes/community.py records which user
    # UUID belongs to the host of each room).
    is_host = False
    if room:
        if room.get('host_id') == user_id:
            is_host = True
        if _host_user_map.get(room_id) == user_id:
            is_host = True

    if is_host:
        # Host left — close the room and evict everyone
        users = _get_room_users(room_id)
        expired_sessions = [
            t for t, s in _sessions.items() if s['room_id'] == room_id
        ]
        for token in expired_sessions:
            _sessions.pop(token, None)
        users.clear()
        _host_user_map.pop(room_id, None)
        close_room(room_id)
        return

    # Regular user — mark offline, keep session for potential reconnection
    users = _get_room_users(room_id)
    if user_id in users:
        users[user_id]['status'] = 'offline'

    expired = [t for t, s in _sessions.items() if s['room_id'] == room_id and s['user_id'] == user_id]
    for token in expired:
        _sessions.pop(token, None)


def remove_user(room_id: str, user_id: str) -> None:
    users = _get_room_users(room_id)
    if user_id in users:
        del users[user_id]
    expired = [t for t, s in _sessions.items() if s['room_id'] == room_id and s['user_id'] == user_id]
    for token in expired:
        _sessions.pop(token, None)


def get_room_users(room_id: str) -> List[Dict[str, Any]]:
    return list(_get_room_users(room_id).values())


def get_user(room_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    return _get_room_users(room_id).get(user_id)


def update_user(
    room_id: str,
    user_id: str,
    role: Optional[str] = None,
    permissions: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    users = _get_room_users(room_id)
    user = users.get(user_id)
    if not user:
        raise RoomServiceError('user not found')
    if role is not None:
        validate_role(role)
        user['role'] = role
        user['permissions'] = normalize_permissions(permissions, role)
    elif permissions is not None:
        user['permissions'] = normalize_permissions(permissions, user['role'])
    return user


def validate_token(token: str) -> Optional[Dict[str, Any]]:
    return _sessions.get(token)


def set_user_status(room_id: str, user_id: str, status: str) -> None:
    user = get_user(room_id, user_id)
    if user:
        user['status'] = status


def cleanup_inactive_rooms() -> int:
    """Close rooms that have been inactive beyond the timeout threshold."""
    data = _read_rooms()
    now = _now_ms()
    timeout_ms = _room_inactive_timeout_minutes() * 60 * 1000
    closed = 0
    for room in data.get('rooms', []):
        if room['status'] == 'active' and now - room.get('updated_at', 0) > timeout_ms:
            room['status'] = 'closed'
            room['updated_at'] = now
            closed += 1
    if closed:
        _write_rooms(data)
    return closed

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
from zaowu_paths import get_project_root


class RoomServiceError(Exception):
    pass


BASE_DIR = get_project_root()
ROOMS_FILE = os.path.join(BASE_DIR, 'community_rooms.json')
DATA_DIR = os.path.join(BASE_DIR, 'data', 'collaboration')
USERS_FILE = os.path.join(DATA_DIR, 'community_users.json')
SESSIONS_FILE = os.path.join(DATA_DIR, 'community_sessions.json')
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')

ABSOLUTE_MAX_USERS = 10
INVITE_CODE_LENGTH = 6

# Token 有效期（2 小时）
TOKEN_TTL_MS = 2 * 60 * 60 * 1000

# 邀请码安全字符集：排除 0/O/1/I/5/S/L 等易混淆字符
_SAFE_CHARS = 'ABCDEFGHJKMNPQRTUVWXYZ2346789'

# 同一房间每分钟最多允许 5 次错误邀请码尝试
MAX_FAILURES_PER_MINUTE = 5

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


def _read_json_file(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _write_json_file(path: str, data: Dict[str, Any]) -> None:
    _ensure_data_dir()
    with _room_lock:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def _persist_users() -> None:
    """Persist in-memory users to disk."""
    _write_json_file(USERS_FILE, _users_by_room)


def _persist_sessions() -> None:
    """Persist in-memory sessions to disk."""
    _write_json_file(SESSIONS_FILE, _sessions)


def _load_persisted_state() -> None:
    """Load users/sessions from disk on startup and prune stale data.

    Users are loaded as ``offline`` because no WebSocket connection is active
    yet. Expired sessions are dropped immediately.
    """
    global _users_by_room, _sessions

    now = _now_ms()

    raw_users = _read_json_file(USERS_FILE)
    loaded_users: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for room_id, users in raw_users.items():
        if not isinstance(users, dict):
            continue
        loaded_users[room_id] = {}
        for user_id, user in users.items():
            if isinstance(user, dict):
                user = dict(user)
                user['status'] = 'offline'
                loaded_users[room_id][user_id] = user
    _users_by_room = loaded_users

    raw_sessions = _read_json_file(SESSIONS_FILE)
    loaded_sessions: Dict[str, Dict[str, Any]] = {}
    for token, session in raw_sessions.items():
        if not isinstance(session, dict):
            continue
        # Drop expired tokens
        if now - session.get('created_at', 0) > TOKEN_TTL_MS:
            continue
        # Only keep sessions whose room still exists and user was loaded
        room_id = session.get('room_id', '')
        user_id = session.get('user_id', '')
        if room_id in _users_by_room and user_id in _users_by_room[room_id]:
            loaded_sessions[token] = session
    _sessions = loaded_sessions

    _migrate_host_user_ids()
    _persist_users()
    _persist_sessions()


def _migrate_host_user_ids() -> None:
    """Backfill host_user_id for rooms created before that field existed.

    Uses the persisted user list to find the host user of each active room.
    """
    data = _read_rooms()
    changed = False
    for room in data.get('rooms', []):
        if room.get('status') != 'active' or room.get('host_user_id'):
            continue
        users = _users_by_room.get(room['id'], {})
        host_user = next((u for u in users.values() if u.get('role') == 'host'), None)
        if host_user:
            room['host_user_id'] = host_user['id']
            changed = True
    if changed:
        _write_rooms(data)


def _generate_invite_code(length: int = INVITE_CODE_LENGTH) -> str:
    return ''.join(random.choice(_SAFE_CHARS) for _ in range(length))


def _generate_token() -> str:
    return uuid.uuid4().hex


def _get_local_ip() -> str:
    """Best-effort local IP detection for LAN collaboration.

    使用国内可达的地址探测本机 IP（114.114.114.114 是国内公共 DNS，
    在中国大陆网络下稳定可达，替代了原 8.8.8.8 在国内受限的问题）。
    """
    # 国内公共 DNS 地址列表（按优先级）
    _probe_targets = [
        ('114.114.114.114', 53),   # 国内公共 DNS，最稳定
        ('223.5.5.5', 53),         # 阿里 DNS
        ('8.8.8.8', 80),           # Google DNS（国际回退）
    ]
    for addr, port in _probe_targets:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect((addr, port))
                return s.getsockname()[0]
            finally:
                s.close()
        except Exception:
            continue
    # 所有探测目标均失败 → 回退到 hostname 解析
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
        'host_user_id': '',  # set when the host actually joins the room
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


def set_room_host_user_id(room_id: str, host_user_id: str) -> Dict[str, Any]:
    """Persist the in-room user UUID of the host after they join.

    This eliminates the need for the runtime-only ``_host_user_map``.
    """
    data = _read_rooms()
    room = next((r for r in data.get('rooms', []) if r['id'] == room_id), None)
    if not room:
        raise RoomServiceError('room not found')
    room['host_user_id'] = host_user_id
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
_join_failures: Dict[str, List[int]] = {}  # room_id -> list of failed attempt timestamps


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

    # 邀请码暴力穷举防护
    now = _now_ms()
    failures = _join_failures.get(room_id, [])
    failures = [t for t in failures if now - t < 60_000]
    if len(failures) >= MAX_FAILURES_PER_MINUTE:
        raise RoomServiceError('too many attempts, please wait')

    if room['invite_code'] != invite_code.upper():
        failures.append(now)
        _join_failures[room_id] = failures
        raise RoomServiceError('invalid invite code')

    # 成功匹配后清除失败记录
    _join_failures.pop(room_id, None)

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
    _persist_users()
    _persist_sessions()
    return user, token


def leave_room(room_id: str, user_id: str) -> None:
    """Handle a user leaving a room.

    If the leaving user is the host, the room is closed and all users are
    removed — the host's departure ends the session for everyone. Otherwise
    the user is simply marked offline.
    """
    room = get_room(room_id)

    # Check if the leaver is the host.
    # Prefer the persisted host_user_id; fall back to legacy checks for
    # rooms created before this field existed.
    is_host_user = False
    if room:
        host_user_id = room.get('host_user_id')
        if host_user_id:
            is_host_user = host_user_id == user_id
        elif room.get('host_id') == user_id:
            is_host_user = True
        elif _host_user_map.get(room_id) == user_id:
            is_host_user = True

    if is_host_user:
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
        _persist_users()
        _persist_sessions()
        return

    # Regular user — mark offline, keep session for potential reconnection
    users = _get_room_users(room_id)
    if user_id in users:
        users[user_id]['status'] = 'offline'

    expired = [t for t, s in _sessions.items() if s['room_id'] == room_id and s['user_id'] == user_id]
    for token in expired:
        _sessions.pop(token, None)

    _persist_users()
    _persist_sessions()


def remove_user(room_id: str, user_id: str) -> None:
    users = _get_room_users(room_id)
    if user_id in users:
        del users[user_id]
    expired = [t for t, s in _sessions.items() if s['room_id'] == room_id and s['user_id'] == user_id]
    for token in expired:
        _sessions.pop(token, None)
    _persist_users()
    _persist_sessions()


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
    session = _sessions.get(token)
    if not session:
        return None
    if _now_ms() - session.get('created_at', 0) > TOKEN_TTL_MS:
        _sessions.pop(token, None)
        _persist_sessions()
        return None
    return session


def set_user_status(room_id: str, user_id: str, status: str) -> None:
    user = get_user(room_id, user_id)
    if user:
        user['status'] = status


def is_host(room_id: str, user_id: str) -> bool:
    """Check whether ``user_id`` is the host of the room.

    The canonical source is the persisted ``host_user_id`` field on the room.
    For rooms created before that field existed, we fall back to the runtime
    ``_host_user_map`` or the legacy machine-UUID comparison.
    """
    room = get_room(room_id)
    if not room:
        return False
    host_user_id = room.get('host_user_id')
    if host_user_id:
        return host_user_id == user_id
    if room.get('host_id') == user_id:
        return True
    return _host_user_map.get(room_id) == user_id


def lookup_room_by_invite_code(invite_code: str) -> Optional[Dict[str, Any]]:
    """Find an active room by its invite code (case-insensitive)."""
    code = invite_code.strip().upper()
    if not code:
        return None
    for room in list_rooms():
        if room.get('invite_code', '').upper() == code:
            return room
    return None


def cleanup_inactive_rooms() -> int:
    """Close rooms that have been inactive beyond the timeout threshold.

    Also removes expired sessions/tokens to prevent stale credentials.
    """
    data = _read_rooms()
    now = _now_ms()
    timeout_ms = _room_inactive_timeout_minutes() * 60 * 1000
    closed = 0
    closed_room_ids: List[str] = []
    for room in data.get('rooms', []):
        if room['status'] == 'active' and now - room.get('updated_at', 0) > timeout_ms:
            room['status'] = 'closed'
            room['updated_at'] = now
            closed_room_ids.append(room['id'])
            closed += 1

    if closed:
        _write_rooms(data)

    # 清理过期 token：与已关闭房间关联，或超过 TOKEN_TTL_MS 的独立会话
    expired_tokens = [
        t for t, s in _sessions.items()
        if s.get('room_id') in closed_room_ids or now - s.get('created_at', 0) > TOKEN_TTL_MS
    ]
    for token in expired_tokens:
        _sessions.pop(token, None)

    if expired_tokens:
        _persist_sessions()

    return closed

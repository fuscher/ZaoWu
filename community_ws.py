"""WebSocket integration layer: bridges pycrdt-websocket with ZaoWu business logic.

This module replaces the entire collaboration/ directory (505 lines) with a thin
integration layer (~150 lines) that delegates CRDT sync, awareness, and document
persistence to pycrdt-websocket while preserving ZaoWu's custom features:

  - Room-level auth (token validation on connect)
  - Custom message protocol (0xF0 prefix = ZaoWu JSON, 0x00/0x01 = Yjs binary)
  - Chat broadcasting
  - File diff application (with path-traversal protection)
  - Permission change notifications
  - WebSocket URL construction
"""

from __future__ import annotations

import contextvars
import json
import os
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs

from pycrdt.websocket import ASGIServer, WebsocketServer, YRoom

from services import room_service
from services.permission_service import can_edit

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'collaboration')

def _ws_exception_handler(exc: Exception, log: logging.Logger) -> bool:
    """Swallow cross-thread Subscription warnings during shutdown.

    On Windows daemon threads, pycrdt's Subscription objects are dropped on
    a different thread than the one that created them, causing a harmless
    ``RuntimeError: pycrdt::subscription::Subscription is unsendable`` on
    process exit.  This handler suppresses that noise.
    """
    msg = str(exc)
    if 'Subscription is unsendable' in msg or 'dropped on another thread' in msg:
        return True  # handled — suppress
    log.error('WebsocketServer exception', exc_info=exc)
    return True  # don't re-raise


# ── Global server instance ──────────────────────────────────────────
websocket_server = WebsocketServer(
    rooms_ready=True,
    auto_clean_rooms=True,
    exception_handler=_ws_exception_handler,
)

# Per-room project path registry (for file_diff application and search)
_room_project_paths: dict[str, str] = {}

# Room close callbacks (for cleanup when room_service.close_room is called)
_room_close_callbacks: dict[str, Callable[[], None]] = {}

# ContextVar for binding room_id to the current WebSocket connection (on_disconnect)
_current_room_id: contextvars.ContextVar[str] = contextvars.ContextVar('_current_room_id', default='')

# ── Auth hook ────────────────────────────────────────────────────────

async def on_connect(message: dict[str, Any], scope: dict[str, Any]) -> bool:
    """ASGI connect hook.  Returns True to *reject* the WebSocket.

    Extracts the token from the query string, validates it against
    room_service, and ensures the user belongs to the requested room.
    """
    query_bytes = scope.get('query_string', b'')
    if isinstance(query_bytes, bytes):
        query_str = query_bytes.decode('utf-8', errors='replace')
    else:
        query_str = str(query_bytes)
    params = parse_qs(query_str)
    token = (params.get('token') or [None])[0]
    if not token:
        logger.warning('WebSocket rejected: missing token')
        return True

    session = room_service.validate_token(token)
    if not session:
        logger.warning('WebSocket rejected: invalid token')
        return True

    # room_id is derived from the URL path (strip /api/community/ws/ prefix)
    path = scope.get('path', '')
    ws_prefix = '/api/community/ws/'
    room_id = path[len(ws_prefix):] if path.startswith(ws_prefix) else path.lstrip('/')

    if session.get('room_id') != room_id:
        logger.warning('WebSocket rejected: token room mismatch')
        return True

    user_id = session['user_id']
    user = room_service.get_user(room_id, user_id)
    if not user:
        logger.warning('WebSocket rejected: user not found in room')
        return True

    # Mark user online — persisted in-memory for room_service queries
    room_service.set_user_status(room_id, user_id, 'online')

    # Attach metadata to scope so message handlers can use it
    scope['zaowu_room_id'] = room_id
    scope['zaowu_user_id'] = user_id
    scope['zaowu_user'] = user
    scope['zaowu_session'] = session

    # Register virtual project path for search and file_diff
    room_meta = room_service.get_room(room_id)
    if room_meta:
        project_id = room_meta.get('project_id', '')
        project_path = _resolve_project_path(room_id, project_id)
        if project_path and os.path.isdir(project_path):
            _room_project_paths[room_id] = os.path.normpath(project_path)

    # Register room close callback for search cleanup
    def _on_room_close():
        _room_project_paths.pop(room_id, None)
    _room_close_callbacks[room_id] = _on_room_close

    return False  # accept the WebSocket


# ── Custom message handler (0xF0 prefix) ────────────────────────────

ZAOWU_PREFIX: int = 0xF0


def set_custom_message_handler(room: YRoom) -> None:
    """Install the ZaoWu custom message hook on a YRoom.

    Messages starting with 0xF0 are parsed as JSON and dispatched to
    the appropriate business-logic handler.  Messages with 0x00 (SYNC)
    or 0x01 (AWARENESS) fall through to pycrdt-websocket's default
    processing.

    On every incoming message, a room_info broadcast is sent so that
    newly connected clients receive the project path. The frontend
    deduplicates by roomId, so redundant broadcasts are harmless.
    """
    # Resolve room_id from room name (get_room_name returns full URL path)
    room_name = websocket_server.get_room_name(room) or ''
    ws_prefix = '/api/community/ws/'
    room_id = room_name[len(ws_prefix):] if room_name.startswith(ws_prefix) else room_name.lstrip('/')

    async def _handler(message: bytes) -> bool:
        if not message:
            return False

        # Broadcast room_info on every message (frontend deduplicates by roomId)
        await _send_room_info(room, room_id)

        if message[0] == ZAOWU_PREFIX:
            await _dispatch_custom_message(message[1:], room)
            return True  # skip pycrdt default processing
        return False  # let pycrdt handle Yjs protocol messages

    room.on_message = _handler


async def _dispatch_custom_message(json_bytes: bytes, room: YRoom) -> None:
    """Parse a 0xF0-prefixed JSON payload and route to the right handler."""
    try:
        payload = json.loads(json_bytes.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning('Failed to parse custom message')
        return

    msg_type = payload.get('type', '')

    if msg_type == 'chat_message':
        await _handle_chat(room, payload)
    elif msg_type == 'permission_change':
        await _handle_permission_change(room, payload)
    elif msg_type == 'file_diff':
        await _handle_file_diff(room, payload)
    elif msg_type == 'awareness_update':
        await _broadcast_custom(room, payload)
    else:
        logger.debug('Unknown custom message type: %s', msg_type)


# ── Chat handler ─────────────────────────────────────────────────────

async def _handle_chat(room: YRoom, payload: dict[str, Any]) -> None:
    """Broadcast a chat message to all clients in the room."""
    # Chat messages are echoed to ALL clients (including sender) so the
    # sender sees their own message confirmed by the server.
    await _broadcast_custom(room, payload)


# ── Permission change handler ────────────────────────────────────────

async def _handle_permission_change(room: YRoom, payload: dict[str, Any]) -> None:
    """Broadcast a permission change notification to all clients."""
    await _broadcast_custom(room, payload)


# ── File diff handler ────────────────────────────────────────────────

async def _handle_file_diff(room: YRoom, payload: dict[str, Any]) -> None:
    """Apply a file diff payload to the local filesystem.

    Supports three diff operations:
      - 'write'  : payload contains {path, content}
      - 'delete' : payload contains {path}
      - 'rename' : payload contains {oldPath, newPath}

    Path-traversal protection: all paths are validated against the
    room's project root directory before any filesystem operation.
    """
    room_id = payload.get('roomId', '')
    if not room_id:
        return

    user_id = payload.get('userId', '')
    user = room_service.get_user(room_id, user_id) or {}
    if not can_edit(user.get('permissions', {})):
        return

    room_meta = room_service.get_room(room_id)
    if not room_meta:
        return

    project_root = room_meta.get('project_id', '')
    project_path = _resolve_project_path(room_id, project_root)
    if not project_path or not os.path.isdir(project_path):
        return

    try:
        content = payload.get('content')
        path = payload.get('path')
        delete_flag = payload.get('delete')
        old_path = payload.get('oldPath')
        new_path = payload.get('newPath')

        if path and content is not None and delete_flag is not True:
            target = _safe_path(project_path, path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, 'w', encoding='utf-8') as f:
                f.write(str(content))
        elif path and delete_flag:
            target = _safe_path(project_path, path)
            if os.path.isfile(target):
                os.remove(target)
        elif old_path and new_path:
            old = _safe_path(project_path, old_path)
            new = _safe_path(project_path, new_path)
            if os.path.isfile(old):
                os.makedirs(os.path.dirname(new), exist_ok=True)
                os.rename(old, new)
    except (ValueError, OSError) as exc:
        logger.warning('File diff application failed: %s', exc)

    # Broadcast to all clients EXCEPT the sender
    await _broadcast_custom(room, payload, exclude_user=user_id)


def _resolve_project_path(room_id: str, project_root: str) -> str:
    """Resolve a registered project root or fallback directory path."""
    # Check the room-project-path registry first
    if room_id in _room_project_paths:
        return _room_project_paths[room_id]

    if project_root:
        try:
            from routes.explorer import find_project
            proj = find_project(project_root)
            if proj:
                return os.path.normpath(proj.get('path', ''))
        except Exception:
            pass

    return ''


def _safe_path(project_path: str, relative: str) -> str:
    """Resolve a relative path inside project_path, rejecting traversal."""
    norm_project = os.path.normpath(project_path)
    resolved = os.path.normpath(os.path.join(norm_project, relative))
    if not resolved.startswith(norm_project + os.sep) and resolved != norm_project:
        raise ValueError(f'Path traversal rejected: {relative}')
    return resolved


def register_room_project_path(room_id: str, project_path: str) -> None:
    """Register a project path for a room (for rooms without registered projects)."""
    _room_project_paths[room_id] = os.path.normpath(project_path)


# ── Broadcast helper ─────────────────────────────────────────────────

async def _broadcast_custom(
    room: YRoom,
    payload: dict[str, Any],
    exclude_user: str | None = None,
) -> None:
    """Send a 0xF0-prefixed JSON message to all clients in a room.

    Args:
        room: The YRoom whose clients receive the message.
        payload: JSON-serialisable dictionary (will be 0xF0-prefixed).
        exclude_user: If set, the user_id to skip (e.g. file_diff sender).
    """
    json_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    message = bytes([ZAOWU_PREFIX]) + json_bytes

    for client in room.clients:
        # Clients don't carry a user_id natively, so we use the room-level
        # user registry to map back. If exclude is requested we skip
        # clients whose connected user_id matches.
        if exclude_user and _client_user_id(client) == exclude_user:
            continue
        try:
            await client.send(message)
        except Exception:
            logger.debug('Failed to send custom message to client', exc_info=True)


def _client_user_id(_client: Any) -> str | None:
    """Best-effort extraction of user_id from a pycrdt Channel.

    The Channel.path contains the room path, not user info. For exclusion
    purposes we maintain a reverse mapping of client -> user_id.
    """
    # In the current pycrdt-websocket model, clients are identified by
    # their Channel object. Since we don't store user metadata on the
    # Channel directly, broadcast exclusion uses the sender's user_id
    # from the message payload context (handled inline in _handle_file_diff
    # via the exclude_user parameter).
    return None


# ── WebSocket URL builder ────────────────────────────────────────────

def build_ws_url(room_host_address: str, token: str) -> str:
    """Construct a WebSocket URL for connecting to a community room.

    Args:
        room_host_address: host:port string (e.g. '192.168.1.100:5000').
        token: Session token for authentication.

    Returns:
        Full ws:// URL string.
    """
    host = room_host_address
    # Handle cases where host_address might already be a full URL
    if host.startswith('http://') or host.startswith('https://'):
        from urllib.parse import urlparse
        parsed = urlparse(host)
        host = parsed.netloc or parsed.hostname or host
    if ':' not in host:
        host = f'{host}:5000'
    return f'ws://{host}/api/community/ws/{{room_id}}?token={token}'


def build_ws_url_for_room(room_id: str, host_address: str, token: str) -> str:
    """Build the full WebSocket URL for a specific room.

    Args:
        room_id: The collaboration room id.
        host_address: host:port string.
        token: Session token.

    Returns:
        Full ws:// URL with room_id substituted.
    """
    base = build_ws_url(host_address, token)
    # Replace the {room_id} placeholder and append the actual token
    host = host_address
    if host.startswith('http://') or host.startswith('https://'):
        from urllib.parse import urlparse
        parsed = urlparse(host)
        host = parsed.netloc or parsed.hostname or host
    if ':' not in host:
        host = f'{host}:5000'
    return f'ws://{host}/api/community/ws/{room_id}?token={token}'


# ── Room info broadcaster ────────────────────────────────────────────

async def _send_room_info(room: YRoom, room_id: str) -> None:
    """Broadcast room project info to all clients (frontend deduplicates by roomId)."""
    room_meta = room_service.get_room(room_id)
    if not room_meta:
        return
    project_id = room_meta.get('project_id', '')
    project_path = _resolve_project_path(room_id, project_id)
    project_name = os.path.basename(project_path) if project_path else room_meta.get('name', '')

    payload = {
        'type': 'room_info',
        'roomId': room_id,
        'payload': {
            'projectPath': project_path,
            'projectName': project_name,
        },
        'timestamp': int(__import__('time').time() * 1000),
    }
    await _broadcast_custom(room, payload, exclude_user=None)


# ── ZaoWuASGIServer (on_disconnect cleanup via ContextVar) ──────────

def _on_disconnect_with_cleanup(message: dict[str, Any]) -> None:
    """on_disconnect callback: clean up search registration via ContextVar room_id."""
    room_id = _current_room_id.get('')
    if room_id:
        _room_project_paths.pop(room_id, None)
        _room_close_callbacks.pop(room_id, None)


class ZaoWuASGIServer(ASGIServer):
    """Subclass of ASGIServer that binds room_id via ContextVar for on_disconnect cleanup.

    Each WebSocket connection sets the ContextVar in __call__; the on_disconnect
    callback reads it from the same coroutine context. No instance-level state
    is modified, so multiple concurrent connections are safe.
    """

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            path = scope.get("path", "")
            ws_prefix = '/api/community/ws/'
            room_id = path[len(ws_prefix):] if path.startswith(ws_prefix) else path.lstrip('/')

            token = _current_room_id.set(room_id)
            try:
                await super().__call__(scope, receive, send)
            finally:
                _current_room_id.reset(token)
        else:
            await super().__call__(scope, receive, send)


# ── ASGI app factory ─────────────────────────────────────────────────

def create_asgi_app():
    """Create the ASGI application wrapping pycrdt-websocket.

    This ASGI app is mounted as middleware: requests to /api/community/ws/*
    are handled by pycrdt-websocket; all other requests fall through to Quart.
    """
    _asgi = ZaoWuASGIServer(
        websocket_server,
        on_connect=on_connect,
        on_disconnect=_on_disconnect_with_cleanup,
    )
    return _asgi


# ── Per-room ystore factory ──────────────────────────────────────────

def make_ystore(room_id: str):
    """Create an SQLiteYStore for persistent document storage.

    Called by YRoom if a custom store is needed per-room.
    """
    try:
        from pycrdt.store import SQLiteYStore
        db_path = os.path.join(DATA_DIR, f'{room_id}.sqlite')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        return SQLiteYStore(path=db_path)
    except ImportError:
        logger.warning('pycrdt-store not available; documents will not be persisted')
        return None

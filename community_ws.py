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

import asyncio
import contextvars
import json
import os
import uuid
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs

from pycrdt.websocket import ASGIServer, WebsocketServer, YRoom

from services import room_service
from services.permission_service import can_edit
from plugin_system import get_plugin_manager
from zaowu_paths import get_project_root

logger = logging.getLogger(__name__)

BASE_DIR = get_project_root()
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

# ContextVars for binding room_id/user_id to the current WebSocket connection.
# These are set in ZaoWuASGIServer.__call__ and read in the on_disconnect callback.
_current_room_id: contextvars.ContextVar[str] = contextvars.ContextVar('_current_room_id', default='')
_current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar('_current_user_id', default='')

# ── Plugin hook helpers ─────────────────────────────────────────────

def _schedule_async(coro: Awaitable[Any]) -> None:
    """Schedule a coroutine in the current or main event loop (fire-and-forget)."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)  # type: ignore[arg-type]
    except RuntimeError:
        mgr = get_plugin_manager()
        if mgr is not None and hasattr(mgr, '_main_loop') and mgr._main_loop is not None:
            mgr._main_loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(coro, loop=mgr._main_loop)  # type: ignore[arg-type]
            )


def _fire_user_hook(hook_name: str, room_id: str, user_id: str) -> None:
    """触发用户协作事件 hook（fire-and-forget，不阻塞 WS 处理）。

    自适应调度策略：
    - 若当前线程有运行中的事件循环（如 on_connect async 上下文），
      直接使用 asyncio.create_task()。
    - 若当前线程无事件循环（如 _on_disconnect_with_cleanup 同步回调），
      通过 PluginManager._main_loop.call_soon_threadsafe() 投递到主循环。
    """
    mgr = get_plugin_manager()
    if mgr is None:
        return

    async def _run_hooks():
        try:
            await mgr.fire_hook(hook_name, room_id, user_id)
        except Exception:
            pass

    _schedule_async(_run_hooks())

# ── Auth hook ────────────────────────────────────────────────────────

async def on_connect(message: dict[str, Any], scope: dict[str, Any]) -> bool:
    """ASGI connect hook.  Returns True to *reject* the WebSocket.

    Token 提取：
    1. Sec-WebSocket-Protocol 子协议（格式: auth.<token>）。
       注意：pycrdt-websocket 的 ASGIServer 不在 websocket.accept 中回显
       子协议，浏览器会按 RFC 6455 §4.1 拒绝握手，因此该路径在当前依赖版本
       下实际不可用，仅保留作为后端兼容逻辑。
    2. query string 的 token 参数 — 这是当前实际可用的方案。
       token 会出现在 URL/访问日志/Referer 中，请在 LAN/桌面场景下使用。

    安全建议：生产环境使用 wss:// 加密 + 短期 token（TTL < 60s）降低泄露风险。
    """
    token = None

    # 1. 从 Sec-WebSocket-Protocol 子协议读取（当前依赖版本下浏览器握手会失败）
    headers = scope.get('headers', [])
    for key, value in headers:
        if key == b'sec-websocket-protocol':
            proto = value.decode('utf-8', errors='replace')
            for part in proto.split(','):
                part = part.strip()
                if part.startswith('auth.'):
                    token = part[5:]
                    break
            if token:
                break

    # 2. 向后兼容：从 query string 读取 token
    if not token:
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

    # room_id is derived from the URL path (strip /api/v1/community/ws/ prefix, v1-compatible)
    import re
    path = scope.get('path', '')
    match = re.match(r'^/api(?:/v\d+)?/community/ws/(.+)$', path)
    room_id = match.group(1) if match else path.lstrip('/')

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

    # Bind user_id to the current async context for the disconnect hook.
    # on_connect runs inside the same ASGI task as ZaoWuASGIServer.__call__,
    # so the ContextVar is visible to _on_disconnect_with_cleanup.
    _current_user_id.set(user_id)

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

    # Register room close callback for search cleanup and room_closed broadcast
    def _on_room_close():
        _room_project_paths.pop(room_id, None)
        # Notify connected clients asynchronously
        _schedule_async(_broadcast_room_closed(room_id))
    _room_close_callbacks[room_id] = _on_room_close

    # Fire user-joined hook
    _fire_user_hook('zaowu_on_user_joined', room_id, user_id)

    return False  # accept the WebSocket


# ── Custom message handler (0xF0 prefix) ────────────────────────────

ZAOWU_PREFIX: int = 0xF0

# File diff limits (I-08)
MAX_DIFF_SIZE = 10 * 1024 * 1024  # 10 MB per write
MIN_DIFF_INTERVAL = 0.1  # seconds between writes from the same user
_user_diff_timestamps: dict[str, float] = {}


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
    import re
    room_name = websocket_server.get_room_name(room) or ''
    match = re.match(r'^/api(?:/v\d+)?/community/ws/(.+)$', room_name)
    room_id = match.group(1) if match else room_name.lstrip('/')

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
        # ★ 将未识别的消息类型转发给插件系统
        mgr = get_plugin_manager()
        if mgr is not None:
            try:
                result = await mgr.dispatch_ws_message(msg_type, payload)
                if result is not None:
                    await _broadcast_custom(room, result)
            except Exception:
                logger.debug('Plugin WS message dispatch failed', exc_info=True)


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

    The diff is broadcast to all other clients regardless of whether the
    local server has the project open, because collaborators may still need
    to apply the change to their own working copies.
    """
    room_id = payload.get('roomId', '')
    if not room_id:
        return

    user_id = payload.get('userId', '')
    user = room_service.get_user(room_id, user_id) or {}
    if not can_edit(user.get('permissions', {})):
        return

    # Rate limit per user
    if user_id:
        now = __import__('time').time()
        last = _user_diff_timestamps.get(user_id, 0)
        if now - last < MIN_DIFF_INTERVAL:
            logger.debug('file_diff rate limited for user %s', user_id)
            return
        _user_diff_timestamps[user_id] = now

    content = payload.get('content')
    path = payload.get('path')
    delete_flag = payload.get('delete')
    old_path = payload.get('oldPath')
    new_path = payload.get('newPath')

    # Size limit (write ops only)
    if path and content is not None and delete_flag is not True:
        content_bytes = str(content).encode('utf-8')
        if len(content_bytes) > MAX_DIFF_SIZE:
            logger.warning('file_diff rejected: size %d exceeds %d', len(content_bytes), MAX_DIFF_SIZE)
            return

    # Broadcast to all clients EXCEPT the sender before attempting local
    # filesystem application. Other clients need the diff even if this server
    # instance does not have the project directory locally available.
    await _broadcast_custom(room, payload, exclude_user=user_id)

    # Local filesystem application (best-effort)
    room_meta = room_service.get_room(room_id)
    if not room_meta:
        return

    project_root = room_meta.get('project_id', '')
    project_path = _resolve_project_path(room_id, project_root)
    if not project_path or not os.path.isdir(project_path):
        return

    try:
        if path and content is not None and delete_flag is not True:
            target = _safe_path(project_path, path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            # Atomic write: temp file + replace
            tmp = target + '.tmp.' + str(uuid.uuid4())[:8]
            try:
                with open(tmp, 'wb') as f:
                    f.write(str(content).encode('utf-8'))
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        elif path and delete_flag:
            target = _safe_path(project_path, path)
            if os.path.isfile(target):
                os.remove(target)
        elif old_path and new_path:
            old = _safe_path(project_path, old_path)
            new = _safe_path(project_path, new_path)
            if os.path.isfile(old):
                os.makedirs(os.path.dirname(new), exist_ok=True)
                os.replace(old, new)
    except (ValueError, OSError) as exc:
        logger.warning('File diff application failed: %s', exc)


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


def _client_user_id(client: Any) -> str | None:
    """Best-effort extraction of user_id from a pycrdt Channel.

    The user_id was attached to the ASGI scope during on_connect.  Some
    pycrdt-websocket Channel implementations expose that scope, allowing us
    to skip the sender when broadcasting file_diff.
    """
    # Try the scope attached to the channel/connection
    scope = getattr(client, 'scope', None)
    if scope and isinstance(scope, dict):
        user_id = scope.get('zaowu_user_id')
        if user_id:
            return user_id
    # Fallback to a manually bound attribute (set by integrations that can
    # intercept the channel creation).
    return getattr(client, '_zaowu_user_id', None)


# ── WebSocket URL builder ────────────────────────────────────────────

def build_ws_url(room_host_address: str, token: str | None = None) -> str:
    """Construct a WebSocket URL for connecting to a community room.

    The token is appended as a URL query parameter when provided. Note that
    Sec-WebSocket-Protocol cannot be used for token transfer because
    pycrdt-websocket's ASGIServer does not echo the selected subprotocol in
    websocket.accept, which causes browsers to reject the handshake per
    RFC 6455 §4.1.

    Args:
        room_host_address: host:port string (e.g. '192.168.1.100:5000').
        token: Optional session token for backwards compatibility.

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
    url = f'ws://{host}/api/v1/community/ws/{{room_id}}'
    if token:
        url = f'{url}?token={token}'
    return url


def build_ws_url_for_room(room_id: str, host_address: str, token: str | None = None) -> str:
    """Build the WebSocket URL for a specific room.

    Args:
        room_id: The collaboration room id.
        host_address: host:port string.
        token: Optional session token. If provided, the token is appended as a
            query parameter. Note that Sec-WebSocket-Protocol is not viable
            here because pycrdt-websocket's ASGIServer does not echo the
            selected subprotocol in websocket.accept, causing browsers to
            reject the handshake per RFC 6455 §4.1.

    Returns:
        Full ws:// URL with room_id substituted.
    """
    # Let plugins replace the host address (e.g. for intranet penetration)
    resolved = _resolve_host_address(host_address)
    if resolved:
        host_address = resolved

    host = host_address
    if host.startswith('http://') or host.startswith('https://'):
        from urllib.parse import urlparse
        parsed = urlparse(host)
        host = parsed.netloc or parsed.hostname or host
    if ':' not in host:
        host = f'{host}:5000'
    url = f'ws://{host}/api/v1/community/ws/{room_id}'
    if token:
        url = f'{url}?token={token}'
    return url


def _resolve_host_address(default_host: str) -> str | None:
    """调用插件的 zaowu_resolve_host_address hook。

    注意：此函数为同步 def，插件 **必须** 将 zaowu_resolve_host_address
    定义为同步函数（def）。若定义为 async def，inspect.iscoroutine()
    检测到后打印警告并跳过，确保 host_address 不会被误设为 coroutine 对象。
    """
    import inspect
    mgr = get_plugin_manager()
    if mgr is None:
        return None
    for record in mgr._enabled_records():
        if not record.enabled:
            continue
        fn = getattr(record.module, 'zaowu_resolve_host_address', None)
        if fn is not None:
            try:
                result = fn(default_host)
                if inspect.iscoroutine(result):
                    logger.warning(
                        'plugin %r: zaowu_resolve_host_address must be a '
                        'sync function, not async def; skipping',
                        record.name,
                    )
                    continue
                if result:
                    return result
            except Exception:
                pass
    return None


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


async def _broadcast_room_closed(room_id: str) -> None:
    """Broadcast a room_closed message to all connected clients."""
    import re
    room_name = f'/api/v1/community/ws/{room_id}'
    try:
        room = await websocket_server.get_room(room_name)
    except Exception:
        return
    if room is None:
        return
    payload = {
        'type': 'room_closed',
        'roomId': room_id,
        'payload': {},
        'timestamp': int(__import__('time').time() * 1000),
    }
    await _broadcast_custom(room, payload, exclude_user=None)


# ── ZaoWuASGIServer (on_disconnect cleanup via ContextVar) ──────────

def _on_disconnect_with_cleanup(message: dict[str, Any]) -> None:
    """on_disconnect callback: clean up search registration via ContextVar room_id."""
    room_id = _current_room_id.get('')
    user_id = _current_user_id.get('')
    if room_id:
        _room_project_paths.pop(room_id, None)
        _room_close_callbacks.pop(room_id, None)
        # Fire user-left hook
        if user_id:
            _fire_user_hook('zaowu_on_user_left', room_id, user_id)


class ZaoWuASGIServer(ASGIServer):
    """Subclass of ASGIServer that binds room_id via ContextVar for on_disconnect cleanup.

    Each WebSocket connection sets the ContextVar in __call__; the on_disconnect
    callback reads it from the same coroutine context. No instance-level state
    is modified, so multiple concurrent connections are safe.

    Additionally, we attach the ASGI ``scope`` to the ``ASGIWebsocket`` instance
    so that ``_client_user_id`` can map clients back to their authenticated
    ``zaowu_user_id`` and correctly honour ``exclude_user`` in broadcasts.
    """

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            import re
            from inspect import isawaitable
            from pycrdt.websocket.asgi_server import ASGIWebsocket

            path = scope.get("path", "")
            match = re.match(r'^/api(?:/v\d+)?/community/ws/(.+)$', path)
            room_id = match.group(1) if match else path.lstrip('/')

            room_token = _current_room_id.set(room_id)
            user_token = _current_user_id.set('')
            try:
                msg = await receive()
                if msg["type"] != "websocket.connect":
                    return

                if self._on_connect is not None:
                    close = self._on_connect(msg, scope)
                    if isawaitable(close):
                        close = await close
                    if close:
                        return

                await send({"type": "websocket.accept"})
                # Attach scope so broadcast helpers can read zaowu_user_id.
                websocket = ASGIWebsocket(receive, send, path, self._on_disconnect)
                websocket.scope = scope  # type: ignore[attr-defined]
                await self._websocket_server.serve(websocket)
            finally:
                _current_user_id.reset(user_token)
                _current_room_id.reset(room_token)
        else:
            await super().__call__(scope, receive, send)


# ── ASGI app factory ─────────────────────────────────────────────────

def create_asgi_app():
    """Create the ASGI application wrapping pycrdt-websocket.

    This ASGI app is mounted as middleware: requests to /api/v1/community/ws/*
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

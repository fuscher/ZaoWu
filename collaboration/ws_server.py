"""WebSocket server for real-time collaboration."""
import json
import threading
from flask import request

from services import room_service
from services.permission_service import can_edit
from collaboration.room import get_collab_room
from collaboration.yjs_provider import get_doc, encode_update_base64, decode_update_base64


HEARTBEAT_INTERVAL_SECONDS = 30
RECEIVE_TIMEOUT_SECONDS = 60

_ws_lock = threading.Lock()


def _apply_file_diff(room_id: str, payload: dict) -> None:
    """Apply a file_diff payload to the local filesystem.

    Supports three diff types:
      - 'write'  : payload contains {path, content} — write full file content
      - 'delete' : payload contains {path} — delete the file
      - 'rename' : payload contains {oldPath, newPath} — rename/move the file

    All paths are validated against the room's project directory to prevent
    escaping the project root via path traversal.
    """
    import os as _os
    room = room_service.get_room(room_id)
    if not room:
        return
    project_root = room.get('project_id', '')
    project_path = ''
    # Resolve the actual project directory from registered projects if available
    if project_root:
        try:
            from routes.explorer import get_project_by_id
            proj = get_project_by_id(project_root)
            if proj:
                project_path = _os.path.normpath(proj.get('path', ''))
        except Exception:
            pass
    if not project_path:
        # Fallback: store room project paths in a simple dict
        project_path = _room_project_paths.get(room_id, '')
    if not project_path or not _os.path.isdir(project_path):
        return

    def _safe_path(relative: str) -> str:
        """Resolve relative path inside project_root, rejecting traversal."""
        resolved = _os.path.normpath(_os.path.join(project_path, relative))
        if not resolved.startswith(_os.path.normpath(project_path) + _os.sep) \
           and resolved != _os.path.normpath(project_path):
            raise ValueError(f'path traversal rejected: {relative}')
        return resolved

    try:
        if 'path' in payload and 'content' in payload:
            # Write file
            target = _safe_path(payload['path'])
            _os.makedirs(_os.path.dirname(target), exist_ok=True)
            with open(target, 'w', encoding='utf-8') as f:
                f.write(payload['content'])
        elif 'path' in payload and 'delete' in payload:
            # Delete file
            target = _safe_path(payload['path'])
            if _os.path.isfile(target):
                _os.remove(target)
        elif 'oldPath' in payload and 'newPath' in payload:
            # Rename file
            old = _safe_path(payload['oldPath'])
            new = _safe_path(payload['newPath'])
            if _os.path.isfile(old):
                _os.makedirs(_os.path.dirname(new), exist_ok=True)
                _os.rename(old, new)
    except (ValueError, OSError):
        pass


_room_project_paths: dict = {}  # room_id -> project_path (for rooms without registered projects)


def register_room_project_path(room_id: str, project_path: str) -> None:
    """Register a project path for a room, used when the project is not in the explorer."""
    _room_project_paths[room_id] = project_path


def _send(ws, message: dict) -> None:
    try:
        ws.send(json.dumps(message))
    except Exception:
        pass


def _build_ws_url(room_id: str, host_address: str, token: str) -> str:
    if ':' in host_address and not host_address.startswith('http'):
        host = host_address
    elif ':' in host_address:
        from urllib.parse import urlparse
        parsed = urlparse(host_address)
        host = parsed.netloc
    else:
        host = f'{host_address}:5000'
    return f'ws://{host}/api/community/ws/{room_id}?token={token}'


def _get_ws_connection(environ: dict):
    """Extract a WebSocket connection from the WSGI environ.

    Supports gevent-websocket (wsgi.websocket).
    """
    if 'wsgi.websocket' in environ:
        return environ['wsgi.websocket']
    return None


def run_message_loop(ws, room_id: str, user_id: str) -> None:
    """Core message loop shared by all WebSocket entry points.

    Call this after token validation and connection registration are done.
    It reads messages from *ws*, dispatches them per message type (with
    permission checks), and cleans up on disconnect.

    Args:
        ws: A gevent-compatible WebSocket connection (read/write).
        room_id: The collaboration room id.
        user_id: The authenticated user id for this connection.
    """
    collab_room = get_collab_room(room_id)
    doc = get_doc(room_id)
    user = room_service.get_user(room_id, user_id) or {}

    # Send current document state to the new client
    try:
        update = doc.get_update_for_client()
        _send(ws, {
            'type': 'room_state',
            'roomId': room_id,
            'userId': user_id,
            'payload': {
                'users': room_service.get_room_users(room_id),
                'yjsUpdate': encode_update_base64(update),
                'permissions': user.get('permissions', {}),
            },
            'timestamp': room_service._now_ms(),
        })

        # Notify other users
        collab_room.broadcast({
            'type': 'user_joined',
            'roomId': room_id,
            'userId': user_id,
            'payload': {'user': user},
            'timestamp': room_service._now_ms(),
        }, exclude_user=user_id)

        # --- message dispatch loop ---
        while True:
            try:
                raw = ws.receive()
            except Exception:
                break
            if raw is None:
                break

            try:
                message = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            msg_type = message.get('type')
            payload = message.get('payload', {})

            if msg_type == 'ping':
                _send(ws, {
                    'type': 'pong',
                    'roomId': room_id,
                    'userId': user_id,
                    'payload': {},
                    'timestamp': room_service._now_ms(),
                })

            elif msg_type == 'yjs_update':
                if not can_edit(user.get('permissions', {})):
                    _send(ws, {
                        'type': 'error',
                        'roomId': room_id,
                        'userId': user_id,
                        'payload': {'message': 'insufficient permissions to edit'},
                        'timestamp': room_service._now_ms(),
                    })
                    continue
                try:
                    update_bytes = decode_update_base64(payload.get('update', ''))
                    doc.apply_update(update_bytes)
                    collab_room.broadcast({
                        'type': 'yjs_update',
                        'roomId': room_id,
                        'userId': user_id,
                        'payload': {'update': payload.get('update', '')},
                        'timestamp': room_service._now_ms(),
                    }, exclude_user=user_id)
                except Exception:
                    pass

            elif msg_type == 'awareness_update':
                if payload.get('cursor'):
                    user['cursor'] = payload['cursor']
                collab_room.broadcast({
                    'type': 'awareness_update',
                    'roomId': room_id,
                    'userId': user_id,
                    'payload': payload,
                    'timestamp': room_service._now_ms(),
                }, exclude_user=user_id)

            elif msg_type == 'chat_message':
                if not user.get('permissions', {}).get('chat', True):
                    continue
                collab_room.broadcast({
                    'type': 'chat_message',
                    'roomId': room_id,
                    'userId': user_id,
                    'payload': payload,
                    'timestamp': room_service._now_ms(),
                })

            elif msg_type == 'file_diff':
                if not can_edit(user.get('permissions', {})):
                    continue
                # Apply diff to local filesystem on the server side
                _apply_file_diff(room_id, payload)
                collab_room.broadcast({
                    'type': 'file_diff',
                    'roomId': room_id,
                    'userId': user_id,
                    'payload': payload,
                    'timestamp': room_service._now_ms(),
                }, exclude_user=user_id)

    finally:
        collab_room.remove_connection(user_id)
        room_service.set_user_status(room_id, user_id, 'offline')
        try:
            ws.close()
        except Exception:
            pass
        collab_room.broadcast({
            'type': 'user_left',
            'roomId': room_id,
            'userId': user_id,
            'payload': {'userId': user_id},
            'timestamp': room_service._now_ms(),
        }, exclude_user=user_id)


def handle_websocket(room_id: str):
    """Flask route handler for /api/community/ws/<room_id>."""
    token = request.args.get('token', '')
    session = room_service.validate_token(token)
    if not session or session['room_id'] != room_id:
        return '', 403

    user_id = session['user_id']
    user = room_service.get_user(room_id, user_id)
    if not user:
        return '', 403

    ws = _get_ws_connection(request.environ)
    if ws is None:
        return json.dumps({'ok': False, 'error': 'websocket not available'}), 503

    collab_room = get_collab_room(room_id)
    collab_room.add_connection(user_id, ws)
    room_service.set_user_status(room_id, user_id, 'online')

    run_message_loop(ws, room_id, user_id)
    return ''

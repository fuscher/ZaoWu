"""Community collaboration REST API blueprint."""
import uuid
from quart import Blueprint, request, jsonify

from services.room_service import (
    RoomServiceError,
    create_room,
    list_rooms,
    get_room,
    update_room,
    close_room,
    join_room,
    leave_room,
    get_room_users,
    update_user,
    remove_user,
    generate_invite_code,
    validate_token,
    cleanup_inactive_rooms,
)
from services.permission_service import PermissionServiceError
from community_ws import build_ws_url_for_room


community_bp = Blueprint('community', __name__)


def _now_ms() -> int:
    from datetime import datetime, timezone
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _host_id() -> str:
    """Return a stable host user id for this server instance."""
    import os
    from zaowu_paths import get_project_root
    marker = os.path.join(get_project_root(), '.host_id')
    try:
        if os.path.exists(marker):
            with open(marker, 'r', encoding='utf-8') as f:
                return f.read().strip()
    except Exception:
        pass
    hid = str(uuid.uuid4())
    try:
        with open(marker, 'w', encoding='utf-8') as f:
            f.write(hid)
    except Exception:
        pass
    return hid


_SNAKE_TO_CAMEL = {
    'invite_code': 'inviteCode',
    'project_id': 'projectId',
    'host_id': 'hostId',
    'host_address': 'hostAddress',
    'max_users': 'maxUsers',
    'default_role': 'defaultRole',
    'created_at': 'createdAt',
    'updated_at': 'updatedAt',
    'user_id': 'userId',
    'room_id': 'roomId',
}


def _to_camel(obj):
    """Recursively convert dict keys from snake_case to camelCase for JSON output."""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            camel_key = _SNAKE_TO_CAMEL.get(k, k)
            result[camel_key] = _to_camel(v)
        return result
    if isinstance(obj, list):
        return [_to_camel(item) for item in obj]
    return obj


@community_bp.route('/rooms', methods=['POST'])
async def api_create_room():
    body = await request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'missing body'}), 400

    name = body.get('name', '').strip()
    project_id = body.get('projectId', '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'missing name'}), 400

    max_users = body.get('maxUsers', 5)
    default_role = body.get('defaultRole', 'collaborator')
    host_address = body.get('hostAddress')

    try:
        room = create_room(
            name=name,
            project_id=project_id,
            host_id=_host_id(),
            host_address=host_address,
            max_users=max_users,
            default_role=default_role,
        )
    except PermissionServiceError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except RoomServiceError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    # Auto-join the host as first participant so they get credentials immediately
    user_name = body.get('userName', 'Host')
    try:
        host_user_id = _host_id()
        host_user, token = join_room(room['id'], room['invite_code'], user_name)
        # Override the auto-assigned role and id to match room.host_id
        host_user = update_user(room['id'], host_user['id'], role='host')
        # Store a mapping so leave_room can match host_user.id to room.host_id
        # (host_id = machine UUID, user.id = random UUID, they differ by design)
        import services.room_service as _svc
        _svc._host_user_map[room['id']] = host_user['id']
    except RoomServiceError:
        return jsonify({'ok': False, 'error': 'failed to join host to room'}), 500

    ws_url = build_ws_url_for_room(
        room['id'],
        room.get('host_address') or request.host,
        token,
    )

    return jsonify({
        'ok': True,
        'room': _to_camel(room),
        'inviteCode': room['invite_code'],
        'user': _to_camel(host_user),
        'token': token,
        'wsUrl': ws_url,
    })


@community_bp.route('/rooms', methods=['GET'])
async def api_list_rooms():
    rooms = list_rooms()
    return jsonify({'ok': True, 'rooms': _to_camel(rooms)})


@community_bp.route('/rooms/<room_id>', methods=['GET'])
async def api_get_room(room_id):
    room = get_room(room_id)
    if not room:
        return jsonify({'ok': False, 'error': 'room not found'}), 404
    users = get_room_users(room_id)
    return jsonify({
        'ok': True,
        'room': _to_camel(room),
        'users': _to_camel(users),
        'permissions': {u['id']: u.get('permissions', {}) for u in users},
    })


@community_bp.route('/rooms/<room_id>', methods=['PATCH'])
async def api_update_room(room_id):
    body = await request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'missing body'}), 400
    try:
        room = update_room(room_id, body)
    except RoomServiceError as e:
        return jsonify({'ok': False, 'error': str(e)}), 404
    except PermissionServiceError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    return jsonify({'ok': True, 'room': _to_camel(room)})


@community_bp.route('/rooms/<room_id>', methods=['DELETE'])
async def api_close_room(room_id):
    try:
        close_room(room_id)
    except RoomServiceError as e:
        return jsonify({'ok': False, 'error': str(e)}), 404
    return jsonify({'ok': True})


@community_bp.route('/rooms/<room_id>/join', methods=['POST'])
async def api_join_room(room_id):
    body = await request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'missing body'}), 400

    invite_code = body.get('inviteCode', '').strip().upper()
    user_name = body.get('userName', '').strip()
    if not invite_code:
        return jsonify({'ok': False, 'error': 'missing invite code'}), 400

    try:
        user, token = join_room(room_id, invite_code, user_name)
    except RoomServiceError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    room = get_room(room_id)
    ws_url = build_ws_url_for_room(room_id, room.get('host_address', request.host), token)
    room_state = {
        'users': get_room_users(room_id),
        'permissions': user.get('permissions', {}),
    }
    return jsonify({
        'ok': True,
        'user': _to_camel(user),
        'token': token,
        'wsUrl': ws_url,
        'roomState': _to_camel(room_state),
    })


@community_bp.route('/rooms/<room_id>/leave', methods=['POST'])
async def api_leave_room(room_id):
    body = await request.get_json(silent=True) or {}
    user_id = body.get('userId')
    if not user_id:
        return jsonify({'ok': False, 'error': 'missing userId'}), 400

    import services.room_service as _svc

    # The host_id stored in the room is a machine UUID (from _host_id()).
    # The user_id passed from the frontend is the *host user's* assigned
    # UUID.  We need to check _host_user_map so that when the host-user
    # leaves, the entire room is closed.
    leave_room(room_id, user_id)
    return jsonify({'ok': True})


@community_bp.route('/rooms/<room_id>/users', methods=['GET'])
async def api_get_users(room_id):
    if not get_room(room_id):
        return jsonify({'ok': False, 'error': 'room not found'}), 404
    return jsonify({'ok': True, 'users': _to_camel(get_room_users(room_id))})


@community_bp.route('/rooms/<room_id>/users/<user_id>', methods=['PATCH'])
async def api_update_user(room_id, user_id):
    body = await request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'missing body'}), 400
    try:
        user = update_user(
            room_id,
            user_id,
            role=body.get('role'),
            permissions=body.get('permissions'),
        )
    except RoomServiceError as e:
        return jsonify({'ok': False, 'error': str(e)}), 404
    except PermissionServiceError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    return jsonify({'ok': True, 'user': _to_camel(user)})


@community_bp.route('/rooms/<room_id>/users/<user_id>', methods=['DELETE'])
async def api_remove_user(room_id, user_id):
    try:
        remove_user(room_id, user_id)
    except RoomServiceError as e:
        return jsonify({'ok': False, 'error': str(e)}), 404
    return jsonify({'ok': True})


@community_bp.route('/rooms/<room_id>/invite', methods=['POST'])
async def api_generate_invite(room_id):
    try:
        invite_code = generate_invite_code(room_id)
    except RoomServiceError as e:
        return jsonify({'ok': False, 'error': str(e)}), 404
    return jsonify({'ok': True, 'inviteCode': invite_code})


@community_bp.route('/rooms/<room_id>/ws-url', methods=['GET'])
async def api_get_ws_url(room_id):
    token = request.args.get('token', '')
    session = validate_token(token)
    if not session or session['room_id'] != room_id:
        return jsonify({'ok': False, 'error': 'invalid token'}), 403
    room = get_room(room_id)
    if not room:
        return jsonify({'ok': False, 'error': 'room not found'}), 404
    ws_url = build_ws_url_for_room(room_id, room.get('host_address', request.host), token)
    return jsonify({'ok': True, 'wsUrl': ws_url})


@community_bp.route('/cleanup', methods=['POST'])
async def api_cleanup():
    closed = cleanup_inactive_rooms()
    return jsonify({'ok': True, 'closed': closed})

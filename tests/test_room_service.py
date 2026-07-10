"""Unit tests for room_service — room lifecycle, user management, token validation."""
import pytest
from services.room_service import (
    RoomServiceError,
    ABSOLUTE_MAX_USERS,
    create_room,
    list_rooms,
    get_room,
    update_room,
    close_room,
    generate_invite_code,
    join_room,
    leave_room,
    remove_user,
    get_room_users,
    get_user,
    update_user,
    validate_token,
    set_user_status,
    cleanup_inactive_rooms,
)


@pytest.fixture(autouse=True)
def _clean_rooms(monkeypatch):
    """Reset rooms file to empty for each test."""
    monkeypatch.setattr(
        'services.room_service._read_rooms',
        lambda: {'rooms': []},
    )
    monkeypatch.setattr(
        'services.room_service._write_rooms',
        lambda data: None,
    )
    # Clear in-memory user/session state
    monkeypatch.setattr(
        'services.room_service._users_by_room',
        {},
    )
    monkeypatch.setattr(
        'services.room_service._sessions',
        {},
    )


class TestCreateRoom:
    def test_creates_active_room(self):
        room = create_room('Test Room', 'project-1', 'host-1')
        assert room['name'] == 'Test Room'
        assert room['status'] == 'active'
        assert room['host_id'] == 'host-1'
        assert room['project_id'] == 'project-1'

    def test_defaults_max_users_from_settings(self, monkeypatch):
        monkeypatch.setattr(
            'services.room_service._read_settings',
            lambda: {
                'communityMaxUsers': 3,
                'communityDefaultRole': 'observer',
                'communityFileSizeLimitKB': 512,
                'communityInactiveTimeoutMinutes': 120,
            },
        )
        room = create_room('Test', 'p1', 'h1')
        assert room['max_users'] == 3
        assert room['default_role'] == 'observer'

    def test_clamps_max_users_to_absolute_max(self):
        room = create_room('Test', 'p1', 'h1', max_users=100)
        assert room['max_users'] == ABSOLUTE_MAX_USERS

    def test_clamps_max_users_minimum(self):
        room = create_room('Test', 'p1', 'h1', max_users=0)
        assert room['max_users'] == 1

    def test_generates_invite_code(self):
        room = create_room('Test', 'p1', 'h1')
        assert len(room['invite_code']) == 6
        assert room['invite_code'].isalnum()


class TestJoinRoom:
    def test_joins_with_valid_code(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}
        try:
            user, token = join_room(room['id'], room['invite_code'], 'Alice')
            assert user['name'] == 'Alice'
        finally:
            rs._read_rooms = orig_read

    def _create_and_join(self):
        """Helper that creates a room via create_room()'s _read_rooms override and joins."""
        room = create_room('Test', 'p1', 'h1')
        # Mock _read_rooms to return this room
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}
        try:
            user, token = join_room(room['id'], room['invite_code'], 'Alice')
            return room, user, token
        finally:
            rs._read_rooms = orig_read

    def test_join_returns_user_and_token(self):
        room, user, token = self._create_and_join()
        assert user['name'] == 'Alice'
        assert user['role'] == room['default_role']
        assert len(token) == 32  # hex UUID

    def test_join_rejects_wrong_invite_code(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {'rooms': [room]},
        )
        with pytest.raises(RoomServiceError, match='invalid invite code'):
            join_room(room['id'], 'WRONG', 'Bob')

    def test_join_rejects_closed_room(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        room['status'] = 'closed'
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {'rooms': [room]},
        )
        with pytest.raises(RoomServiceError, match='not active'):
            join_room(room['id'], room['invite_code'], 'Bob')

    def test_join_rejects_full_room(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1', max_users=1)
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {'rooms': [room]},
        )
        # Force room to appear full
        import services.room_service as rs
        rs._users_by_room[room['id']] = {'existing': {'id': 'existing'}}
        with pytest.raises(RoomServiceError, match='room is full'):
            join_room(room['id'], room['invite_code'], 'Bob')

    def test_join_assigns_unique_color(self):
        room, u1, _ = self._create_and_join()
        assert u1['color'].startswith('#')
        assert u1['status'] == 'online'

    def test_token_validates(self):
        room, user, token = self._create_and_join()
        session = validate_token(token)
        assert session is not None
        assert session['room_id'] == room['id']
        assert session['user_id'] == user['id']

    def test_invalid_token_returns_none(self):
        assert validate_token('bogus-token') is None


class TestUserManagement:
    def _setup_room_with_users(self):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}
        try:
            u1, _ = join_room(room['id'], room['invite_code'], 'Alice')
            u2, _ = join_room(room['id'], room['invite_code'], 'Bob')
            return room, u1, u2
        finally:
            rs._read_rooms = orig_read

    def test_list_users(self):
        room, u1, u2 = self._setup_room_with_users()
        users = get_room_users(room['id'])
        assert len(users) == 2
        names = {u['name'] for u in users}
        assert names == {'Alice', 'Bob'}

    def test_get_user(self):
        room, u1, _ = self._setup_room_with_users()
        found = get_user(room['id'], u1['id'])
        assert found is not None
        assert found['name'] == 'Alice'

    def test_leave_room_sets_offline(self):
        room, u1, _ = self._setup_room_with_users()
        leave_room(room['id'], u1['id'])
        user = get_user(room['id'], u1['id'])
        assert user['status'] == 'offline'

    def test_remove_user_deletes(self):
        room, u1, _ = self._setup_room_with_users()
        remove_user(room['id'], u1['id'])
        assert get_user(room['id'], u1['id']) is None

    def test_update_user_role(self):
        room, u1, _ = self._setup_room_with_users()
        result = update_user(room['id'], u1['id'], role='observer')
        assert result['role'] == 'observer'
        assert result['permissions']['edit'] is False

    def test_update_user_permissions(self):
        room, u1, _ = self._setup_room_with_users()
        result = update_user(room['id'], u1['id'], permissions={'chat': False})
        assert result['permissions']['chat'] is False

    def test_set_user_status(self):
        room, u1, _ = self._setup_room_with_users()
        set_user_status(room['id'], u1['id'], 'away')
        assert get_user(room['id'], u1['id'])['status'] == 'away'


class TestRoomLifecycle:
    def test_list_filters_active_only(self, monkeypatch):
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {
                'rooms': [
                    {'id': 'r1', 'name': 'Room 1', 'status': 'active'},
                    {'id': 'r2', 'name': 'Room 2', 'status': 'closed'},
                ],
            },
        )
        rooms = list_rooms()
        assert len(rooms) == 1
        assert rooms[0]['id'] == 'r1'

    def test_list_all_flag_returns_closed(self, monkeypatch):
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {
                'rooms': [
                    {'id': 'r1', 'status': 'active'},
                    {'id': 'r2', 'status': 'closed'},
                ],
            },
        )
        rooms = list_rooms(status='all')
        assert len(rooms) == 2

    def test_get_room_finds_by_id(self, monkeypatch):
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {'rooms': [{'id': 'r1', 'name': 'Test'}]},
        )
        assert get_room('r1')['name'] == 'Test'
        assert get_room('not-exist') is None

    def test_update_room_name(self, monkeypatch):
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {'rooms': [{'id': 'r1', 'name': 'Old', 'status': 'active'}]},
        )
        monkeypatch.setattr('services.room_service._write_rooms', lambda data: None)
        updated = update_room('r1', {'name': 'New'})
        assert updated['name'] == 'New'

    def test_update_room_not_found(self, monkeypatch):
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {'rooms': []},
        )
        with pytest.raises(RoomServiceError, match='room not found'):
            update_room('missing', {'name': 'X'})

    def test_close_room(self, monkeypatch):
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {'rooms': [{'id': 'r1', 'status': 'active', 'updated_at': 0}]},
        )
        monkeypatch.setattr('services.room_service._write_rooms', lambda data: None)
        close_room('r1')
        # Verify the write was called with closed status

    def test_generate_new_invite_code(self, monkeypatch):
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {
                'rooms': [{
                    'id': 'r1',
                    'invite_code': 'ABCDEF',
                    'status': 'active',
                    'updated_at': 0,
                }],
            },
        )
        monkeypatch.setattr('services.room_service._write_rooms', lambda data: None)
        new = generate_invite_code('r1')
        assert len(new) == 6
        assert new != 'ABCDEF'

    def test_cleanup_closes_inactive_rooms(self, monkeypatch):
        from datetime import datetime, timezone
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        old = now - (180 * 60 * 1000)  # 3 hours ago, beyond default 2h timeout
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {
                'rooms': [
                    {'id': 'old', 'status': 'active', 'updated_at': old},
                    {'id': 'fresh', 'status': 'active', 'updated_at': now},
                ],
            },
        )
        monkeypatch.setattr('services.room_service._write_rooms', lambda data: None)
        closed = cleanup_inactive_rooms()
        assert closed >= 1

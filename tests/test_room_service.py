"""Unit tests for room_service — room lifecycle, user management, token validation."""
import json
import pytest
from services.room_service import (
    RoomServiceError,
    ABSOLUTE_MAX_USERS,
    TOKEN_TTL_MS,
    MAX_FAILURES_PER_MINUTE,
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
    lookup_room_by_invite_code,
    set_room_host_user_id,
    is_host,
    _load_persisted_state,
    _migrate_host_user_ids,
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
    monkeypatch.setattr(
        'services.room_service._join_failures',
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


class TestTokenExpiry:
    def test_expired_token_is_invalid(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}
        try:
            user, token = join_room(room['id'], room['invite_code'], 'Alice')
            # Simulate an old creation time
            rs._sessions[token]['created_at'] = rs._now_ms() - TOKEN_TTL_MS - 1
            assert validate_token(token) is None
            assert token not in rs._sessions
        finally:
            rs._read_rooms = orig_read

    def test_cleanup_removes_expired_sessions(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}
        try:
            user, token = join_room(room['id'], room['invite_code'], 'Alice')
            rs._sessions[token]['created_at'] = rs._now_ms() - TOKEN_TTL_MS - 1
            monkeypatch.setattr('services.room_service._write_rooms', lambda data: None)
            cleanup_inactive_rooms()
            assert token not in rs._sessions
        finally:
            rs._read_rooms = orig_read


class TestInviteCodeBruteForce:
    def test_too_many_failed_joins_blocks_attempts(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}
        try:
            for _ in range(MAX_FAILURES_PER_MINUTE):
                with pytest.raises(RoomServiceError, match='invalid invite code'):
                    join_room(room['id'], 'WRONG', 'Bob')
            # The next attempt within the window should be rate-limited
            with pytest.raises(RoomServiceError, match='too many attempts'):
                join_room(room['id'], room['invite_code'], 'Bob')
        finally:
            rs._read_rooms = orig_read

    def test_successful_join_clears_failure_history(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}
        try:
            with pytest.raises(RoomServiceError):
                join_room(room['id'], 'WRONG', 'Bob')
            # Successful join should clear the failure record
            user, token = join_room(room['id'], room['invite_code'], 'Alice')
            assert user['name'] == 'Alice'
            assert room['id'] not in rs._join_failures
        finally:
            rs._read_rooms = orig_read


class TestLookupByInviteCode:
    def test_finds_active_room_by_code(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {'rooms': [room]},
        )
        found = lookup_room_by_invite_code(room['invite_code'])
        assert found is not None
        assert found['id'] == room['id']

    def test_lookup_is_case_insensitive(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {'rooms': [room]},
        )
        found = lookup_room_by_invite_code(room['invite_code'].lower())
        assert found is not None
        assert found['id'] == room['id']

    def test_missing_code_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            'services.room_service._read_rooms',
            lambda: {'rooms': []},
        )
        assert lookup_room_by_invite_code('ABCDEF') is None


class TestHostUserIdPersistence:
    def test_host_user_id_persisted_on_room(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}
        writes = []
        rs._write_rooms = lambda data: writes.append(data)
        try:
            host_user, token = join_room(room['id'], room['invite_code'], 'Host')
            host_user = update_user(room['id'], host_user['id'], role='host')
            updated_room = set_room_host_user_id(room['id'], host_user['id'])
            assert updated_room['host_user_id'] == host_user['id']
            # Verify the write propagated to the rooms file
            assert len(writes) >= 1
            persisted = next(
                (r for r in writes[-1]['rooms'] if r['id'] == room['id']),
                None,
            )
            assert persisted is not None
            assert persisted['host_user_id'] == host_user['id']
        finally:
            rs._read_rooms = orig_read

    def test_is_host_uses_persisted_host_user_id(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}
        try:
            host_user, _ = join_room(room['id'], room['invite_code'], 'Host')
            host_user = update_user(room['id'], host_user['id'], role='host')
            set_room_host_user_id(room['id'], host_user['id'])
            assert is_host(room['id'], host_user['id']) is True
            assert is_host(room['id'], 'someone-else') is False
        finally:
            rs._read_rooms = orig_read

    def test_host_leaving_closes_room_and_removes_sessions(self, monkeypatch):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}
        try:
            host_user, host_token = join_room(room['id'], room['invite_code'], 'Host')
            host_user = update_user(room['id'], host_user['id'], role='host')
            set_room_host_user_id(room['id'], host_user['id'])
            guest, guest_token = join_room(room['id'], room['invite_code'], 'Alice')

            leave_room(room['id'], host_user['id'])

            # Room should be closed
            assert get_room(room['id'])['status'] == 'closed'
            # All users and sessions removed
            assert get_user(room['id'], host_user['id']) is None
            assert get_user(room['id'], guest['id']) is None
            assert validate_token(host_token) is None
            assert validate_token(guest_token) is None
        finally:
            rs._read_rooms = orig_read

    def test_migrate_host_user_ids_backfills_legacy_room(self, monkeypatch, tmp_path):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}
        try:
            host_user, _ = join_room(room['id'], room['invite_code'], 'Host')
            host_user = update_user(room['id'], host_user['id'], role='host')
            # Simulate a legacy room with no host_user_id
            room['host_user_id'] = ''
            # Persist the user so _migrate_host_user_ids can find the host
            rs._users_by_room[room['id']] = {host_user['id']: host_user}
            _migrate_host_user_ids()
            assert room['host_user_id'] == host_user['id']
        finally:
            rs._read_rooms = orig_read


class TestSessionPersistence:
    def test_sessions_persisted_to_disk(self, monkeypatch, tmp_path):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}

        data_dir = tmp_path / 'data' / 'collaboration'
        data_dir.mkdir(parents=True)
        sessions_file = data_dir / 'community_sessions.json'
        users_file = data_dir / 'community_users.json'
        monkeypatch.setattr('services.room_service.SESSIONS_FILE', str(sessions_file))
        monkeypatch.setattr('services.room_service.USERS_FILE', str(users_file))

        try:
            user, token = join_room(room['id'], room['invite_code'], 'Alice')
            assert sessions_file.exists()
            with open(sessions_file, 'r', encoding='utf-8') as f:
                sessions = json.load(f)
            assert token in sessions
            assert sessions[token]['user_id'] == user['id']
        finally:
            rs._read_rooms = orig_read

    def test_load_persisted_state_restores_sessions(self, monkeypatch, tmp_path):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}

        data_dir = tmp_path / 'data' / 'collaboration'
        data_dir.mkdir(parents=True)
        sessions_file = data_dir / 'community_sessions.json'
        users_file = data_dir / 'community_users.json'
        monkeypatch.setattr('services.room_service.SESSIONS_FILE', str(sessions_file))
        monkeypatch.setattr('services.room_service.USERS_FILE', str(users_file))

        try:
            user, token = join_room(room['id'], room['invite_code'], 'Alice')
            # Simulate restart: clear in-memory state and reload
            rs._sessions = {}
            rs._users_by_room = {}
            _load_persisted_state()
            assert user['id'] in rs._users_by_room.get(room['id'], {})
            assert validate_token(token) is not None
        finally:
            rs._read_rooms = orig_read

    def test_load_persisted_state_drops_expired_sessions(self, monkeypatch, tmp_path):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}

        data_dir = tmp_path / 'data' / 'collaboration'
        data_dir.mkdir(parents=True)
        sessions_file = data_dir / 'community_sessions.json'
        users_file = data_dir / 'community_users.json'
        monkeypatch.setattr('services.room_service.SESSIONS_FILE', str(sessions_file))
        monkeypatch.setattr('services.room_service.USERS_FILE', str(users_file))

        try:
            user, token = join_room(room['id'], room['invite_code'], 'Alice')
            # Make the session expired
            rs._sessions[token]['created_at'] = rs._now_ms() - TOKEN_TTL_MS - 1
            rs._persist_sessions()

            # Simulate restart
            rs._sessions = {}
            rs._users_by_room = {}
            _load_persisted_state()
            assert validate_token(token) is None
            assert token not in rs._sessions
        finally:
            rs._read_rooms = orig_read

    def test_load_persisted_state_marks_users_offline(self, monkeypatch, tmp_path):
        room = create_room('Test', 'p1', 'h1')
        import services.room_service as rs
        orig_read = rs._read_rooms
        rs._read_rooms = lambda: {'rooms': [room]}

        data_dir = tmp_path / 'data' / 'collaboration'
        data_dir.mkdir(parents=True)
        sessions_file = data_dir / 'community_sessions.json'
        users_file = data_dir / 'community_users.json'
        monkeypatch.setattr('services.room_service.SESSIONS_FILE', str(sessions_file))
        monkeypatch.setattr('services.room_service.USERS_FILE', str(users_file))

        try:
            user, token = join_room(room['id'], room['invite_code'], 'Alice')
            assert user['status'] == 'online'
            rs._persist_users()

            # Simulate restart
            rs._users_by_room = {}
            _load_persisted_state()
            loaded_user = get_user(room['id'], user['id'])
            assert loaded_user is not None
            assert loaded_user['status'] == 'offline'
        finally:
            rs._read_rooms = orig_read

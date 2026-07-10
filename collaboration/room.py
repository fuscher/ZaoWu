"""In-memory collaboration room state and connection management."""
import threading
from typing import Dict, List, Any, Callable


class CollabRoom:
    """Runtime representation of an active collaboration room."""

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.connections: Dict[str, Any] = {}  # user_id -> ws connection
        self._lock = threading.RLock()

    def add_connection(self, user_id: str, ws) -> None:
        with self._lock:
            self.connections[user_id] = ws

    def remove_connection(self, user_id: str) -> None:
        with self._lock:
            self.connections.pop(user_id, None)

    def has_connection(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self.connections

    def broadcast(self, message: Dict[str, Any], exclude_user: str = None) -> None:
        """Broadcast a JSON message to all connections, optionally excluding one user."""
        import json as _json
        with self._lock:
            targets = list(self.connections.items())
        payload = _json.dumps(message)
        for user_id, ws in targets:
            if exclude_user and user_id == exclude_user:
                continue
            try:
                ws.send(payload)
            except Exception:
                # Connection likely dead; will be cleaned up on next receive
                pass


_rooms: Dict[str, CollabRoom] = {}
_rooms_lock = threading.Lock()


def get_collab_room(room_id: str) -> CollabRoom:
    with _rooms_lock:
        if room_id not in _rooms:
            _rooms[room_id] = CollabRoom(room_id)
        return _rooms[room_id]


def remove_collab_room(room_id: str) -> None:
    with _rooms_lock:
        _rooms.pop(room_id, None)

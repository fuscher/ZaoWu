"""Yjs CRDT document management and persistence for collaborative rooms."""
import os
import base64
import threading
from typing import Dict, List, Optional

try:
    import y_py as Y
    HAS_Y_PY = True
except Exception:
    HAS_Y_PY = False


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLAB_DATA_DIR = os.path.join(BASE_DIR, 'data', 'collaboration')

_doc_lock = threading.Lock()
_docs: Dict[str, 'YjsDocHandle'] = {}


class YjsDocHandle:
    """Wrapper around a Yjs document with persistence helpers.

    When y-py is available, updates are applied to a real CRDT document and
    persisted as a single state update. When y-py is unavailable (e.g. no Rust
    toolchain), the server falls back to storing raw update bytes and replaying
    them to new clients. Clients are responsible for merging the updates.
    """

    def __init__(self, room_id: str):
        self.room_id = room_id
        self._lock = threading.Lock()
        # Fallback state when y-py is not installed
        self._fallback_updates: List[bytes] = []
        if HAS_Y_PY:
            self.doc = Y.YDoc()
            self._text = self.doc.get_text('codemirror')
            self._map = self.doc.get_map('metadata')
        else:
            self.doc = None
            self._text = None
            self._map = None
        self._load()

    @property
    def text(self):
        return self._text

    @property
    def map(self):
        return self._map

    def _persist_path(self) -> str:
        os.makedirs(COLLAB_DATA_DIR, exist_ok=True)
        return os.path.join(COLLAB_DATA_DIR, f'{self.room_id}.ydoc')

    def _fallback_path(self) -> str:
        os.makedirs(COLLAB_DATA_DIR, exist_ok=True)
        return os.path.join(COLLAB_DATA_DIR, f'{self.room_id}.updates')

    def _load(self) -> None:
        if HAS_Y_PY:
            path = self._persist_path()
            if not os.path.exists(path):
                return
            try:
                with open(path, 'rb') as f:
                    data = f.read()
                if data:
                    Y.apply_update(self.doc, data)
            except Exception:
                pass
        else:
            path = self._fallback_path()
            if not os.path.exists(path):
                return
            try:
                with open(path, 'rb') as f:
                    data = f.read()
                if data:
                    # Updates are concatenated; Yjs clients can apply them in sequence
                    self._fallback_updates = [data]
            except Exception:
                pass

    def _save(self) -> None:
        if HAS_Y_PY:
            path = self._persist_path()
            try:
                update = Y.encode_state_as_update(self.doc)
                tmp = path + '.tmp'
                with open(tmp, 'wb') as f:
                    f.write(update)
                os.replace(tmp, path)
            except Exception:
                pass
        else:
            path = self._fallback_path()
            try:
                tmp = path + '.tmp'
                with open(tmp, 'wb') as f:
                    for update in self._fallback_updates:
                        f.write(update)
                os.replace(tmp, path)
            except Exception:
                pass

    def apply_update(self, update_bytes: bytes) -> None:
        with self._lock:
            if HAS_Y_PY:
                Y.apply_update(self.doc, update_bytes)
            else:
                self._fallback_updates.append(update_bytes)
            self._save()

    def get_update_for_client(self, state_vector: Optional[bytes] = None) -> bytes:
        if not HAS_Y_PY:
            with self._lock:
                # Concatenate all stored updates for the client to apply
                return b''.join(self._fallback_updates)
        with self._lock:
            return Y.encode_state_as_update(self.doc, state_vector)

    def get_text_content(self) -> str:
        if not HAS_Y_PY or self._text is None:
            return ''
        with self._lock:
            return str(self._text)

    def set_text_content(self, content: str) -> None:
        if not HAS_Y_PY or self._text is None:
            return
        with self._lock:
            current = str(self._text)
            if current != content:
                txn = self.doc.begin_transaction()
                try:
                    self._text.delete_range(txn, 0, len(current))
                    self._text.insert(txn, 0, content)
                except Exception:
                    # fallback for older y-py API without transaction object
                    self._text.delete(0, len(current))
                    self._text.insert(0, content)
                self._save()

    def get_state_vector(self) -> bytes:
        if not HAS_Y_PY:
            return b''
        with self._lock:
            return Y.encode_state_vector(self.doc)


def get_doc(room_id: str) -> YjsDocHandle:
    with _doc_lock:
        if room_id not in _docs:
            _docs[room_id] = YjsDocHandle(room_id)
        return _docs[room_id]


def remove_doc(room_id: str) -> None:
    with _doc_lock:
        _docs.pop(room_id, None)


def encode_update_base64(update: bytes) -> str:
    return base64.b64encode(update).decode('ascii')


def decode_update_base64(payload: str) -> bytes:
    return base64.b64decode(payload)

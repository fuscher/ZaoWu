"""Smoke test for community collaboration APIs and WebSocket (pycrdt-websocket protocol).

Tests the full lifecycle:
  1. Create a room via REST API
  2. Join as a collaborator
  3. Connect via WebSocket and receive the Yjs SYNC_STEP1 message
  4. Send a 0xF0-prefixed chat message and verify the server echoes it back
  5. Verify room cleanup
"""

import json
import struct
import urllib.request
import urllib.error
import websocket

BASE = 'http://127.0.0.1:5000/api/community'

# ── Protocol constants ───────────────────────────────────────────────
ZAOWU_PREFIX = 0xF0  # ZaoWu custom JSON messages (chat, file_diff, etc.)
YJS_SYNC = 0x00       # Yjs SYNC protocol (handled by pycrdt-websocket)
YJS_AWARENESS = 0x01  # Yjs AWARENESS protocol (handled by pycrdt-websocket)


def api(method, path, body=None):
    """Helper for REST API calls."""
    url = f'{BASE}{path}'
    data = None
    headers = {'Content-Type': 'application/json'}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))


def encode_custom_message(payload: dict) -> bytes:
    """Encode a ZaoWu custom message: 0xF0 prefix + JSON."""
    json_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    return bytes([ZAOWU_PREFIX]) + json_bytes


def decode_custom_message(data: bytes) -> dict | None:
    """Decode a ZaoWu 0xF0-prefixed custom message."""
    if data and data[0] == ZAOWU_PREFIX:
        try:
            return json.loads(data[1:].decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
    return None


def is_yjs_message(data: bytes) -> bool:
    """Check if a binary frame is a Yjs protocol message (0x00 or 0x01)."""
    return len(data) > 0 and data[0] in (YJS_SYNC, YJS_AWARENESS)


def main():
    # ── 1. Create a room ───────────────────────────────────────────
    created = api('POST', '/rooms', {
        'name': 'Test Room',
        'projectId': '',
        'maxUsers': 5,
        'defaultRole': 'collaborator',
    })
    assert created.get('ok'), f'Create room failed: {created}'
    print('created:', json.dumps(created, indent=2, ensure_ascii=False))

    room = created['room']
    invite = created['inviteCode']
    host_user = created['user']
    host_token = created['token']

    # ── 2. Join as a second collaborator ──────────────────────────
    joined = api('POST', f'/rooms/{room["id"]}/join', {
        'inviteCode': invite,
        'userName': 'Alice',
    })
    assert joined.get('ok'), f'Join room failed: {joined}'
    print('joined:', json.dumps(joined, indent=2, ensure_ascii=False))

    alice_user = joined['user']
    alice_token = joined['token']
    ws_url = joined['wsUrl']
    print('ws_url:', ws_url)

    # ── 3. Connect WebSocket (host) ───────────────────────────────
    host_ws_url = created['wsUrl']
    print('host_ws_url:', host_ws_url)

    host_ws = websocket.create_connection(host_ws_url)

    # The first message should be the Yjs SYNC_STEP1 (binary, 0x00 prefix)
    msg = host_ws.recv()
    assert isinstance(msg, (bytes, bytearray)), \
        f'Expected binary Yjs SYNC_STEP1, got {type(msg)}'
    assert is_yjs_message(msg if isinstance(msg, bytes) else bytes(msg)), \
        f'Expected Yjs SYNC message (0x00 or 0x01), got byte {msg[0]:#04x}'
    print('host ws received SYNC_STEP1 OK (len=%d)' % len(msg))

    # ── 4. Connect WebSocket (Alice) ─────────────────────────────
    alice_ws = websocket.create_connection(ws_url)
    alice_msg = alice_ws.recv()
    assert is_yjs_message(alice_msg if isinstance(alice_msg, bytes) else bytes(alice_msg)), \
        'Alice expected Yjs SYNC_STEP1'
    print('alice ws received SYNC_STEP1 OK (len=%d)' % len(alice_msg))

    # ── 5. Send a chat message via 0xF0 channel (host) ─────────────
    chat_payload = {
        'type': 'chat_message',
        'roomId': room['id'],
        'userId': host_user['id'],
        'payload': {'id': f'{host_user["id"]}-1', 'content': 'hello from host', 'timestamp': 1},
        'timestamp': 1,
    }
    host_ws.send(encode_custom_message(chat_payload), opcode=websocket.ABNF.OPCODE_BINARY)

    # Alice should receive the chat message (server broadcasts to all)
    # The server echoes it via 0xF0 prefix
    echo = alice_ws.recv()
    decoded = decode_custom_message(echo if isinstance(echo, bytes) else bytes(echo))
    if decoded:
        print('alice received chat echo:', json.dumps(decoded, indent=2, ensure_ascii=False))
        assert decoded.get('type') == 'chat_message', \
            f'Expected chat_message, got {decoded.get("type")}'
    else:
        # It might be a Yjs message if awareness was sent first; try next recv
        print('alice received non-custom message (likely Yjs awareness), trying next...')
        echo2 = alice_ws.recv()
        decoded2 = decode_custom_message(echo2 if isinstance(echo2, bytes) else bytes(echo2))
        assert decoded2, 'Expected to eventually receive chat_message as custom frame'
        assert decoded2.get('type') == 'chat_message'

    # ── 6. Cleanup ─────────────────────────────────────────────────
    host_ws.close()
    alice_ws.close()

    # Force room cleanup via API
    cleanup = api('POST', '/cleanup')
    print('cleanup:', cleanup)

    print()
    print('✅ test passed — all assertions OK')


if __name__ == '__main__':
    main()

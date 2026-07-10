"""Smoke test for community collaboration APIs and WebSocket."""
import json
import urllib.request
import urllib.error
import websocket

BASE = 'http://127.0.0.1:5000/api/community'


def api(method, path, body=None):
    url = f'{BASE}{path}'
    data = None
    headers = {'Content-Type': 'application/json'}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))


def main():
    # Create a room
    created = api('POST', '/rooms', {
        'name': 'Test Room',
        'projectId': '',
        'maxUsers': 5,
        'defaultRole': 'collaborator',
    })
    print('created:', created)
    room = created['room']
    invite = created['inviteCode']

    # Join as a collaborator
    joined = api('POST', f'/rooms/{room["id"]}/join', {
        'inviteCode': invite,
        'userName': 'Alice',
    })
    print('joined:', joined)
    token = joined['token']
    ws_url = joined['wsUrl']
    print('ws_url:', ws_url)

    # Connect WebSocket
    ws = websocket.create_connection(ws_url.replace('ws://', 'ws://'))
    msg = ws.recv()
    print('ws room_state:', msg)

    # Send a chat message
    ws.send(json.dumps({
        'type': 'chat_message',
        'roomId': room['id'],
        'userId': joined['user']['id'],
        'payload': {'content': 'hello', 'timestamp': 1},
        'timestamp': 1,
    }))
    msg = ws.recv()
    print('ws chat echo:', msg)

    ws.close()
    print('test passed')


if __name__ == '__main__':
    main()

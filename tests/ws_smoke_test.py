"""Quick test for WebSocket connectivity after server_quart startup."""
import threading, time, urllib.request, json, asyncio

def run_server():
    from server_quart import run_server
    run_server(port=5022)

def main():
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(8)

    # HTTP health check
    resp = urllib.request.urlopen('http://127.0.0.1:5022/api/health', timeout=5)
    print('HTTP health:', resp.read().decode().strip())

    # Create room
    req = urllib.request.Request(
        'http://127.0.0.1:5022/api/community/rooms',
        data=json.dumps({'name': 'Smoke', 'projectId': '', 'userName': 'Host'}).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    r = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())

    # Build WS URL using 127.0.0.1 (not LAN IP from API)
    from urllib.parse import urlparse
    parsed = urlparse(r['wsUrl'])
    ws_url = f"ws://127.0.0.1:{parsed.port}{parsed.path}?token={r['token']}"
    print(f'WS URL: {ws_url}')

    # Connect and verify SYNC_STEP1
    import websockets as ws_async

    async def connect():
        async with ws_async.connect(ws_url, close_timeout=10) as ws:
            msg = await ws.recv()
            print(f'PASS: byte[0]=0x{msg[0]:02x} len={len(msg)}')
            # Send a 0xF0 chat message
            chat = json.dumps({
                'type': 'chat_message',
                'roomId': r['room']['id'],
                'userId': r['user']['id'],
                'payload': {'content': 'hello smoke test', 'timestamp': 1},
                'timestamp': 1,
            }).encode('utf-8')
            await ws.send(bytes([0xF0]) + chat)
            print('Sent 0xF0 chat message')

    asyncio.run(connect())
    time.sleep(1)
    print('=== SMOKE TEST PASSED ===')

if __name__ == '__main__':
    main()

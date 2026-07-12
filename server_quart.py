import os
import json
import locale
import asyncio
from quart import Quart, send_from_directory, request, jsonify
from routes import explorer_bp, search_bp, log_bp, chat_bp, git_bp, terminal_bp, community_bp

app = Quart(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, 'ZaoWu', 'dist')
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')

DEFAULTS = {
    'enabled': True,
    'effect': 'linewaves',
    'persist': False,
    'language': 'zh-CN',
    'theme': 'dark',
    'searchMaxFileSizeKB': 1024,
    'searchResultLimit': 500,
    'communityMaxUsers': 5,
    'communityDefaultRole': 'collaborator',
    'communityFileSizeLimitKB': 512,
    'communityInactiveTimeoutMinutes': 120,
}


def detect_language():
    try:
        system_lang = locale.getdefaultlocale()[0]
    except Exception:
        system_lang = None
    if system_lang and system_lang.startswith('zh'):
        return 'zh-CN'
    return 'en'


def read_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if 'language' not in saved:
                    saved['language'] = detect_language()
                for key, val in DEFAULTS.items():
                    if key not in saved:
                        saved[key] = val
                return saved
        except (json.JSONDecodeError, IOError):
            pass
    return {**DEFAULTS, 'language': detect_language()}


def write_settings(data):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


app.register_blueprint(explorer_bp, url_prefix='/api/explorer')
app.register_blueprint(search_bp, url_prefix='/api/search')
app.register_blueprint(log_bp, url_prefix='/api/log')
app.register_blueprint(chat_bp, url_prefix='/api/chat')
app.register_blueprint(git_bp, url_prefix='/api/git')
app.register_blueprint(terminal_bp, url_prefix='/api/terminal')
app.register_blueprint(community_bp, url_prefix='/api/community')


@app.route('/')
async def index():
    html_path = os.path.join(DIST_DIR, 'index.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    settings_json = json.dumps(read_settings())
    injected = html.replace(
        '<script ',
        f'<script>window.__SETTINGS__ = {settings_json};</script>\n    <script ',
        1,
    )
    return injected


@app.route('/assets/<path:path>')
async def assets(path):
    return await send_from_directory(os.path.join(DIST_DIR, 'assets'), path)


@app.route('/api/health')
async def health():
    return jsonify({'status': 'ok'})


@app.route('/api/settings', methods=['GET', 'POST'])
async def settings():
    if request.method == 'GET':
        return jsonify(read_settings())
    elif request.method == 'POST':
        data = await request.get_json(silent=True)
        if data and isinstance(data, dict):
            write_settings(data)
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': 'invalid data'}), 400


@app.route('/<path:path>')
async def fallback(path):
    file_path = os.path.join(DIST_DIR, path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return await send_from_directory(DIST_DIR, path)
    return await send_from_directory(DIST_DIR, 'index.html')


# ── ASGI middleware for pycrdt-websocket ─────────────────────────────

from community_ws import create_asgi_app, websocket_server

_ws_asgi = create_asgi_app()


@app.before_serving
async def _startup_ws_server():
    """Start pycrdt-websocket's WebsocketServer before Quart begins serving.

    WebsocketServer.start() internally loops waiting for _stopped, so it
    never returns. We use its async context manager (__aenter__/__aexit__)
    which spawns the server in a background anyio task group.

    We also patch get_room() so every newly created YRoom gets our 0xF0
    custom message handler installed.
    """
    await websocket_server.__aenter__()
    import community_ws
    _original_get_room = websocket_server.get_room
    async def _get_room_with_handler(name: str):
        room = await _original_get_room(name)
        if not room.on_message:
            community_ws.set_custom_message_handler(room)
        return room
    websocket_server.get_room = _get_room_with_handler  # type: ignore[assignment]


@app.after_serving
async def _shutdown_ws_server():
    """Stop the WebsocketServer when Quart finishes serving.

    On Windows daemon threads, pycrdt Subscription objects are dropped on a
    thread different from their origin, which produces a harmless RuntimeError
    on exit.  We catch it here so the server shuts down cleanly.
    """
    try:
        await websocket_server.__aexit__(None, None, None)
    except RuntimeError:
        pass  # cross-thread Subscription drop on Windows — harmless


@app.before_serving
async def _mount_ws_middleware():
    """Mount the pycrdt-websocket ASGI app as middleware before Quart starts.

    Requests matching /api/community/ws/* are routed to the pycrdt-websocket
    ASGIServer for WebSocket handling; all other requests fall through to Quart.

    IMPORTANT: before_serving hooks fire in registration order. _startup_ws_server
    (which starts websocket_server) MUST be registered before this hook, so the
    ASGI middleware is installed AFTER the websocket server is ready.
    """
    original_asgi = app.asgi_app

    async def _asgi_middleware(scope, receive, send):
        if scope.get('type') == 'websocket' and scope.get('path', '').startswith('/api/community/ws/'):
            await _ws_asgi(scope, receive, send)
        else:
            await original_asgi(scope, receive, send)

    app.asgi_app = _asgi_middleware


# ── Server entry point ───────────────────────────────────────────────

def _start_asyncio(port: int) -> None:
    """Run the Hypercorn ASGI server in a dedicated asyncio event loop.

    Called from a daemon thread so the PyWebView main thread is not blocked.
    On Windows, signal handlers are not supported outside the main thread, so
    we monkey-patch `signal.signal` to a no-op before Hypercorn tries to
    register any handlers.
    """
    import sys

    # On Windows daemon threads, signal.signal() raises ValueError.
    # Hypercorn unconditionally calls it inside worker_serve(). We stub it
    # out here so the serve() call succeeds.
    if sys.platform == 'win32':
        import signal as _signal_module
        _signal_module.signal = lambda *a, **kw: None  # type: ignore[assignment]

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_run_hypercorn(port))


async def _run_hypercorn(port: int = 5000) -> None:
    from hypercorn.config import Config
    from hypercorn.asyncio import serve

    config = Config()
    config.bind = [f'0.0.0.0:{port}']
    config.include_server_header = False
    await serve(app, config, shutdown_trigger=_never_shutdown)  # type: ignore[arg-type]


async def _never_shutdown() -> None:
    """A shutdown trigger that never fires — the server keeps running until
    the process exits (via PyWebView's os._exit(0) in main.py)."""
    await asyncio.Event().wait()


def run_server(port: int = 5000) -> None:
    """Start the Quart + pycrdt-websocket server (blocking).

    Compatible with the existing main.py interface: the function name
    and signature match the old server.run_server().
    """
    _start_asyncio(port)


if __name__ == '__main__':
    run_server()

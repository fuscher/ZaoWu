import os
import sys
import json
import locale
import asyncio
import logging
from quart import Quart, send_from_directory, request, jsonify, redirect
from routes import explorer_bp, search_bp, log_bp, chat_bp, git_bp, terminal_bp, community_bp, plugin_bp, agent_skills_bp
from zaowu_paths import get_project_root, get_dist_dir, get_plugins_dir

app = Quart(__name__)

BASE_DIR = get_project_root()
DIST_DIR = get_dist_dir()
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')
PLUGINS_DIR = get_plugins_dir()

API_VERSION = 'v1'

# ── Plugin system bootstrap ────────────────────────────────────────
from plugin_system import PluginManager, get_plugin_manager, set_plugin_manager

_plugin_mgr = PluginManager(PLUGINS_DIR)
_plugin_mgr.attach_app(app)
set_plugin_manager(_plugin_mgr)
_logger = logging.getLogger('plugin_system')

# All routes registered under /api/xxx (legacy). An ASGI middleware (see below)
# transparently rewrites /api/v1/xxx → /api/xxx so v1-aware clients work without
# duplicate blueprint registrations.
app.register_blueprint(explorer_bp, url_prefix='/api/explorer')
app.register_blueprint(search_bp, url_prefix='/api/search')
app.register_blueprint(log_bp, url_prefix='/api/log')
app.register_blueprint(chat_bp, url_prefix='/api/chat')
app.register_blueprint(git_bp, url_prefix='/api/git')
app.register_blueprint(terminal_bp, url_prefix='/api/terminal')
app.register_blueprint(community_bp, url_prefix='/api/community')
app.register_blueprint(plugin_bp, url_prefix='/api/plugins')
app.register_blueprint(agent_skills_bp, url_prefix='/api/agent/skills')

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
async def _startup_logging():
    """Configure unified logging before any other subsystem starts."""
    from services.logging_config import configure_logging
    configure_logging()
    _logger.info('logging configured: zaowu root logger + RotatingFileHandler -> logs/app.ndjson')


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
        if scope.get('type') == 'websocket' and scope.get('path', '').startswith('/api/') and 'community/ws/' in scope.get('path', ''):
            await _ws_asgi(scope, receive, send)
        else:
            await original_asgi(scope, receive, send)

    app.asgi_app = _asgi_middleware


@app.before_serving
async def _mount_api_version_prefix():
    """Rewrite /api/v1/* → /api/* transparently for v1-aware clients.

    This avoids duplicate blueprint registrations while allowing the frontend
    to use versioned paths. The original /api/* paths remain directly accessible
    (used by test suite and backwards compatibility).

    Important: WebSocket paths (scope type='websocket') are NOT rewritten —
    the WS middleware has already intercepted them by this point.
    """
    original_asgi = app.asgi_app

    async def _rewrite(scope, receive, send):
        if scope.get('type') == 'http':
            path = scope.get('path', '')
            if path.startswith(f'/api/{API_VERSION}/'):
                scope['path'] = path.replace(f'/api/{API_VERSION}/', '/api/', 1)
        await original_asgi(scope, receive, send)

    app.asgi_app = _rewrite


# ── SQLite conversation store ───────────────────────────────────────

from services.conversation_store import ConversationStore

_conversation_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    """返回全局 ConversationStore 单例。必须在 before_serving 之后调用。"""
    assert _conversation_store is not None, 'store not initialised — call during before_serving'
    return _conversation_store


@app.before_serving
async def _migrate_conversations():
    """Create tables and one-time import from conversations.json → SQLite."""
    global _conversation_store
    _conversation_store = ConversationStore()
    await _conversation_store.ensure_tables()

    json_path = os.path.join(BASE_DIR, 'conversations.json')
    if os.path.exists(json_path):
        try:
            count = await _conversation_store.migrate_from_json(json_path)
            if count > 0:
                backup = json_path + '.bak'
                os.rename(json_path, backup)
                _logger.info(
                    'migrated %d conversations from JSON → SQLite (backup: %s)',
                    count, backup,
                )
            else:
                _logger.info('no conversations to migrate from %s', json_path)
        except Exception:
            _logger.exception('conversation migration failed; continuing')
    else:
        _logger.info('no conversations.json found; starting with empty SQLite store')


# ── Plugin system lifecycle ────────────────────────────────────────
# before_serving / after_serving fire in registration order.
# Startup order:  _startup_logging → _startup_ws_server → _mount_ws_middleware → _mount_api_version_prefix → _migrate_conversations → _startup_skills → _startup_plugins
#   (plugins see running WS server, registered middleware, loaded skills and configured logging)
# Shutdown order: _shutdown_ws_server → _shutdown_plugins
#   (plugins must not touch the WS server during zaowu_app_shutdown)

from services.skill_loader import DEFAULT_SKILLS_DIR


def _is_safe_skills_dir(skills_dir: str) -> bool:
    """Validate that ``skills_dir`` is a real directory under ``BASE_DIR``.

    Resolves symbolic links and rejects paths that escape the project root,
    preventing accidental traversal if the configured directory is tampered
    with between restarts.
    """
    try:
        real_path = os.path.realpath(skills_dir)
        base_real = os.path.realpath(BASE_DIR)
        return os.path.isdir(real_path) and real_path.startswith(base_real + os.sep)
    except Exception:
        return False


@app.before_serving
async def _startup_skills():
    """Discover and register skills from agent_modules/skills/."""
    if not _is_safe_skills_dir(DEFAULT_SKILLS_DIR):
        _logger.error(
            'skills directory %r is not under project root or is unreachable; '
            'skipping skill discovery',
            DEFAULT_SKILLS_DIR,
        )
        return
    try:
        from services.skill_loader import discover_skills
        loaded = await asyncio.to_thread(discover_skills, DEFAULT_SKILLS_DIR)
        _logger.info('skills loaded: %s', loaded)
    except Exception:
        _logger.exception('skill startup failed; continuing without skills')


@app.before_serving
async def _startup_plugins():
    """Discover, load, and start every plugin in plugins/."""
    mgr = get_plugin_manager()
    if mgr is None:
        _logger.warning('PluginManager not installed; skipping plugin startup')
        return
    try:
        await mgr.load_all()
        # Plugins register their blueprints via zaowu_register_routes.
        # Must happen before the server accepts requests.
        await mgr.collect_routes()

        # Collect agent tools registered by plugins and merge them into the
        # global ToolRegistry.  Delay the import to avoid circular imports.
        try:
            plugin_tools = await mgr.collect_agent_tools()
            from services.tool_registry import ToolRegistry
            registry = ToolRegistry.get_instance()
            for tool in plugin_tools:
                registry.register(tool)
                _logger.info('registered agent tool from plugin: %s', tool.name)
        except Exception:
            _logger.exception('failed to collect plugin agent tools; continuing')

        # Collect agent skills registered by plugins and merge them into the
        # global SkillRegistry.  Plugin skills may override builtin skills.
        # New plugin skills default to enabled unless the user has explicitly
        # disabled (or deleted) a skill with the same name in .skill_state.json.
        try:
            plugin_skills = await mgr.collect_skills()
            from services.skill_registry import SkillRegistry
            from services.skill_loader import load_skill_state
            skill_registry = SkillRegistry.get_instance()
            state = load_skill_state(DEFAULT_SKILLS_DIR)
            disabled = set(state.get('disabled') or [])
            deleted = set(state.get('deleted') or [])
            for skill in plugin_skills:
                if skill.name in deleted:
                    _logger.info('plugin skill %s is marked deleted; skipping', skill.name)
                    continue
                enabled = skill.name not in disabled
                skill_registry.register(skill, enabled=enabled)
                _logger.info(
                    'registered agent skill from plugin: %s (enabled=%s)',
                    skill.name, enabled,
                )
        except Exception:
            _logger.exception('failed to collect plugin skills; continuing')

        # ★ ASGI 中间件挂载 hook（早于任何 HTTP 请求）
        for record in mgr._enabled_records():
            await mgr._invoke(record, 'zaowu_mount_asgi_middleware')

        await mgr.startup_hooks()
    except Exception:
        _logger.exception('plugin startup failed; continuing without plugins')


@app.after_serving
async def _shutdown_plugins():
    """Invoke zaowu_app_shutdown on every enabled plugin and clean up."""
    mgr = get_plugin_manager()
    if mgr is None:
        return
    try:
        await mgr.shutdown_hooks()
    except Exception:
        _logger.exception('plugin shutdown failed')


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
    asyncio._zaowu_main_loop = loop  # 保存主事件循环引用，供子线程异步 hook 调用
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

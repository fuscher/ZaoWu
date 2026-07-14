"""hello_world — minimal example plugin for ZaoWu.

Demonstrates every key plugin-system feature in the smallest possible
footprint:

* Reading config via ``plugin_api.config``
* Logging via ``plugin_api.logger``
* Subscribing to the event bus
* Registering a sidebar panel + activity bar action + status bar item
* Registering a custom HTTP route via ``zaowu_register_routes``
* Cleaning up on shutdown

Copy this folder to ``plugins/my_thing/`` and edit away — no other
files need to change.
"""

from plugin_system.api import plugin_api
from plugin_system.bus import event_bus


# ── Lifecycle hooks ────────────────────────────────────────────────

def zaowu_plugin_loaded():
    """Called once when the plugin module is first imported."""
    plugin_api.logger.info('hello_world loaded (v1.0.0)')


def zaowu_plugin_enabled():
    """Called when the user enables the plugin. Return False to veto."""
    plugin_api.logger.info('hello_world enabled')
    return True


def zaowu_plugin_disabled():
    """Called when the user disables the plugin. Return False to veto."""
    plugin_api.logger.info('hello_world disabled')
    return True


def zaowu_app_startup():
    """Called after the host application has finished starting."""
    cfg = plugin_api.config
    if cfg.get('logOnStartup', True):
        plugin_api.logger.info('startup greeting: %s', cfg.get('greeting', 'Hello!'))

    # Demonstrate event bus subscription: listen for our own events
    event_bus.subscribe('hello_world.ping', _on_ping, owner='hello_world')

    # Publish a greeting so other plugins could react
    event_bus.publish('hello_world.loaded', {'version': '1.0.0'})


def zaowu_app_shutdown():
    """Called when the host application is about to stop."""
    plugin_api.logger.info('hello_world shutting down')
    # The manager auto-unsubscribes on disable, but doing it explicitly
    # here is good hygiene for the shutdown path.
    event_bus.unsubscribe_all('hello_world')


# ── File system event hook ─────────────────────────────────────────

def zaowu_on_file_saved(path: str):
    """Called whenever the user saves a file in the editor."""
    plugin_api.logger.info('zaowu_on_file_saved: %s', path)


# ── Frontend extension hooks ───────────────────────────────────────

def zaowu_sidebar_panels():
    """Register a sidebar panel. The frontend looks for
    ``plugins/hello_world/frontend/Panel.vue`` to render it.
    """
    return [{
        'id': 'hello_world_panel',
        'label': {'zh-CN': '你好', 'en': 'Hello'},
        'icon': 'Smile',
        'component': 'Panel',
        'order': 100,
    }]


def zaowu_activity_bar_actions():
    """Register an activity-bar button (no frontend component required)."""
    return [{
        'id': 'hello_world_action',
        'label': {'zh-CN': '打招呼', 'en': 'Say Hello'},
        'icon': 'Zap',
        'handler': 'hello_world.click',
        'order': 50,
    }]


def zaowu_status_bar_items():
    """Register a status-bar widget."""
    return [{
        'id': 'hello_world_status',
        'component': 'StatusWidget',
        'position': 'right',
        'order': 200,
    }]


def zaowu_settings_sections():
    """Register a settings section. The frontend looks for
    ``plugins/hello_world/frontend/Settings.vue`` to render it.
    """
    return [{
        'id': 'hello_world_settings',
        'label': {'zh-CN': '你好设置', 'en': 'Hello Settings'},
        'component': 'Settings',
        'icon': 'Smile',
        'order': 100,
    }]


# ── HTTP route registration ───────────────────────────────────────

def zaowu_register_routes():
    """Register a custom HTTP endpoint.

    The route becomes ``GET /api/plugins/hello_world/greet`` — note the
    ``/api/plugins`` prefix is added by the host, and the blueprint's
    own ``url_prefix`` adds ``/hello_world``.
    """
    from quart import Blueprint, jsonify

    bp = Blueprint('hello_world', __name__, url_prefix='/hello_world')

    @bp.route('/greet', methods=['GET'])
    async def greet():
        greeting = plugin_api.config.get('greeting', 'Hello!')
        return jsonify({
            'ok': True,
            'greeting': greeting,
            'plugin': 'hello_world',
        })

    @bp.route('/projects', methods=['GET'])
    async def list_projects():
        # Demonstrate access to host services
        projects = plugin_api.get_projects()
        return jsonify({
            'ok': True,
            'count': len(projects),
            'projects': [{'id': p.get('id'), 'path': p.get('path')} for p in projects],
        })

    return [bp]


# ── WebSocket message handling ────────────────────────────────────

def zaowu_ws_message_types():
    """Declare custom WebSocket message types this plugin handles."""
    return ['hello_world.ping']


def zaowu_handle_ws_message(msg_type, payload):
    """Handle a custom WS message. Return a dict to broadcast it."""
    if msg_type == 'hello_world.ping':
        return {
            'type': 'hello_world.pong',
            'payload': {'echo': payload, 'from': 'hello_world'},
        }
    return None


# ── Event bus handler ─────────────────────────────────────────────

def _on_ping(payload):
    """Called when another plugin publishes ``hello_world.ping``."""
    plugin_api.logger.info('received ping: %r', payload)

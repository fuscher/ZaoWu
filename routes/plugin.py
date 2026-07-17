"""Plugin management REST API.

All endpoints are mounted under ``/api/plugins`` by ``server_quart.py``.
They are thin wrappers around :class:`plugin_system.PluginManager` —
every operation delegates to the manager and translates
:class:`PluginError` subclasses into appropriate HTTP statuses.

Endpoint summary
----------------
* ``GET    /api/plugins``                      — list all plugins
* ``GET    /api/plugins/<name>``               — get one plugin
* ``POST   /api/plugins/<name>/enable``        — enable
* ``POST   /api/plugins/<name>/disable``       — disable
* ``POST   /api/plugins/<name>/reload``        — hot reload
* ``DELETE /api/plugins/<name>``               — uninstall (rename folder)
* ``GET    /api/plugins/<name>/config``        — read config
* ``PUT    /api/plugins/<name>/config``        — replace config
* ``GET    /api/plugins/extensions``           — aggregate frontend extensions
* ``POST   /api/plugins/discover``             — re-scan plugins dir
"""

from __future__ import annotations

from quart import Blueprint, jsonify, request

from plugin_system import (
    PluginError,
    PluginNotFoundError,
    PluginStateError,
    get_plugin_manager,
)

plugin_bp = Blueprint('plugins', __name__)


def _mgr():
    """Return the active PluginManager or a 503-style error tuple."""
    mgr = get_plugin_manager()
    if mgr is None:
        return None, (jsonify({'ok': False, 'error': 'plugin system not initialised'}), 503)
    return mgr, None


def _err(exc: PluginError, status: int = 400):
    return jsonify({'ok': False, 'error': str(exc)}), status


# ── List / detail ───────────────────────────────────────────────────

@plugin_bp.route('', methods=['GET'])
async def list_plugins():
    mgr, err = _mgr()
    if err:
        return err
    return jsonify({'ok': True, 'plugins': mgr.list_plugins()})  # type: ignore[union-attr]


@plugin_bp.route('/<name>', methods=['GET'])
async def get_plugin(name: str):
    mgr, err = _mgr()
    if err:
        return err
    info = mgr.get_plugin(name)  # type: ignore[union-attr]
    if info is None:
        return _err(PluginNotFoundError(f'plugin {name!r} not found'), 404)
    return jsonify({'ok': True, 'plugin': info})


# ── Lifecycle ───────────────────────────────────────────────────────

@plugin_bp.route('/<name>/enable', methods=['POST'])
async def enable_plugin(name: str):
    mgr, err = _mgr()
    if err:
        return err
    try:
        await mgr.enable(name)  # type: ignore[union-attr]
    except PluginNotFoundError as exc:
        return _err(exc, 404)
    except PluginStateError as exc:
        return _err(exc, 409)
    return jsonify({'ok': True, 'plugin': mgr.get_plugin(name)})  # type: ignore[union-attr]


@plugin_bp.route('/<name>/disable', methods=['POST'])
async def disable_plugin(name: str):
    mgr, err = _mgr()
    if err:
        return err
    try:
        await mgr.disable(name)  # type: ignore[union-attr]
    except PluginNotFoundError as exc:
        return _err(exc, 404)
    except PluginStateError as exc:
        return _err(exc, 409)
    return jsonify({'ok': True, 'plugin': mgr.get_plugin(name)})  # type: ignore[union-attr]


@plugin_bp.route('/<name>/reload', methods=['POST'])
async def reload_plugin(name: str):
    mgr, err = _mgr()
    if err:
        return err
    try:
        await mgr.reload(name)  # type: ignore[union-attr]
    except PluginNotFoundError as exc:
        return _err(exc, 404)
    except PluginError as exc:
        return _err(exc, 500)
    return jsonify({'ok': True, 'plugin': mgr.get_plugin(name)})  # type: ignore[union-attr]


@plugin_bp.route('/<name>', methods=['DELETE'])
async def uninstall_plugin(name: str):
    mgr, err = _mgr()
    if err:
        return err
    try:
        await mgr.uninstall(name)  # type: ignore[union-attr]
    except PluginNotFoundError as exc:
        return _err(exc, 404)
    except PluginStateError as exc:
        return _err(exc, 500)
    return jsonify({'ok': True})


# ── Config ──────────────────────────────────────────────────────────

@plugin_bp.route('/<name>/config', methods=['GET'])
async def get_config(name: str):
    mgr, err = _mgr()
    if err:
        return err
    info = mgr.get_plugin(name)  # type: ignore[union-attr]
    if info is None:
        return _err(PluginNotFoundError(f'plugin {name!r} not found'), 404)
    return jsonify({'ok': True, 'config': info['config']})


@plugin_bp.route('/<name>/config', methods=['PUT'])
async def update_config(name: str):
    mgr, err = _mgr()
    if err:
        return err
    body = await request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'ok': False, 'error': 'expected a JSON object body'}), 400
    try:
        mgr.update_config(name, body)  # type: ignore[union-attr]
    except PluginNotFoundError as exc:
        return _err(exc, 404)
    return jsonify({'ok': True, 'config': body})


# ── Frontend extension aggregation ──────────────────────────────────

@plugin_bp.route('/extensions', methods=['GET'])
async def get_extensions():
    """Aggregate every enabled plugin's frontend contributions.

    Returns a single object with five keys — ``panels``, ``actions``,
    ``settings``, ``statusItems``, ``detailSections`` — each a concatenated
    list.  The frontend can call this once on startup to learn about all
    plugin UI contributions.
    """
    mgr, err = _mgr()
    if err:
        return err
    panels = await mgr.collect_sidebar_panels()  # type: ignore[union-attr]
    actions = await mgr.collect_activity_bar_actions()  # type: ignore[union-attr]
    settings = await mgr.collect_settings_sections()  # type: ignore[union-attr]
    status_items = await mgr.collect_status_bar_items()  # type: ignore[union-attr]
    detail_sections = await mgr.collect_detail_sections()  # type: ignore[union-attr]
    return jsonify({
        'ok': True,
        'panels': panels,
        'actions': actions,
        'settings': settings,
        'statusItems': status_items,
        'detailSections': detail_sections,
    })


# ── Discovery ───────────────────────────────────────────────────────

@plugin_bp.route('/discover', methods=['POST'])
async def rediscover():
    """Re-scan the plugins directory and report the result.

    This does **not** unload already-loaded plugins whose folder has
    disappeared — call ``/api/plugins/<name>`` DELETE for that.  It
    primarily picks up newly added plugin folders.
    """
    mgr, err = _mgr()
    if err:
        return err
    loaded, broken = await mgr.load_all()  # type: ignore[union-attr]
    return jsonify({'ok': True, 'loaded': loaded, 'broken': broken, 'plugins': mgr.list_plugins()})  # type: ignore[union-attr]

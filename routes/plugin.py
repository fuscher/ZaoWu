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
* ``POST   /api/plugins/install``              — install from uploaded zip
* ``GET    /api/plugins/<name>/frontend/<path>`` — serve frontend bundle
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile

from quart import Blueprint, jsonify, request, send_from_directory

from plugin_system import (
    PluginError,
    PluginLoadError,
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


# ── Install from zip ────────────────────────────────────────────────

_NAME_RE = re.compile(r'^[A-Za-z0-9_]+$')
_MAX_ZIP_SIZE = 10 * 1024 * 1024  # 10 MB


@plugin_bp.route('/install', methods=['POST'])
async def install_plugin():
    """Install a plugin from an uploaded .zip file.

    The zip must contain a top-level directory with ``manifest.json``
    and ``__init__.py``.  Frontend bundles (if any) are included in
    the zip under ``frontend/dist/``.
    """
    mgr, err = _mgr()
    if err:
        return err

    # 1. Receive the uploaded file
    files = await request.files
    upload = files.get('file')
    if upload is None:
        return jsonify({'ok': False, 'error': 'no file uploaded'}), 400

    # Read content and check size
    content = upload.read()
    if len(content) > _MAX_ZIP_SIZE:
        return jsonify({'ok': False, 'error': f'file too large (max {_MAX_ZIP_SIZE // 1024 // 1024}MB)'}), 400

    # 2. Extract to a temporary directory
    tmp_dir = tempfile.mkdtemp(prefix='zaowu_plugin_')
    try:
        zip_path = os.path.join(tmp_dir, 'upload.zip')
        with open(zip_path, 'wb') as f:
            f.write(content)

        if not zipfile.is_zipfile(zip_path):
            return jsonify({'ok': False, 'error': 'not a valid zip file'}), 400

        extract_dir = os.path.join(tmp_dir, 'extracted')
        os.makedirs(extract_dir)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Path traversal guard
            for info in zf.infolist():
                dest = os.path.normpath(os.path.join(extract_dir, info.filename))
                if not dest.startswith(os.path.normpath(extract_dir) + os.sep) and dest != os.path.normpath(extract_dir):
                    return jsonify({'ok': False, 'error': f'unsafe path in zip: {info.filename}'}), 400
            zf.extractall(extract_dir)

        # 3. Find the plugin root (may be nested one level in the zip)
        entries = os.listdir(extract_dir)
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            plugin_src = os.path.join(extract_dir, entries[0])
        else:
            plugin_src = extract_dir

        # 4. Validate required files
        manifest_path = os.path.join(plugin_src, 'manifest.json')
        init_path = os.path.join(plugin_src, '__init__.py')

        if not os.path.isfile(manifest_path):
            return jsonify({'ok': False, 'error': 'missing manifest.json'}), 400
        if not os.path.isfile(init_path):
            return jsonify({'ok': False, 'error': 'missing __init__.py'}), 400

        # Parse and validate manifest
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            return jsonify({'ok': False, 'error': f'invalid manifest.json: {exc}'}), 400

        plugin_name = manifest_data.get('name')
        if not isinstance(plugin_name, str) or not _NAME_RE.match(plugin_name):
            return jsonify({'ok': False, 'error': 'manifest "name" must match ^[A-Za-z0-9_]+$'}), 400

        # 5. Copy to plugins directory
        plugins_dir = mgr.plugins_dir  # type: ignore[union-attr]
        dest_dir = os.path.join(plugins_dir, plugin_name)

        if os.path.exists(dest_dir):
            return jsonify({'ok': False, 'error': f'plugin {plugin_name!r} already exists'}), 409

        shutil.copytree(plugin_src, dest_dir)

        # 6. Load the new plugin via the manager
        try:
            await mgr.install_from_path(dest_dir)  # type: ignore[union-attr]
        except PluginError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 500

        info = mgr.get_plugin(plugin_name)  # type: ignore[union-attr]
        return jsonify({'ok': True, 'plugin': info})

    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500
    finally:
        # Clean up temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Plugin frontend bundle serving ──────────────────────────────────

@plugin_bp.route('/<name>/frontend/<path:path>', methods=['GET'])
async def serve_frontend(name: str, path: str):
    """Serve static files from a plugin's ``frontend/`` directory.

    This allows the browser to load pre-compiled JS bundles for
    runtime-installed plugins via dynamic ``import()``.

    Security: path traversal is blocked by send_from_directory
    (it rejects ``..`` segments), and we additionally restrict
    the scope to the ``frontend/`` subdirectory.
    """
    mgr, err = _mgr()
    if err:
        return err

    plugins_dir = mgr.plugins_dir  # type: ignore[union-attr]
    frontend_dir = os.path.join(plugins_dir, name, 'frontend')

    if not os.path.isdir(frontend_dir):
        return jsonify({'ok': False, 'error': 'plugin frontend directory not found'}), 404

    # Ensure the resolved path is inside frontend_dir
    requested = os.path.normpath(os.path.join(frontend_dir, path))
    if not requested.startswith(os.path.normpath(frontend_dir) + os.sep):
        return jsonify({'ok': False, 'error': 'invalid path'}), 400

    if not os.path.isfile(requested):
        return jsonify({'ok': False, 'error': 'file not found'}), 404

    # Determine content type for JS/JSON files
    if requested.endswith('.js'):
        mimetype = 'application/javascript'
    elif requested.endswith('.json'):
        mimetype = 'application/json'
    else:
        mimetype = None

    return await send_from_directory(frontend_dir, path, mimetype=mimetype)

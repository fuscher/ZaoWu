"""Project path resolution for both development and PyInstaller-frozen runs.

When the application is packaged with PyInstaller, ``sys.executable`` points to
the bundled executable instead of the Python interpreter.  Modules that compute
project paths from ``__file__`` would otherwise resolve to the temporary
``_internal`` extraction directory, which is overwritten on every update.  This
module separates *runtime data* (settings, conversations, logs, etc.) from
*bundled resources* (frontend build, plugins, agent skills) so each lives in the
right place after deployment.
"""

from __future__ import annotations

import os
import sys


def _exe_dir() -> str:
    """Directory that contains the running executable."""
    return os.path.dirname(os.path.abspath(sys.executable))


def get_project_root() -> str:
    """Return the directory that should hold runtime data and configuration.

    In development this is the repository root (the directory containing this
    module).  In a PyInstaller bundle it is the deployment root next to the
    executable, searched upward for common runtime markers so both a flat
    deployment (``<root>/ZaoWu.exe``) and the nested reference layout
    (``<root>/dist/ZaoWu/ZaoWu.exe``) resolve to the same root.
    """
    if not getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(__file__))

    exe_dir = _exe_dir()
    markers = [
        'settings.json',
        'conversations.json',
        'projects.json',
        'providers.json',
        'chat_config.json',
        'data',
        'logs',
        # 版本化部署的部署根锚点（启动器预置）：settings.json 被误删时防止上溯越界
        'versions.json',
    ]
    current = exe_dir
    while True:
        for marker in markers:
            if os.path.exists(os.path.join(current, marker)):
                return current
        parent = os.path.dirname(current)
        if parent == current:
            return exe_dir
        current = parent


def get_resource_root() -> str:
    """Return the directory that holds bundled application resources.

    In development this is the repository root (``plugins/``, ``agent_modules/``
    and ``ZaoWu/dist/`` live here).  In a PyInstaller one-folder bundle the
    resources are packaged inside the ``_internal`` directory next to the
    executable, matching the reference deployment layout.
    """
    if not getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(__file__))
    return os.path.join(_exe_dir(), '_internal')


def get_dist_dir() -> str:
    """Return the frontend build directory (contains ``index.html``)."""
    return os.path.join(get_resource_root(), 'ZaoWu', 'dist')


def get_plugins_dir() -> str:
    """Return the directory that contains built-in plugins."""
    return os.path.join(get_resource_root(), 'plugins')


def get_agent_modules_dir() -> str:
    """Return the directory that contains agent module packages."""
    return os.path.join(get_resource_root(), 'agent_modules')


def get_server_port() -> int:
    """Return the TCP port the ZaoWu server binds to.

    Overridable via the ``ZAOWU_PORT`` environment variable.  This lets the
    default 5000 be avoided when another process transiently holds it (the
    Bilibili desktop client is known to grab 5000 as an ephemeral source
    port, which makes ``bind 0.0.0.0:5000`` fail with WinError 10013).

    Every component that advertises the server address — the collaboration
    room host and the websocket URL builders — must read this so peers
    always connect to the port the server is actually listening on.
    """
    raw = os.environ.get('ZAOWU_PORT', '5000')
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 5000

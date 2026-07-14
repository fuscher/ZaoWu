"""Service API exposed to plugins.

Plugins interact with the host exclusively through this module.  Two
access styles are supported, both backed by the same implementation:

1. **Function-style** (recommended for simple plugins)::

       from plugin_system.api import plugin_api

       def zaowu_app_startup():
           projects = plugin_api.get_projects()
           plugin_api.logger.info('saw %d projects', len(projects))

2. **Class-style** (when a plugin wants explicit context)::

       from plugin_system.api import PluginAPI, PluginContext

       class MyPlugin:
           def __init__(self, api: PluginAPI, ctx: PluginContext):
               self.api = api
               self.ctx = ctx
           def zaowu_app_startup(self):
               self.ctx.logger.info('started with %r', self.ctx.config)

Design notes
------------
* ``plugin_api`` is a process-wide singleton; it delegates to the host
  services (room_service, explorer, settings, the Quart app).
* Per-plugin state (config, logger) is resolved through a
  :class:`contextvars.ContextVar` that the :class:`PluginManager` binds
  for the duration of each hook call.  This means ``plugin_api.config``
  "just works" inside any hook, with zero boilerplate.
* All host services are imported lazily inside methods so that importing
  :mod:`plugin_system.api` never triggers heavy initialisation and never
  creates a circular import with the Quart app.
"""

from __future__ import annotations

import contextvars
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger('plugin_system.api')


# ── Per-plugin context ──────────────────────────────────────────────

@dataclass
class PluginContext:
    """Per-plugin view of the world: identity, config, logger.

    A fresh instance is created by the :class:`PluginManager` when a
    plugin is loaded.  The user-overridden config (from
    ``data/plugin_configs.json``) is merged on top of the manifest
    defaults here, so plugins never need to read the manifest themselves.
    """

    name: str
    config: Dict[str, Any] = field(default_factory=dict)
    logger: logging.Logger = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.logger is None:
            self.logger = logging.getLogger(f'plugin.{self.name}')


# ── Current-plugin ContextVar ───────────────────────────────────────

#: Bound by PluginManager around each hook call so that ``plugin_api``
#: can resolve the calling plugin's context.  Default ``None`` means
#: "not inside a plugin hook" — accessing ``plugin_api.config`` then
#: raises a clear error instead of silently returning empty data.
_current_plugin: contextvars.ContextVar[Optional[PluginContext]] = contextvars.ContextVar(
    'plugin_system_current_plugin', default=None,
)


def _require_ctx() -> PluginContext:
    ctx = _current_plugin.get()
    if ctx is None:
        raise RuntimeError(
            'plugin_api.config / .logger / .name can only be used inside a '
            'plugin hook; the PluginManager binds them automatically. If you '
            'need plugin context outside a hook, use a class-style plugin '
            'and capture the PluginContext in __init__.'
        )
    return ctx


# ── Host-level service API ──────────────────────────────────────────

class PluginAPI:
    """Bridge between plugins and ZaoWu core services.

    The class is intentionally thin: each method delegates to an
    existing host module so the plugin system never duplicates business
    logic.  A single instance is shared process-wide (see :data:`plugin_api`).
    """

    def __init__(self) -> None:
        self._app: Any = None  # Quart app, set by PluginManager.attach_app
        self._lock = threading.RLock()
        # plugin_name -> PluginContext (the manager populates this)
        self._contexts: Dict[str, PluginContext] = {}
        # Blueprints registered by plugins, tracked for diagnostics
        self._registered_blueprints: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Wiring (called by PluginManager)
    # ------------------------------------------------------------------ #

    def attach_app(self, app: Any) -> None:
        """Bind the Quart app so plugins can register blueprints."""
        self._app = app

    def register_context(self, ctx: PluginContext) -> None:
        with self._lock:
            self._contexts[ctx.name] = ctx

    def drop_context(self, name: str) -> None:
        with self._lock:
            self._contexts.pop(name, None)

    def get_context(self, name: str) -> Optional[PluginContext]:
        return self._contexts.get(name)

    def bind_context(self, ctx: PluginContext):
        """Context manager that sets ``_current_plugin`` for a hook call.

        Returns a token that must be passed to :meth:`reset_context`.
        Implemented as a plain setter (not ``with``) so it can be used
        from async code without an extra import.
        """
        return _current_plugin.set(ctx)

    def reset_context(self, token: Any) -> None:
        _current_plugin.reset(token)

    # ------------------------------------------------------------------ #
    # Per-plugin accessors (resolve via ContextVar)
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        """Name of the plugin currently invoking a hook."""
        return _require_ctx().name

    @property
    def config(self) -> Dict[str, Any]:
        """Config dict for the current plugin (manifest defaults + user overrides)."""
        return _require_ctx().config

    @property
    def logger(self) -> logging.Logger:
        """Logger namespaced as ``plugin.<name>``."""
        return _require_ctx().logger

    # ------------------------------------------------------------------ #
    # Host services
    # ------------------------------------------------------------------ #

    def get_app(self) -> Any:
        """Direct access to the Quart app (advanced use)."""
        if self._app is None:
            raise RuntimeError('Quart app has not been attached to PluginAPI yet')
        return self._app

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Read a value from the host ``settings.json``."""
        try:
            from server_quart import read_settings
            return read_settings().get(key, default)
        except Exception:
            logger.debug('get_setting fallback', exc_info=True)
            return default

    def get_projects(self) -> List[Dict[str, Any]]:
        """Return the list of registered projects (same shape as /api/explorer/projects)."""
        try:
            from routes.explorer import read_projects
            return read_projects()
        except Exception:
            logger.debug('get_projects failed', exc_info=True)
            return []

    def get_room_service(self):
        """Return the :mod:`services.room_service` module for direct room CRUD."""
        from services import room_service
        return room_service

    async def broadcast_to_room(self, room_id: str, payload: Dict[str, Any]) -> bool:
        """Broadcast a custom JSON message to every client in a room.

        Uses the same 0xF0-prefixed protocol as the collaboration
        WebSocket layer, so frontend code that already listens for
        ``type``-keyed messages will receive it transparently.

        Returns ``True`` if the room existed and the message was sent.
        """
        try:
            from community_ws import websocket_server, ZAOWU_PREFIX
            import json
            room = await websocket_server.get_room(f'/api/community/ws/{room_id}')
            if room is None:
                return False
            message = bytes([ZAOWU_PREFIX]) + json.dumps(payload, ensure_ascii=False).encode('utf-8')
            for client in list(room.clients):
                try:
                    await client.send(message)
                except Exception:
                    pass
            return True
        except Exception:
            logger.debug('broadcast_to_room failed', exc_info=True)
            return False

    def register_blueprint(self, bp: Any, url_prefix: Optional[str] = None) -> None:
        """Register a Quart Blueprint on the host app.

        Must be called during ``zaowu_register_routes`` so the blueprint
        is live before the server starts accepting requests.
        """
        if self._app is None:
            raise RuntimeError('cannot register blueprint: Quart app not attached')
        self._app.register_blueprint(bp, url_prefix=url_prefix)
        self._registered_blueprints.append({
            'plugin': _require_ctx().name if _current_plugin.get() else '?',
            'blueprint': getattr(bp, 'name', str(bp)),
            'url_prefix': url_prefix,
        })

    def start_subprocess(self, *args: Any, **kwargs: Any) -> subprocess.Popen:
        """Spawn a subprocess owned by the current plugin.

        The returned :class:`subprocess.Popen` is also tracked by the
        manager so it can be terminated on plugin disable / app shutdown.
        """
        proc = subprocess.Popen(*args, **kwargs)
        ctx_name = _require_ctx().name if _current_plugin.get() else None
        if ctx_name:
            # Lazy import to avoid circular dependency
            from .manager import get_plugin_manager
            mgr = get_plugin_manager()
            if mgr is not None:
                mgr._track_subprocess(ctx_name, proc)  # type: ignore[attr-defined]
        return proc

    # ------------------------------------------------------------------ #
    # Diagnostics
    # ------------------------------------------------------------------ #

    def registered_blueprints(self) -> List[Dict[str, Any]]:
        """Return a copy of the blueprint registry (for /api/plugins diagnostics)."""
        return list(self._registered_blueprints)


# ── Module-level singleton ──────────────────────────────────────────

#: Import this from any plugin to access host services::
#:
#:     from plugin_system.api import plugin_api
plugin_api = PluginAPI()


__all__ = ['PluginAPI', 'PluginContext', 'plugin_api']

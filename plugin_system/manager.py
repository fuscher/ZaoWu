"""PluginManager — the orchestrator of plugin lifecycle.

The manager is the single entry point the host uses to interact with the
plugin system.  It owns:

* **Discovery & loading** — delegates to :mod:`plugin_system.loader`.
* **State persistence** — ``plugins/.plugin_state.json`` records which
  plugins are enabled and any user config overrides.
* **Lifecycle transitions** — ``load → enable → disable → unload`` with
  hook dispatch at each step.
* **Hook invocation** — binds the per-plugin :class:`PluginContext` via
  :class:`contextvars.ContextVar` so ``plugin_api.config`` / ``.logger``
  resolve correctly inside every hook.
* **Subprocess tracking** — every subprocess started by a plugin is
  remembered so it can be terminated on disable / shutdown.
* **Aggregate queries** — convenience methods for the host to fetch
  sidebar panels, settings sections, etc. from all enabled plugins.

The host integration is exactly three calls:

    mgr = PluginManager(plugins_dir)
    mgr.attach_app(app)            # before server starts
    await mgr.load_all()           # during before_serving
    ...
    await mgr.shutdown_hooks()     # during after_serving

A module-level singleton is exposed via :func:`get_plugin_manager` so
plugin code (and :mod:`plugin_system.api`) can reach it without imports
of the Quart app.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import hooks as _hooks
from .api import PluginAPI, PluginContext, plugin_api
from .bus import event_bus
from .exceptions import (
    PluginError,
    PluginLoadError,
    PluginNotFoundError,
    PluginStateError,
)
from .loader import DiscoveredPlugin, discover, unload_plugin
from .schema import Manifest, CURRENT_API_VERSION

logger = logging.getLogger('plugin_system.manager')


STATE_VERSION = 1
STATE_FILENAME = '.plugin_state.json'


# ── Per-plugin runtime record ───────────────────────────────────────

@dataclass
class PluginRecord:
    """Everything the manager knows about a loaded plugin.

    ``discovered`` carries the static info (manifest + module); the
    remaining fields track runtime state that can change across
    enable/disable cycles without reloading the module.
    """

    discovered: DiscoveredPlugin
    ctx: PluginContext
    enabled: bool = False
    # Subprocesses spawned by this plugin (tracked for cleanup)
    subprocesses: List[Any] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.discovered.name

    @property
    def module(self) -> Any:
        return self.discovered.module

    @property
    def manifest(self) -> Manifest:
        # Safe: loader only constructs records for plugins with a manifest
        assert self.discovered.manifest is not None
        return self.discovered.manifest


# ── Broken-plugin record (manifest/import failed) ───────────────────

@dataclass
class BrokenPlugin:
    """A plugin that could not be loaded but is still reported in the list."""

    name: str
    path: str
    error: str


# ── Manager ─────────────────────────────────────────────────────────


class PluginManager:
    """Singleton-ish manager (one instance per process is recommended).

    Construction is cheap; the heavy work happens in :meth:`load_all`.
    """

    def __init__(self, plugins_dir: str) -> None:
        self.plugins_dir = os.path.abspath(plugins_dir)
        self._state_path = os.path.join(self.plugins_dir, STATE_FILENAME)

        self._records: Dict[str, PluginRecord] = {}    # name -> record (loaded)
        self._broken: Dict[str, BrokenPlugin] = {}     # name -> broken entry
        self._lock = threading.RLock()                  # guards state file writes
        self._app: Any = None
        self._started = False
        # Whether load_all() has run — guards against double init.
        self._loaded = False

    # ------------------------------------------------------------------ #
    # Wiring
    # ------------------------------------------------------------------ #

    def attach_app(self, app: Any) -> None:
        """Bind the Quart app so plugins can register blueprints later."""
        self._app = app
        plugin_api.attach_app(app)

    # ------------------------------------------------------------------ #
    # State persistence
    # ------------------------------------------------------------------ #

    def _read_state(self) -> Dict[str, Any]:
        if not os.path.isfile(self._state_path):
            return {'version': STATE_VERSION, 'plugins': {}}
        try:
            with open(self._state_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning('plugin state file unreadable (%s); starting fresh', exc)
            return {'version': STATE_VERSION, 'plugins': {}}
        if not isinstance(data, dict) or 'plugins' not in data:
            return {'version': STATE_VERSION, 'plugins': {}}
        return data

    def _write_state(self, data: Dict[str, Any]) -> None:
        os.makedirs(self.plugins_dir, exist_ok=True)
        tmp = self._state_path + '.tmp'
        with self._lock:
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self._state_path)
            except OSError as exc:
                logger.error('failed to persist plugin state: %s', exc)

    def _state_for(self, name: str) -> Dict[str, Any]:
        data = self._read_state()
        return data.get('plugins', {}).get(name, {})

    def _save_plugin_state(self, name: str, enabled: bool, config: Dict[str, Any]) -> None:
        data = self._read_state()
        data.setdefault('plugins', {})[name] = {
            'enabled': enabled,
            'config': dict(config),
        }
        self._write_state(data)

    def _drop_plugin_state(self, name: str) -> None:
        data = self._read_state()
        if name in data.get('plugins', {}):
            data['plugins'].pop(name)
            self._write_state(data)

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #

    async def load_all(self) -> Tuple[int, int]:
        """Discover, import, and initialise every plugin on disk.

        Returns ``(loaded_count, broken_count)``.  Broken plugins are
        recorded but do not abort the scan.
        """
        if self._loaded:
            logger.warning('PluginManager.load_all() called twice; ignoring')
            return 0, 0
        self._loaded = True

        discovered = discover(self.plugins_dir)
        state = self._read_state()
        plugins_state = state.get('plugins', {})

        loaded = 0
        broken = 0

        # Store the main event loop reference so hooks fired from
        # sync threads can use call_soon_threadsafe() to reach it.
        self._main_loop = asyncio.get_running_loop()
        for d in discovered:
            if not d.ok:
                self._broken[d.name] = BrokenPlugin(
                    name=d.name, path=d.path, error=d.error or 'unknown error',
                )
                logger.error('plugin %s broken: %s', d.name, d.error)
                broken += 1
                continue

            # API version compatibility check (fail-open on parse errors)
            manifest = d.manifest
            assert manifest is not None
            if not manifest.api_compatible(CURRENT_API_VERSION):
                logger.warning(
                    'plugin %s requires API %s (runtime %s); loaded anyway, may break',
                    d.name, manifest.min_api_version, CURRENT_API_VERSION,
                )

            # Resolve effective enabled flag & config:
            #   manifest.enabled  ->  state file  ->  default
            saved = plugins_state.get(d.name, {})
            user_config = saved.get('config', {})
            effective_config = {**manifest.config, **user_config}
            effective_enabled = bool(saved.get('enabled', manifest.enabled))

            ctx = PluginContext(
                name=d.name,
                config=effective_config,
            )
            plugin_api.register_context(ctx)

            record = PluginRecord(
                discovered=d,
                ctx=ctx,
                enabled=False,  # set to True by enable() below
            )
            self._records[d.name] = record

            # Fire zaowu_plugin_loaded (always — module is freshly imported)
            await self._invoke(record, 'zaowu_plugin_loaded')

            if effective_enabled:
                try:
                    await self.enable(d.name, persist=False)
                except PluginError as exc:
                    logger.error('plugin %s failed to enable on load: %s', d.name, exc)
                    # Leave it loaded but disabled.
            loaded += 1

        logger.info('plugin load complete: %d loaded, %d broken', loaded, broken)
        return loaded, broken

    async def reload(self, name: str) -> None:
        """Unload and re-import a plugin by name (hot reload).

        Useful during development.  The plugin's enabled state and user
        config are preserved across the reload.
        """
        record = self._records.get(name)
        if record is None:
            raise PluginNotFoundError(f'cannot reload unknown plugin {name!r}')

        was_enabled = record.enabled
        saved_config = dict(record.ctx.config)

        # 1. Disable + unload module
        if was_enabled:
            await self.disable(name, persist=False)
        unload_plugin(name)
        plugin_api.drop_context(name)
        self._records.pop(name, None)

        # 2. Re-discover this single plugin
        from .loader import _discover_one
        plugin_path = record.discovered.path
        d = _discover_one(name, plugin_path)
        if not d.ok:
            self._broken[name] = BrokenPlugin(name=name, path=plugin_path, error=d.error or 'reload failed')
            raise PluginLoadError(f'reload of {name!r} failed: {d.error}')

        # 3. Re-register context
        ctx = PluginContext(name=name, config=saved_config)
        plugin_api.register_context(ctx)
        new_record = PluginRecord(discovered=d, ctx=ctx, enabled=False)
        self._records[name] = new_record
        self._broken.pop(name, None)

        await self._invoke(new_record, 'zaowu_plugin_loaded')
        if was_enabled:
            await self.enable(name, persist=False)

        logger.info('plugin %s reloaded', name)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def enable(self, name: str, persist: bool = True) -> None:
        """Enable a loaded plugin.

        Calls ``zaowu_plugin_enabled``; the hook may return ``False`` to
        veto the transition (e.g. missing external dependency).
        """
        record = self._records.get(name)
        if record is None:
            raise PluginNotFoundError(f'cannot enable unknown plugin {name!r}')
        if record.enabled:
            return  # idempotent

        call = await self._invoke(record, 'zaowu_plugin_enabled')
        if call.ok and call.value is False:
            raise PluginStateError(f'plugin {name!r} refused to be enabled')

        record.enabled = True
        if persist:
            self._save_plugin_state(name, enabled=True, config=record.ctx.config)
        logger.info('plugin %s enabled', name)

    async def disable(self, name: str, persist: bool = True) -> None:
        """Disable an enabled plugin.

        Calls ``zaowu_plugin_disabled`` (may veto), then:
        - terminates subprocesses owned by the plugin,
        - unsubscribes the plugin from the event bus,
        - persists state.
        """
        record = self._records.get(name)
        if record is None:
            raise PluginNotFoundError(f'cannot disable unknown plugin {name!r}')
        if not record.enabled:
            return  # idempotent

        call = await self._invoke(record, 'zaowu_plugin_disabled')
        if call.ok and call.value is False:
            raise PluginStateError(f'plugin {name!r} refused to be disabled')

        record.enabled = False
        self._kill_subprocesses(name)
        event_bus.unsubscribe_all(name)
        if persist:
            self._save_plugin_state(name, enabled=False, config=record.ctx.config)
        logger.info('plugin %s disabled', name)

    async def unload(self, name: str) -> None:
        """Fully remove a plugin: disable, drop context, unload module.

        Does **not** delete the plugin directory — that is "uninstall"
        and is intentionally a separate operation (see :meth:`uninstall`).
        """
        record = self._records.get(name)
        if record is None:
            raise PluginNotFoundError(f'cannot unload unknown plugin {name!r}')

        if record.enabled:
            await self.disable(name, persist=False)

        plugin_api.drop_context(name)
        unload_plugin(name)
        self._records.pop(name, None)
        self._drop_plugin_state(name)
        logger.info('plugin %s unloaded', name)

    async def uninstall(self, name: str) -> None:
        """Disable, unload, and move the plugin folder to ``<name>.disabled``.

        The folder is renamed rather than deleted so the user can recover
        their plugin.  To fully remove it, delete the renamed folder.
        """
        record = self._records.get(name)
        plugin_path = record.discovered.path if record else os.path.join(self.plugins_dir, name)

        if record is not None:
            await self.unload(name)

        if os.path.isdir(plugin_path):
            disabled_path = plugin_path + '.disabled'
            # Avoid clashing with a previous .disabled folder
            i = 1
            while os.path.exists(disabled_path):
                disabled_path = f'{plugin_path}.disabled.{i}'
                i += 1
            try:
                os.rename(plugin_path, disabled_path)
                logger.info('plugin %s uninstalled (folder renamed to %s)', name, disabled_path)
            except OSError as exc:
                logger.error('failed to rename plugin folder %s: %s', plugin_path, exc)
                raise PluginStateError(f'cannot uninstall {name!r}: {exc}') from exc

    # ------------------------------------------------------------------ #
    # Host lifecycle hooks
    # ------------------------------------------------------------------ #

    async def startup_hooks(self) -> None:
        """Invoke ``zaowu_app_startup`` on every enabled plugin."""
        self._started = True
        await self._invoke_all_enabled('zaowu_app_startup')

    async def shutdown_hooks(self) -> None:
        """Invoke ``zaowu_app_shutdown`` on every enabled plugin & cleanup."""
        try:
            await self._invoke_all_enabled('zaowu_app_shutdown')
        finally:
            # Kill any lingering subprocesses
            for name in list(self._records.keys()):
                self._kill_subprocesses(name)
            self._started = False

    # ------------------------------------------------------------------ #
    # Aggregate hook queries (used by host routes / frontend)
    # ------------------------------------------------------------------ #

    async def collect_sidebar_panels(self) -> List[Dict[str, Any]]:
        return await self._aggregate('zaowu_sidebar_panels')

    async def collect_activity_bar_actions(self) -> List[Dict[str, Any]]:
        return await self._aggregate('zaowu_activity_bar_actions')

    async def collect_settings_sections(self) -> List[Dict[str, Any]]:
        return await self._aggregate('zaowu_settings_sections')

    async def collect_status_bar_items(self) -> List[Dict[str, Any]]:
        return await self._aggregate('zaowu_status_bar_items')

    async def collect_detail_sections(self) -> List[Dict[str, Any]]:
        """Collect plugin-contributed sections for the plugin detail page."""
        return await self._aggregate('zaowu_plugin_detail_sections')

    async def collect_routes(self) -> List[Any]:
        """Invoke ``zaowu_register_routes`` on every enabled plugin.

        Plugins are expected to call ``plugin_api.register_blueprint``
        inside this hook; the return value (a list of Blueprints) is
        also accepted as a fallback and registered automatically.
        """
        calls = await self._invoke_all_enabled('zaowu_register_routes')
        for call in calls:
            if not call.ok or not call.value:
                continue
            blueprints = call.value if isinstance(call.value, list) else [call.value]
            for bp in blueprints:
                try:
                    plugin_api.register_blueprint(bp)
                except Exception as exc:  # noqa: BLE001
                    logger.error('plugin %s blueprint registration failed: %s', call.plugin_name, exc)
        return _hooks.merge_aggregated(calls)

    async def collect_ws_message_types(self) -> List[str]:
        result = await self._aggregate('zaowu_ws_message_types')
        # Flatten nested lists if any
        flat: List[str] = []
        for item in result:
            if isinstance(item, str):
                flat.append(item)
            elif isinstance(item, list):
                flat.extend(str(x) for x in item)
        return flat

    async def collect_agent_tools(self) -> List[Any]:
        """Invoke ``zaowu_register_agent_tools`` on every enabled plugin.

        Plugins are expected to return a list of :class:`ToolDefinition`
        objects (or anything exposing ``name``, ``description``,
        ``parameters`` and ``handler``).  Invalid items are logged and
        skipped so one misbehaving plugin cannot break the host.
        """
        calls = await self._invoke_all_enabled('zaowu_register_agent_tools')
        merged = _hooks.merge_aggregated(calls)
        valid: List[Any] = []
        for tool in merged:
            missing = [
                attr for attr in ('name', 'description', 'parameters', 'handler')
                if not hasattr(tool, attr)
            ]
            if missing:
                logger.warning(
                    'plugin agent tool skipped: missing attributes %s', missing,
                )
                continue
            if not callable(tool.handler):
                logger.warning(
                    'plugin agent tool %r skipped: handler is not callable',
                    tool.name,
                )
                continue
            valid.append(tool)
        return valid

    async def dispatch_ws_message(self, msg_type: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Forward a custom WS message to plugins that declared the type.

        The first plugin that returns a non-None dict wins; subsequent
        plugins are still called for side effects but their return value
        is ignored.  Returns the broadcast payload or ``None``.
        """
        declared = await self.collect_ws_message_types()
        if msg_type not in declared:
            return None

        result: Optional[Dict[str, Any]] = None
        for record in self._enabled_records():
            call = await self._invoke(
                record, 'zaowu_handle_ws_message',
                args=(msg_type, payload),
            )
            if call.ok and call.value is not None and result is None:
                result = call.value
        return result

    # ------------------------------------------------------------------ #
    # Introspection (for the management REST API)
    # ------------------------------------------------------------------ #

    def list_plugins(self) -> List[Dict[str, Any]]:
        """Return a serialisable description of every known plugin."""
        out: List[Dict[str, Any]] = []
        for name, record in self._records.items():
            m = record.manifest
            out.append({
                'name': name,
                'version': m.version,
                'description': dict(m.description),
                'author': m.author,
                'minApiVersion': m.min_api_version,
                'enabled': record.enabled,
                'loaded': True,
                'path': record.discovered.path,
                'config': dict(record.ctx.config),
                'error': None,
            })
        for name, broken in self._broken.items():
            out.append({
                'name': name,
                'version': '',
                'description': {},
                'author': '',
                'minApiVersion': '',
                'enabled': False,
                'loaded': False,
                'path': broken.path,
                'config': {},
                'error': broken.error,
            })
        out.sort(key=lambda p: p['name'].lower())
        return out

    def get_plugin(self, name: str) -> Optional[Dict[str, Any]]:
        for p in self.list_plugins():
            if p['name'] == name:
                return p
        return None

    def update_config(self, name: str, config: Dict[str, Any]) -> None:
        """Replace a plugin's user-overridden config and persist it."""
        record = self._records.get(name)
        if record is None:
            raise PluginNotFoundError(f'cannot configure unknown plugin {name!r}')
        record.ctx.config = dict(config)
        self._save_plugin_state(name, enabled=record.enabled, config=record.ctx.config)
        logger.info('plugin %s config updated', name)

    # ------------------------------------------------------------------ #
    # Subprocess tracking (called by PluginAPI.start_subprocess)
    # ------------------------------------------------------------------ #

    def _track_subprocess(self, name: str, proc: Any) -> None:
        record = self._records.get(name)
        if record is None:
            return
        record.subprocesses.append(proc)

    def _kill_subprocesses(self, name: str) -> None:
        record = self._records.get(name)
        if record is None:
            return
        for proc in record.subprocesses:
            try:
                if proc.poll() is None:  # still running
                    proc.terminate()
            except Exception:  # noqa: BLE001
                logger.debug('subprocess terminate failed for %s', name, exc_info=True)
        record.subprocesses.clear()

    # ------------------------------------------------------------------ #
    # Hook invocation internals
    # ------------------------------------------------------------------ #

    def _enabled_records(self) -> List[PluginRecord]:
        return [r for r in self._records.values() if r.enabled]

    async def _invoke(self, record: PluginRecord, hook_name: str, *, args: tuple = ()) -> _hooks.HookCall:
        """Invoke a hook on a single plugin with ContextVar binding."""
        token = plugin_api.bind_context(record.ctx)
        try:
            return await _hooks.invoke_hook(
                record.module, record.name, hook_name,
                args=args,
                # No inject_self: function-style plugins use plugin_api;
                # class-style plugins receive `self` via their own __init__.
            )
        finally:
            plugin_api.reset_context(token)

    async def _invoke_all_enabled(self, hook_name: str, *, args: tuple = ()) -> List[_hooks.HookCall]:
        """Invoke a hook on every enabled plugin. Order is load order."""
        calls: List[_hooks.HookCall] = []
        for record in self._enabled_records():
            call = await self._invoke(record, hook_name, args=args)
            calls.append(call)
        return calls

    async def _aggregate(self, hook_name: str) -> List[Any]:
        """Invoke an aggregate hook and return the merged list.

        Injects ``pluginName`` into every dict item so the frontend can
        look up the corresponding Vue component via PluginHost.
        String / non-dict items are left untouched (they come from hooks
        like ``zaowu_ws_message_types`` that return simple type names).
        """
        calls = await self._invoke_all_enabled(hook_name)
        merged = _hooks.merge_aggregated(calls)
        for call in calls:
            if call.ok and isinstance(call.value, list):
                for item in call.value:
                    if isinstance(item, dict):
                        item['pluginName'] = call.plugin_name
        return merged

    async def fire_hook(self, hook_name: str, *args: Any) -> None:
        """Fire a non-aggregate hook on every enabled plugin.

        Public API for host code that needs to trigger plugin hooks
        (e.g. file-saved, user-joined).  Errors are isolated — a
        failing plugin never takes down the host or other plugins.

        Usage::

            mgr = get_plugin_manager()
            if mgr is not None:
                await mgr.fire_hook('zaowu_on_file_saved', file_path)
        """
        for record in self._enabled_records():
            await self._invoke(record, hook_name, args=args)


# ── Module-level singleton accessor ─────────────────────────────────

_singleton: Optional[PluginManager] = None
_singleton_lock = threading.Lock()


def get_plugin_manager() -> Optional[PluginManager]:
    """Return the process-wide :class:`PluginManager`, or ``None`` if unset."""
    return _singleton


def set_plugin_manager(mgr: PluginManager) -> None:
    """Install ``mgr`` as the process-wide singleton (called once at boot)."""
    global _singleton
    with _singleton_lock:
        _singleton = mgr


__all__ = [
    'PluginManager',
    'PluginRecord',
    'BrokenPlugin',
    'get_plugin_manager',
    'set_plugin_manager',
]

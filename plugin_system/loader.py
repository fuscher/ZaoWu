"""Plugin discovery and dynamic loading.

The loader is the *only* module that knows how to find a plugin on disk
and turn it into a Python module object.  It is intentionally split from
:mod:`plugin_system.manager` so that:

* Discovery (filesystem scan) can be tested without a manager.
* Import errors are reported uniformly via :class:`DiscoveredPlugin`.
* The manager focuses on lifecycle, not on filesystem details.

Loading contract
----------------
A directory ``plugins/<name>/`` is considered a *candidate* plugin iff:

1. It is a directory (not a file).
2. Its name does not start with ``.`` or ``_``.
3. It contains a ``manifest.json`` file.
4. It contains an ``__init__.py`` file.

If (1) or (2) fail, the entry is silently skipped.  If (3) or (4) fail,
the entry is recorded as a *broken* candidate with an error message so
the user can see what went wrong in the management UI.

Each successfully imported plugin module is registered in
``sys.modules`` under a synthetic name ``zaowu_plugin_<name>`` to:

* Avoid clashing with real top-level packages.
* Make it possible to ``importlib.reload`` a plugin by name.
* Give plugins a stable identity for ``__name__`` introspection.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .exceptions import PluginLoadError, PluginManifestError
from .schema import Manifest

logger = logging.getLogger('plugin_system.loader')


# Prefix used when registering plugin modules in sys.modules.
MODULE_PREFIX = 'zaowu_plugin_'


@dataclass
class DiscoveredPlugin:
    """Result of scanning a single plugin directory.

    ``module`` is ``None`` if either the manifest or the import failed;
    consult ``error`` for the reason.  The manager uses this to decide
    whether to keep the plugin in the loaded set or report it as broken.
    """

    name: str
    path: str
    manifest: Optional[Manifest] = None
    module: Any = None
    error: Optional[str] = None
    # Whether the plugin actually made it into sys.modules
    registered: bool = False

    @property
    def ok(self) -> bool:
        return self.manifest is not None and self.module is not None and self.error is None


# ── Discovery ───────────────────────────────────────────────────────


def discover(plugins_dir: str) -> List[DiscoveredPlugin]:
    """Scan ``plugins_dir`` for plugin candidates.

    Returns a list of :class:`DiscoveredPlugin` entries — one per
    subdirectory that looks like a plugin.  Broken candidates (missing
    manifest or ``__init__.py``) are included with ``error`` set so the
    caller can surface them to the user.
    """
    results: List[DiscoveredPlugin] = []
    if not os.path.isdir(plugins_dir):
        logger.debug('plugins directory does not exist: %s', plugins_dir)
        return results

    try:
        entries = sorted(os.scandir(plugins_dir), key=lambda e: e.name.lower())
    except OSError as exc:
        logger.error('cannot scan plugins directory %s: %s', plugins_dir, exc)
        return results

    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        name = entry.name
        if name.startswith('.') or name.startswith('_'):
            continue

        plugin_path = entry.path
        discovered = _discover_one(name, plugin_path)
        results.append(discovered)

    return results


def _discover_one(name: str, plugin_path: str) -> DiscoveredPlugin:
    """Inspect a single plugin directory and try to load it."""
    manifest_path = os.path.join(plugin_path, 'manifest.json')
    init_path = os.path.join(plugin_path, '__init__.py')

    if not os.path.isfile(manifest_path):
        return DiscoveredPlugin(
            name=name, path=plugin_path,
            error=f'missing manifest.json',
        )
    if not os.path.isfile(init_path):
        return DiscoveredPlugin(
            name=name, path=plugin_path,
            error=f'missing __init__.py',
        )

    # 1. Parse manifest
    try:
        manifest = Manifest.from_file(manifest_path)
    except PluginManifestError as exc:
        return DiscoveredPlugin(name=name, path=plugin_path, error=str(exc))

    # The directory name should match the manifest name.  If they
    # differ, trust the manifest (it is the source of truth) but log a
    # warning so users notice the mismatch.
    if manifest.name != name:
        logger.warning(
            'plugin directory %r does not match manifest name %r; using manifest name',
            name, manifest.name,
        )

    # 2. Import the module
    module_name = MODULE_PREFIX + manifest.name
    try:
        module = _import_plugin_module(module_name, init_path, manifest.name)
    except PluginLoadError as exc:
        return DiscoveredPlugin(name=manifest.name, path=plugin_path, manifest=manifest, error=str(exc))

    return DiscoveredPlugin(
        name=manifest.name,
        path=plugin_path,
        manifest=manifest,
        module=module,
        registered=True,
    )


# ── Import ──────────────────────────────────────────────────────────


def _import_plugin_module(module_name: str, init_path: str, plugin_name: str) -> Any:
    """Import a plugin's ``__init__.py`` as ``zaowu_plugin_<name>``.

    Raises :class:`PluginLoadError` on any failure so the caller can
    record the message without a traceback leaking into logs.
    """
    # If already loaded (e.g. manager is re-scanning), unload first so
    # we pick up the latest source.  This is the "reload" path.
    if module_name in sys.modules:
        _unload_module(module_name)

    try:
        spec = importlib.util.spec_from_file_location(module_name, init_path)
    except (ValueError, ImportError, OSError) as exc:
        raise PluginLoadError(f'cannot create import spec for {plugin_name}: {exc}') from exc

    if spec is None or spec.loader is None:
        raise PluginLoadError(f'importlib returned no spec for {plugin_name}')

    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules *before* exec so the plugin's own code can
    # import itself by name (e.g. ``from zaowu_plugin_myplugin import util``).
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — capture any plugin-side error
        # Roll back the sys.modules entry so a retry is clean.
        sys.modules.pop(module_name, None)
        raise PluginLoadError(f'plugin {plugin_name!r} raised during import: {exc}') from exc

    logger.debug('loaded plugin module %s from %s', module_name, init_path)
    return module


def _unload_module(module_name: str) -> None:
    """Remove a previously imported plugin module from ``sys.modules``."""
    mod = sys.modules.pop(module_name, None)
    if mod is not None and hasattr(mod, '__name__'):
        logger.debug('unloaded plugin module %s', module_name)


def unload_plugin(plugin_name: str) -> bool:
    """Unload a plugin's module by its manifest name.

    Returns ``True`` if a module was actually removed.  The manager
    calls this during disable/uninstall to release references.
    """
    return _unload_module_returned(MODULE_PREFIX + plugin_name)


def _unload_module_returned(module_name: str) -> bool:
    if module_name in sys.modules:
        _unload_module(module_name)
        return True
    return False


def get_module_name(plugin_name: str) -> str:
    """Return the synthetic ``sys.modules`` key for a plugin."""
    return MODULE_PREFIX + plugin_name


def is_loaded(plugin_name: str) -> bool:
    """Check whether a plugin module is currently in ``sys.modules``."""
    return get_module_name(plugin_name) in sys.modules


__all__ = [
    'DiscoveredPlugin',
    'MODULE_PREFIX',
    'discover',
    'unload_plugin',
    'get_module_name',
    'is_loaded',
]

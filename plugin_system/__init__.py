"""ZaoWu plugin system.

A lightweight, folder-based plugin framework.  Dropping a directory
containing ``manifest.json`` + ``__init__.py`` into ``plugins/`` is all
that is required to install a plugin.

Public surface
--------------
* :class:`PluginManager`      — orchestrator (host side)
* :func:`get_plugin_manager`  — process-wide accessor
* :data:`plugin_api`          — service API singleton (plugin side)
* :data:`event_bus`           — inter-plugin pub/sub
* :class:`Manifest`           — manifest data model
* :data:`HOOK_NAMES`          — recognised hook names

See ``plugins/PLUGIN_SYSTEM.md`` for the full design document.
"""

from .api import PluginAPI, PluginContext, plugin_api
from .bus import EventBus, event_bus
from .exceptions import (
    PluginError,
    PluginHookError,
    PluginLoadError,
    PluginManifestError,
    PluginNotFoundError,
    PluginStateError,
)
from .hooks import HOOK_NAMES, AGGREGATE_HOOKS, HookCall, invoke_all, invoke_hook, merge_aggregated
from .loader import DiscoveredPlugin, discover, unload_plugin
from .manager import (
    BrokenPlugin,
    PluginManager,
    PluginRecord,
    get_plugin_manager,
    set_plugin_manager,
)
from .schema import CURRENT_API_VERSION, Manifest

__version__ = '1.0.0'

__all__ = [
    # Manager
    'PluginManager',
    'PluginRecord',
    'BrokenPlugin',
    'get_plugin_manager',
    'set_plugin_manager',
    # API
    'PluginAPI',
    'PluginContext',
    'plugin_api',
    # Bus
    'EventBus',
    'event_bus',
    # Hooks
    'HOOK_NAMES',
    'AGGREGATE_HOOKS',
    'HookCall',
    'invoke_hook',
    'invoke_all',
    'merge_aggregated',
    # Loader
    'DiscoveredPlugin',
    'discover',
    'unload_plugin',
    # Schema
    'Manifest',
    'CURRENT_API_VERSION',
    # Exceptions
    'PluginError',
    'PluginNotFoundError',
    'PluginLoadError',
    'PluginManifestError',
    'PluginStateError',
    'PluginHookError',
]

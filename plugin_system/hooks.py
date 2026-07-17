"""Hook specifications and dispatcher.

ZaoWu plugins integrate with the host by defining functions whose names
match a known hook.  This module is the single source of truth for:

1. The set of recognised hook names (``HOOK_NAMES``).
2. The calling convention for each hook (return type, sync/async).
3. A dispatcher (:func:`invoke_hook`) that:

   - Looks up the hook function on a plugin module.
   - Awaits coroutines and calls regular functions synchronously.
   - Wraps every call in ``try/except`` so one plugin's failure never
     propagates to the host or to sibling plugins (isolation).
   - Accepts a ``self``/``plugin_api`` argument when the plugin opts in
     to the service API (see :mod:`plugin_system.api`).

Hook functions are discovered *purely by name* — no decorators, no base
class required.  If a plugin does not define a hook, it is simply skipped.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from .exceptions import PluginHookError

logger = logging.getLogger('plugin_system.hooks')


# ── Hook catalogue ──────────────────────────────────────────────────

#: All recognised hook names.  Adding a name here is the only change
#: required to introduce a new hook — the dispatcher handles the rest.
HOOK_NAMES: Tuple[str, ...] = (
    # Lifecycle
    'zaowu_plugin_loaded',      # after the plugin module is imported
    'zaowu_plugin_enabled',     # when the user enables the plugin  -> bool
    'zaowu_plugin_disabled',    # when the user disables the plugin -> bool
    'zaowu_app_startup',        # host application finished starting
    'zaowu_app_shutdown',       # host application is about to stop
    # HTTP / ASGI
    'zaowu_register_routes',    # return list[Blueprint]
    'zaowu_mount_asgi_middleware',  # advanced: mutate middleware chain
    # Frontend extension points
    'zaowu_sidebar_panels',     # -> list[dict]
    'zaowu_activity_bar_actions',  # -> list[dict]
    'zaowu_settings_sections',  # -> list[dict]
    'zaowu_status_bar_items',   # -> list[dict]
    'zaowu_plugin_detail_sections',  # -> list[dict]
    # WebSocket / collaboration
    'zaowu_ws_message_types',   # -> list[str]
    'zaowu_handle_ws_message',  # -> dict | None
    'zaowu_resolve_host_address',  # -> str | None
    # Filesystem events
    'zaowu_on_user_joined',
    'zaowu_on_user_left',
    'zaowu_on_file_saved',
    'zaowu_on_file_deleted',
    'zaowu_on_file_renamed',
    # Agent tool registration
    'zaowu_register_agent_tools',
)

#: Hooks whose return value is collected from every plugin and merged
#: (e.g. panel lists are concatenated).  Other hooks' return values are
#: ignored — they are called purely for side effects.
AGGREGATE_HOOKS: Tuple[str, ...] = (
    'zaowu_sidebar_panels',
    'zaowu_activity_bar_actions',
    'zaowu_settings_sections',
    'zaowu_status_bar_items',
    'zaowu_plugin_detail_sections',
    'zaowu_register_routes',
    'zaowu_ws_message_types',
    'zaowu_register_agent_tools',
)


@dataclass(frozen=True)
class HookCall:
    """Result of a single hook invocation on a single plugin."""

    plugin_name: str
    hook_name: str
    ok: bool
    value: Any = None
    error: Optional[str] = None


# ── Dispatcher ──────────────────────────────────────────────────────


def _resolve_hook(module: Any, hook_name: str) -> Optional[Callable]:
    """Return the hook callable on ``module`` or ``None`` if absent."""
    fn = getattr(module, hook_name, None)
    if fn is None:
        return None
    if not callable(fn):
        logger.warning('plugin attribute %r is not callable; skipped', hook_name)
        return None
    return fn


async def _maybe_await(value: Any) -> Any:
    """Await ``value`` if it is awaitable, otherwise return it as-is."""
    if inspect.isawaitable(value):
        return await value
    return value


async def invoke_hook(
    module: Any,
    plugin_name: str,
    hook_name: str,
    *,
    args: tuple = (),
    kwargs: Optional[Dict[str, Any]] = None,
    inject_self: Any = None,
    default: Any = None,
) -> HookCall:
    """Invoke ``hook_name`` on ``module`` with full isolation.

    Args:
        module:        The imported plugin module (or instance).
        plugin_name:   Plugin identifier, used for logging only.
        hook_name:     One of :data:`HOOK_NAMES`.
        args:          Positional arguments forwarded to the hook.
        kwargs:        Keyword arguments forwarded to the hook.
        inject_self:   If not ``None``, prepended as the first positional
                       argument so the hook can receive a service API
                       object (``self``/``plugin_api``).
        default:       Value returned in :class:`HookCall.value` if the
                       plugin does not define the hook.

    Returns:
        A :class:`HookCall` describing the outcome.  Exceptions are
        logged and captured in ``HookCall.error``; they never propagate
        to the caller.
    """
    if hook_name not in HOOK_NAMES:
        raise ValueError(f'unknown hook name: {hook_name!r}')

    fn = _resolve_hook(module, hook_name)
    if fn is None:
        return HookCall(plugin_name, hook_name, ok=True, value=default)

    call_args = args
    if inject_self is not None:
        call_args = (inject_self,) + tuple(args)
    if kwargs is None:
        kwargs = {}

    try:
        result = fn(*call_args, **kwargs)
        result = await _maybe_await(result)
    except Exception as exc:  # noqa: BLE001 — intentional broad catch for isolation
        logger.exception('plugin %r hook %r raised', plugin_name, hook_name)
        return HookCall(plugin_name, hook_name, ok=False, error=str(exc))
    return HookCall(plugin_name, hook_name, ok=True, value=result)


async def invoke_all(
    plugins: Dict[str, Any],
    hook_name: str,
    *,
    args: tuple = (),
    kwargs: Optional[Dict[str, Any]] = None,
    inject_self_factory: Optional[Callable[[str], Any]] = None,
    aggregate: bool = False,
) -> List[HookCall]:
    """Invoke ``hook_name`` on every loaded plugin module.

    Args:
        plugins:              Mapping of plugin name -> module.
        hook_name:            Hook to invoke.
        args/kwargs:          Forwarded to each hook.
        inject_self_factory:  Callable that receives a plugin name and
                              returns the object to inject as the first
                              positional argument (or ``None`` to skip
                              injection for that plugin).
        aggregate:            If ``True`` (or the hook is in
                              :data:`AGGREGATE_HOOKS`), each result's
                              ``value`` is expected to be a list and the
                              merged list is available via
                              :func:`merge_aggregated`.

    Returns:
        List of :class:`HookCall`, one per plugin that defined the hook
        (plugins without the hook are still included with their default
        value so callers can see who was asked).
    """
    if hook_name not in HOOK_NAMES:
        raise ValueError(f'unknown hook name: {hook_name!r}')

    do_aggregate = aggregate or hook_name in AGGREGATE_HOOKS
    calls: List[HookCall] = []
    for name, module in plugins.items():
        inject_self = inject_self_factory(name) if inject_self_factory else None
        default: Any = [] if do_aggregate else None
        call = await invoke_hook(
            module, name, hook_name,
            args=args, kwargs=kwargs,
            inject_self=inject_self,
            default=default,
        )
        calls.append(call)
    return calls


def merge_aggregated(calls: List[HookCall]) -> List[Any]:
    """Concatenate the ``value`` lists of successful aggregate calls.

    Failed calls contribute nothing.  Non-list values are wrapped in a
    single-element list so a hook that returns a bare value still works.
    """
    merged: List[Any] = []
    for call in calls:
        if not call.ok or call.value is None:
            continue
        if isinstance(call.value, list):
            merged.extend(call.value)
        else:
            merged.append(call.value)
    return merged


__all__ = [
    'HOOK_NAMES',
    'AGGREGATE_HOOKS',
    'HookCall',
    'invoke_hook',
    'invoke_all',
    'merge_aggregated',
]

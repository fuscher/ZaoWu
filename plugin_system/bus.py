"""Lightweight event bus for plugin-to-plugin communication.

The host itself never publishes on this bus — it is purely a peer-to-peer
channel that plugins opt into.  This keeps the host decoupled: adding a
new event type requires no host changes.

Two flavours of subscription are supported:

* **Sync handlers** — invoked inline by :meth:`EventBus.publish`.
  Use only for cheap, non-blocking work.
* **Async handlers** — scheduled on the current event loop via
  :func:`asyncio.ensure_future`.  They run concurrently with the
  publisher and never block it.

Error isolation is preserved: a failing handler is logged and skipped;
it never propagates to the publisher or to sibling handlers.

Example
-------

    # plugin A
    from plugin_system.bus import event_bus
    def zaowu_plugin_loaded():
        event_bus.subscribe('myplugin.loaded', _on_other_loaded)

    # plugin B
    from plugin_system.bus import event_bus
    def zaowu_app_startup():
        event_bus.publish('myplugin.loaded', {'version': '1.0'})
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Tuple

logger = logging.getLogger('plugin_system.bus')


# A handler is either a sync callable or a coroutine function.
Handler = Callable[[Any], Any]


class EventBus:
    """In-process pub/sub bus with sync & async handler support."""

    def __init__(self) -> None:
        # event_name -> list of (handler, is_async, owner_plugin_name)
        self._subs: Dict[str, List[Tuple[Handler, bool, str]]] = defaultdict(list)
        self._lock = asyncio.Lock() if False else None  # reserved; not needed for in-memory dict

    # ------------------------------------------------------------------ #
    # Subscription
    # ------------------------------------------------------------------ #

    def subscribe(self, event_name: str, handler: Handler, owner: str = '?') -> None:
        """Register ``handler`` for ``event_name``.

        Both sync and async callables are accepted; the type is detected
        via :func:`inspect.iscoroutinefunction`.  If the same handler is
        registered twice for the same event, the second registration is
        ignored (deduplication by identity).
        """
        if not callable(handler):
            raise TypeError('handler must be callable')
        is_async = inspect.iscoroutinefunction(handler)
        entry = (handler, is_async, owner)
        bucket = self._subs[event_name]
        # Deduplicate by handler identity
        for existing in bucket:
            if existing[0] is handler:
                return
        bucket.append(entry)
        logger.debug('bus: %s subscribed to %r', owner, event_name)

    def unsubscribe(self, event_name: str, handler: Handler) -> bool:
        """Remove a previously registered handler. Returns ``True`` if removed."""
        bucket = self._subs.get(event_name)
        if not bucket:
            return False
        for i, (h, _a, _o) in enumerate(bucket):
            if h is handler:
                bucket.pop(i)
                if not bucket:
                    self._subs.pop(event_name, None)
                return True
        return False

    def unsubscribe_all(self, owner: str) -> int:
        """Remove every handler registered by ``owner``. Returns the count dropped."""
        dropped = 0
        for event_name in list(self._subs.keys()):
            bucket = self._subs[event_name]
            kept = [(h, a, o) for (h, a, o) in bucket if o != owner]
            dropped += len(bucket) - len(kept)
            if kept:
                self._subs[event_name] = kept
            else:
                self._subs.pop(event_name, None)
        if dropped:
            logger.debug('bus: dropped %d subscriptions owned by %s', dropped, owner)
        return dropped

    # ------------------------------------------------------------------ #
    # Publishing
    # ------------------------------------------------------------------ #

    def publish(self, event_name: str, payload: Any = None) -> int:
        """Dispatch ``event_name`` to all handlers.

        Sync handlers run inline (and may raise — caught and logged).
        Async handlers are scheduled on the running event loop via
        :func:`asyncio.ensure_future`.  If no loop is running, async
        handlers are skipped with a warning (sync handlers still run).

        Returns the number of handlers that were notified.
        """
        bucket = self._subs.get(event_name, [])
        if not bucket:
            return 0

        loop = self._get_running_loop()
        notified = 0
        for handler, is_async, owner in list(bucket):
            if is_async:
                if loop is None:
                    logger.warning(
                        'bus: async handler for %r owned by %s skipped (no running loop)',
                        event_name, owner,
                    )
                    continue
                task = loop.create_task(self._safe_async(handler, payload, owner, event_name))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            else:
                self._safe_sync(handler, payload, owner, event_name)
            notified += 1
        return notified

    async def publish_async(self, event_name: str, payload: Any = None) -> int:
        """Async variant that ``await``s every async handler to completion.

        Sync handlers still run inline.  Use this when callers need to
        know all handlers finished before proceeding.
        """
        bucket = self._subs.get(event_name, [])
        if not bucket:
            return 0
        notified = 0
        for handler, is_async, owner in list(bucket):
            if is_async:
                try:
                    await handler(payload)
                except Exception:  # noqa: BLE001
                    logger.exception('bus: async handler %r of %s failed for %r',
                                     getattr(handler, '__name__', handler), owner, event_name)
            else:
                self._safe_sync(handler, payload, owner, event_name)
            notified += 1
        return notified

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    def handlers(self, event_name: str) -> List[Tuple[str, bool, str]]:
        """Return ``(handler_name, is_async, owner)`` for each subscriber."""
        return [
            (getattr(h, '__name__', repr(h)), a, o)
            for (h, a, o) in self._subs.get(event_name, [])
        ]

    def event_names(self) -> List[str]:
        return sorted(self._subs.keys())

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_running_loop() -> 'asyncio.AbstractEventLoop | None':
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    @staticmethod
    def _safe_sync(handler: Handler, payload: Any, owner: str, event_name: str) -> None:
        try:
            handler(payload)
        except Exception:  # noqa: BLE001
            logger.exception('bus: sync handler %r of %s failed for %r',
                             getattr(handler, '__name__', handler), owner, event_name)

    @staticmethod
    async def _safe_async(handler: Handler, payload: Any, owner: str, event_name: str) -> None:
        try:
            await handler(payload)
        except Exception:  # noqa: BLE001
            logger.exception('bus: async handler %r of %s failed for %r',
                             getattr(handler, '__name__', handler), owner, event_name)


# Track background tasks so the GC doesn't cancel them mid-flight.
_background_tasks: set = set()


# Module-level singleton — same pattern as ``plugin_api``.
event_bus = EventBus()


__all__ = ['EventBus', 'event_bus']

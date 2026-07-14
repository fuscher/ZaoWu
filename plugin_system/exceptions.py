"""Exception types for the ZaoWu plugin system.

All plugin-related errors inherit from :class:`PluginError` so callers can
catch them with a single ``except``.  More specific subclasses allow the
manager to react differently (e.g. skip a broken plugin vs. reject a
duplicate name).
"""


class PluginError(Exception):
    """Base class for every plugin-system error."""


class PluginNotFoundError(PluginError):
    """Raised when an operation targets a plugin name that is not loaded."""


class PluginLoadError(PluginError):
    """Raised when a plugin's manifest or module cannot be loaded."""


class PluginManifestError(PluginError):
    """Raised when ``manifest.json`` is missing required fields or invalid."""


class PluginStateError(PluginError):
    """Raised when a lifecycle transition is illegal (e.g. enable twice)."""


class PluginHookError(PluginError):
    """Raised when a hook invocation fails and the caller wants the cause.

    The original exception is preserved in :attr:`__cause__` so it can be
    inspected without losing the plugin context.
    """

"""Manifest data model and validation.

A manifest is the only required piece of metadata for a plugin.  It is a
plain JSON file named ``manifest.json`` placed at the plugin root.  This
module parses it into a :class:`Manifest` dataclass and validates the
minimum contract:

  - ``name``        : non-empty string, matches ``^[A-Za-z0-9_]+$``
  - ``version``     : non-empty string (semantic version recommended)
  - ``description`` : dict of locale -> string (may be empty)
  - ``author``      : optional string
  - ``minApiVersion``: optional string
  - ``enabled``     : optional bool (default True)
  - ``config``      : optional dict of default configuration values
  - ``frontend``    : optional dict (panels/settings/actions/statusItems)

Unknown keys are tolerated so future manifest extensions do not break
older runtimes.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .exceptions import PluginManifestError


_NAME_RE = re.compile(r'^[A-Za-z0-9_]+$')
CURRENT_API_VERSION = '1.0.0'


@dataclass
class Manifest:
    """Parsed and validated plugin manifest."""

    name: str
    version: str
    description: Dict[str, str] = field(default_factory=dict)
    author: str = ''
    min_api_version: str = CURRENT_API_VERSION
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    frontend: Dict[str, Any] = field(default_factory=dict)
    frontend_bundles: Dict[str, str] = field(default_factory=dict)
    # Path to the source manifest.json (set by loader, not by users)
    source_path: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    @classmethod
    def from_dict(cls, data: Dict[str, Any], source_path: Optional[str] = None) -> 'Manifest':
        """Build a :class:`Manifest` from a parsed JSON dict.

        Raises :class:`PluginManifestError` if required fields are missing
        or invalid.
        """
        if not isinstance(data, dict):
            raise PluginManifestError('manifest root must be a JSON object')

        name = data.get('name')
        if not isinstance(name, str) or not name:
            raise PluginManifestError('manifest field "name" is required and must be a non-empty string')
        if not _NAME_RE.match(name):
            raise PluginManifestError(
                f'plugin name {name!r} contains invalid characters; only letters, digits and underscore are allowed'
            )

        version = data.get('version')
        if not isinstance(version, str) or not version:
            raise PluginManifestError('manifest field "version" is required and must be a non-empty string')

        description = data.get('description', {})
        if description is None:
            description = {}
        if not isinstance(description, dict):
            raise PluginManifestError('manifest field "description" must be an object of locale -> string')

        config = data.get('config', {})
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise PluginManifestError('manifest field "config" must be an object')

        frontend = data.get('frontend', {})
        if frontend is None:
            frontend = {}
        if not isinstance(frontend, dict):
            raise PluginManifestError('manifest field "frontend" must be an object')

        frontend_bundles = data.get('frontendBundles', {})
        if frontend_bundles is None:
            frontend_bundles = {}
        if not isinstance(frontend_bundles, dict):
            raise PluginManifestError('manifest field "frontendBundles" must be an object')

        return cls(
            name=name,
            version=version,
            description={k: str(v) for k, v in description.items()},
            author=str(data.get('author', '') or ''),
            min_api_version=str(data.get('minApiVersion', CURRENT_API_VERSION) or CURRENT_API_VERSION),
            enabled=bool(data.get('enabled', True)),
            config=config,
            frontend=frontend,
            frontend_bundles={str(k): str(v) for k, v in frontend_bundles.items()},
            source_path=source_path,
        )

    @classmethod
    def from_file(cls, path: str) -> 'Manifest':
        """Read and parse ``manifest.json`` from ``path``."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise PluginManifestError(f'manifest.json is not valid JSON: {exc}') from exc
        except OSError as exc:
            raise PluginManifestError(f'cannot read manifest.json: {exc}') from exc
        return cls.from_dict(data, source_path=path)

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_dict(self) -> Dict[str, Any]:
        """Serialize back to a JSON-compatible dict (manifest format)."""
        return {
            'name': self.name,
            'version': self.version,
            'description': dict(self.description),
            'author': self.author,
            'minApiVersion': self.min_api_version,
            'enabled': self.enabled,
            'config': dict(self.config),
            'frontend': dict(self.frontend),
            'frontendBundles': dict(self.frontend_bundles),
        }

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def api_compatible(self, runtime_version: str = CURRENT_API_VERSION) -> bool:
        """Best-effort semantic-version compatibility check.

        Compares ``minApiVersion`` against the runtime version by
        major.minor.  Patch differences are ignored.  If either version
        fails to parse, compatibility is assumed (fail-open).
        """
        def _parse(v: str):
            try:
                parts = v.split('.')
                return int(parts[0]), int(parts[1])
            except (ValueError, IndexError):
                return None
        min_parts = _parse(self.min_api_version)
        runtime_parts = _parse(runtime_version)
        if min_parts is None or runtime_parts is None:
            return True
        return min_parts <= runtime_parts

    @property
    def plugin_dir(self) -> str:
        """Directory containing the manifest file."""
        if self.source_path:
            return os.path.dirname(self.source_path)
        return ''

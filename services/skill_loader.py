"""Skill module discovery and loading.

Skills live in ``agent_modules/skills/<skill_name>/`` directories.  Each skill
must contain a ``manifest.json`` (with ``type: 'skill'``) and an ``__init__.py``
that exposes ``zaowu_register_skills() -> List[SkillDefinition]``.

Enable/disable/delete state is persisted in
``agent_modules/skills/.skill_state.json`` so that user preferences survive
restarts.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import re
import shutil
import sys
import threading
from typing import Any, Dict, List, Optional, Set

import yaml

from services.skill_registry import SkillDefinition, SkillRegistry


MODULE_PREFIX = 'zaowu_skill_'
SKILL_STATE_FILENAME = '.skill_state.json'

# Default skills directory, centralised here to avoid circular imports between
# ``server_quart`` and ``routes.agent_skills``.
DEFAULT_SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'agent_modules', 'skills',
)

logger = logging.getLogger('services.skill_loader')

# Process-wide lock serialising skill state mutations (import, enable, disable,
# delete).  This prevents lost-update races on .skill_state.json and directory
# creation races.  A single-process Quart server is assumed; a cross-process
# deployment would need a file lock.
_skill_state_lock = threading.Lock()


def _read_json(path: str) -> Dict[str, Any]:
    """Read a JSON file, returning an empty dict on any error."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning('failed to read %s: %s', path, exc)
        return {}


def _write_json(path: str, data: Dict[str, Any]) -> None:
    """Atomically write JSON data to a file."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _resolve_localized_description(description: Any, fallback: str = '') -> str:
    """Pick a display string from a localized description object.

    Supports ``{"zh-CN": "...", "en": "..."}`` or a plain string.
    Falls back to ``fallback`` when nothing usable is found.
    """
    if isinstance(description, str):
        return description
    if isinstance(description, dict):
        return (
            description.get('zh-CN')
            or description.get('en')
            or next(iter(description.values()), fallback)
            or fallback
        )
    return fallback


def get_skill_state_path(skills_dir: str) -> str:
    """Return the path to the skill state file for the given skills directory."""
    return os.path.join(skills_dir, SKILL_STATE_FILENAME)


def load_skill_state(skills_dir: str) -> Dict[str, Any]:
    """Load skill enable/disable/delete state.

    The state file has the following shape::

        {
          "version": 1,
          "enabled": ["code_review", "refactor"],
          "disabled": ["legacy_skill"],
          "deleted": ["removed_skill"]
        }

    Notes:
        - ``enabled`` tracks explicitly enabled skills.
        - ``disabled`` tracks explicitly disabled skills so the disabled state
          survives restarts even when ``enabled`` becomes empty.
        - ``deleted`` tracks user-deleted skills; they are skipped on load.
        - Newly discovered skills default to enabled unless listed in
          ``disabled`` or ``deleted``.
    """
    state = _read_json(get_skill_state_path(skills_dir))
    if not state.get('version'):
        state['version'] = 1
    if 'enabled' not in state:
        state['enabled'] = []
    if 'disabled' not in state:
        state['disabled'] = []
    if 'deleted' not in state:
        state['deleted'] = []
    return state


def save_skill_state(skills_dir: str, state: Dict[str, Any]) -> None:
    """Persist skill enable/disable/delete state."""
    os.makedirs(skills_dir, exist_ok=True)
    _write_json(get_skill_state_path(skills_dir), state)


def enable_skill_state(name: str, skills_dir: str) -> None:
    """Persist that ``name`` is enabled, under the process-wide state lock."""
    with _skill_state_lock:
        state = load_skill_state(skills_dir)
        if name not in state['enabled']:
            state['enabled'].append(name)
        if name in state['disabled']:
            state['disabled'].remove(name)
        if name in state['deleted']:
            state['deleted'].remove(name)
        save_skill_state(skills_dir, state)


def disable_skill_state(name: str, skills_dir: str) -> None:
    """Persist that ``name`` is disabled, under the process-wide state lock."""
    with _skill_state_lock:
        state = load_skill_state(skills_dir)
        if name in state['enabled']:
            state['enabled'].remove(name)
        if name not in state['disabled']:
            state['disabled'].append(name)
        save_skill_state(skills_dir, state)


def delete_skill_state(name: str, skills_dir: str) -> None:
    """Persist that ``name`` is deleted, under the process-wide state lock."""
    with _skill_state_lock:
        state = load_skill_state(skills_dir)
        if name not in state['deleted']:
            state['deleted'].append(name)
        if name in state['enabled']:
            state['enabled'].remove(name)
        if name in state['disabled']:
            state['disabled'].remove(name)
        save_skill_state(skills_dir, state)


def _load_skill_module(name: str, init_path: str):
    """Load a skill module into ``sys.modules``.

    TODO: share the core import logic with ``plugin_system.loader`` to avoid
    duplication.
    """
    module_name = MODULE_PREFIX + name
    if module_name in sys.modules:
        del sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, init_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot create import spec for skill {name}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def discover_skills(
    skills_dir: str,
    registry: SkillRegistry | None = None,
) -> List[str]:
    """Scan ``skills_dir`` and register discovered skills.

    Returns the list of successfully loaded skill names.

    Loading rules:

    1. Read ``.skill_state.json`` for enable/delete state.
    2. For each subdirectory with ``manifest.json`` and ``__init__.py``:
       - validate ``manifest.type == 'skill'``;
       - import ``__init__.py`` and call ``zaowu_register_skills()``;
       - validate every returned item is a ``SkillDefinition``;
       - merge ``manifest.config`` over ``skill.default_config``;
       - register the skill as enabled unless it is marked deleted.
    """
    loaded: List[str] = []
    if not os.path.isdir(skills_dir):
        return loaded

    registry = registry or SkillRegistry.get_instance()
    state = load_skill_state(skills_dir)
    deleted: Set[str] = set(state.get('deleted') or [])
    disabled: Set[str] = set(state.get('disabled') or [])

    for entry in sorted(os.scandir(skills_dir), key=lambda e: e.name.lower()):
        if not entry.is_dir(follow_symlinks=False):
            continue
        name = entry.name
        if name.startswith('.') or name.startswith('_'):
            continue

        manifest_path = os.path.join(entry.path, 'manifest.json')
        init_path = os.path.join(entry.path, '__init__.py')
        if not os.path.isfile(manifest_path) or not os.path.isfile(init_path):
            continue

        manifest = _read_json(manifest_path)
        if manifest.get('type') != 'skill':
            logger.warning(
                'skill module %s has invalid type %r; skipped',
                name, manifest.get('type'),
            )
            continue

        # Prefer the name declared in the manifest, but fall back to the
        # directory name.
        manifest_name = manifest.get('name') or name

        if manifest_name in deleted:
            logger.info('skill %s is marked as deleted; skipped', manifest_name)
            continue

        try:
            module = _load_skill_module(manifest_name, init_path)
            fn = getattr(module, 'zaowu_register_skills', None)
            if fn is None:
                logger.warning(
                    'skill module %s has no zaowu_register_skills',
                    manifest_name,
                )
                continue

            skills = fn()
            for skill in skills or []:
                if not isinstance(skill, SkillDefinition):
                    logger.warning(
                        'skill module %s returned non-SkillDefinition; skipped',
                        manifest_name,
                    )
                    continue

                # Allow manifest.config to override default_config.
                if manifest.get('config'):
                    skill.default_config = {
                        **skill.default_config,
                        **manifest['config'],
                    }

                # Use the localized manifest description if present.
                manifest_description = manifest.get('description')
                if manifest_description:
                    skill.description = _resolve_localized_description(
                        manifest_description, fallback=skill.description
                    )

                # Manifest may declare a tool whitelist for the sandbox.
                # An explicit manifest value overrides the Python declaration so
                # that manifest authors can restrict (not just expand) the list.
                manifest_allowed = manifest.get('allowed_tools')
                if manifest_allowed is not None:
                    skill.allowed_tools = list(dict.fromkeys(manifest_allowed))

                skill.source = 'builtin'
                # Newly discovered skills default to enabled unless explicitly
                # disabled or deleted.
                is_enabled = skill.name not in disabled and skill.name not in deleted
                registry.register(skill, enabled=is_enabled)
                loaded.append(skill.name)
        except Exception:
            logger.exception('failed to load skill %s', manifest_name)

    return loaded


async def reload_skills(skills_dir: str) -> List[str]:
    """Hot-reload all skills.

    Preserves the enabled state for plugin-provided skills across reloads.
    """
    registry = SkillRegistry.get_instance()
    # ``clear()`` wipes both _skills and _enabled; save the enabled set first.
    saved_enabled = set(registry._enabled)
    registry.clear()

    loaded = await asyncio.to_thread(discover_skills, skills_dir)

    from plugin_system import get_plugin_manager
    plugin_mgr = get_plugin_manager()
    if plugin_mgr is not None:
        plugin_skills = await plugin_mgr.collect_skills()
        for skill in plugin_skills:
            registry.register(skill, enabled=skill.name in saved_enabled)
            loaded.append(skill.name)

    return loaded


# ── Markdown skill import ──────────────────────────────────────────────


def _sanitize_skill_name(name: str) -> str:
    """Normalize a skill name to a safe directory name.

    Keeps Unicode letters/digits (e.g. Chinese characters), underscores,
    and hyphens.  Collapses spaces to underscores and lowercases.
    Falls back to ASCII-only stripping if the result would be empty.
    """
    # First pass: keep Unicode word chars, hyphens; replace spaces with _
    sanitized = re.sub(r'[^\w\-]', '', name.strip().replace(' ', '_'))
    # If Unicode stripping left nothing (e.g. all punctuation), try ASCII-only
    if not sanitized:
        sanitized = re.sub(r'[^a-zA-Z0-9_\-]', '', name.strip().replace(' ', '_'))
    return sanitized.lower()


def _generate_skill_init_py(skill: SkillDefinition) -> str:
    """Generate the contents of __init__.py for a skill directory."""
    system_prompt_repr = repr(skill.system_prompt)
    lines = [
        '"""Auto-generated skill module."""',
        '',
        'from services.skill_registry import SkillDefinition',
        '',
        '',
        'def zaowu_register_skills():',
        '    """Return the skill definition."""',
        '    return [',
        '        SkillDefinition(',
        f"            name={skill.name!r},",
        f"            description={skill.description!r},",
        f"            system_prompt={system_prompt_repr},",
        f"            default_config={skill.default_config!r},",
        f"            tags={skill.tags!r},",
        f"            allowed_tools={skill.allowed_tools!r},",
        '        )',
        '    ]',
        '',
    ]
    return '\n'.join(lines)


def _parse_markdown_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """Split YAML frontmatter from the markdown body.

    Supports:

        ---
        name: my_skill
        ---
        System prompt here...

    Returns (metadata_dict, body). If no frontmatter is found, returns
    ({}, content).
    """
    content = content.strip()
    if not content.startswith('---'):
        return {}, content

    # Find the closing --- (must be on its own line)
    match = re.match(r'^---\s*\n(.*?)\n---\s*(?:\n|$)', content, re.DOTALL)
    if not match:
        return {}, content

    frontmatter = match.group(1)
    body = content[match.end():]
    try:
        metadata = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f'Invalid YAML frontmatter: {exc}') from exc

    if not isinstance(metadata, dict):
        raise ValueError('YAML frontmatter must be a mapping')
    return metadata, body.strip()


def import_skill_from_markdown(
    content: str,
    skills_dir: str,
    registry: SkillRegistry | None = None,
) -> SkillDefinition:
    """Import a skill from a SKILL.md formatted string.

    Creates the skill directory, writes ``manifest.json`` and ``__init__.py``,
    and registers the skill in the registry.

    Expected markdown format::

        ---
        name: my_skill
        description: My custom skill
        allowed_tools:
          - read_file
          - search_code
        config:
          max_files: 5
        ---

        You are a helpful assistant focused on ...

    Args:
        content: Full markdown content.
        skills_dir: Directory where skills are stored.
        registry: Optional registry to register the skill in.

    Returns:
        The generated SkillDefinition.

    Raises:
        ValueError: If the markdown is invalid or the skill already exists.
    """
    metadata, body = _parse_markdown_frontmatter(content)

    raw_name = metadata.get('name') or ''
    if not raw_name:
        raise ValueError('Skill name is required in markdown frontmatter')

    name = _sanitize_skill_name(raw_name)
    if not name:
        raise ValueError(f'Invalid skill name: {raw_name!r}')

    description = metadata.get('description') or name
    if isinstance(description, dict):
        # Keep localized descriptions for the manifest; use current locale
        # fallback for SkillDefinition.
        display_description = (
            description.get('zh-CN')
            or description.get('en')
            or next(iter(description.values()), name)
        )
    else:
        display_description = str(description)

    allowed_tools = list(metadata.get('allowed_tools') or [])
    config = metadata.get('config') or {}
    tags = list(metadata.get('tags') or [])

    skill_dir = os.path.join(skills_dir, name)

    with _skill_state_lock:
        # Use lexists so that a symlink is treated as an existing path and we
        # never follow it or overwrite its target.  This also closes the
        # check-then-act (TOCTOU) window because os.mkdir below is atomic.
        if os.path.lexists(skill_dir):
            raise ValueError(f'Skill path already exists: {name}')

        skill = SkillDefinition(
            name=name,
            description=display_description,
            system_prompt=body,
            default_config=dict(config),
            tags=tags,
            allowed_tools=allowed_tools,
            source='builtin',
        )

        # Ensure the parent directory exists, then create the skill directory
        # atomically with os.mkdir (not exist_ok=True) so a concurrent import
        # of the same name fails instead of silently sharing the directory.
        os.makedirs(skills_dir, exist_ok=True)
        try:
            os.mkdir(skill_dir)
        except FileExistsError:
            raise ValueError(f'Skill directory already exists: {name}')

        try:
            manifest: Dict[str, Any] = {
                'name': name,
                'version': str(metadata.get('version', '1.0.0')),
                'type': 'skill',
                'description': description if isinstance(description, dict) else display_description,
                'config': dict(config),
            }
            if allowed_tools:
                manifest['allowed_tools'] = allowed_tools
            if tags:
                manifest['tags'] = tags

            manifest_path = os.path.join(skill_dir, 'manifest.json')
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)

            init_path = os.path.join(skill_dir, '__init__.py')
            with open(init_path, 'w', encoding='utf-8') as f:
                f.write(_generate_skill_init_py(skill))
        except Exception:
            # Roll back on failure to avoid partial skill directories.
            shutil.rmtree(skill_dir, ignore_errors=True)
            raise

        registry = registry or SkillRegistry.get_instance()
        registry.register(skill, enabled=True)

        # Persist enabled state while holding the import lock so concurrent
        # imports cannot read/write .skill_state.json and lose updates.
        state = load_skill_state(skills_dir)
        if name not in state['enabled']:
            state['enabled'].append(name)
        if name in state['disabled']:
            state['disabled'].remove(name)
        if name in state['deleted']:
            state['deleted'].remove(name)
        save_skill_state(skills_dir, state)

        logger.info('imported skill %s from markdown', name)
        return skill

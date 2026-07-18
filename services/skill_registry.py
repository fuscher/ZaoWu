"""Skill registry for the agent system.

A Skill is a high-level, domain-specific persona that guides the LLM by
injecting a system prompt and optional default configuration.  Skills do not
own tools; they only influence how the LLM uses the existing ToolRegistry.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


logger = logging.getLogger('services.skill_registry')


@dataclass
class SkillDefinition:
    """Definition of an agent skill.

    A skill does not perform tool calls itself.  It only provides:

    - ``system_prompt``: appended to the LLM system prompt.
    - ``default_config``: default configuration that may be overridden by
      ``manifest.config`` or per-conversation ``agentConfig.skillConfig``.
    - ``source``: origin identifier (``'builtin'`` for directory-loaded skills
      or the plugin name for plugin-provided skills).
    """

    name: str
    description: str
    system_prompt: str = ''
    default_config: Dict[str, Any] = field(default_factory=dict)
    source: str = 'builtin'
    tags: List[str] = field(default_factory=list)
    # 允许调用的工具白名单；为空表示不限制（向后兼容）
    allowed_tools: List[str] = field(default_factory=list)


class SkillRegistry:
    """Global singleton registry for agent skills.

    Supports enable/disable management:

    - All discovered skills are kept in ``_skills``.
    - ``_enabled`` controls which skills are currently active.
    - ``list_enabled()`` returns only enabled skills.

    Thread safety: all public methods acquire an instance lock so that the
    registry can be safely accessed from Quart request handlers and background
    threads (e.g. ``asyncio.to_thread``) concurrently.
    """

    _instance: Optional['SkillRegistry'] = None
    _class_lock = threading.Lock()

    def __init__(self) -> None:
        self._skills: Dict[str, SkillDefinition] = {}
        self._enabled: set[str] = set()
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'SkillRegistry':
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton, primarily for tests."""
        with cls._class_lock:
            cls._instance = None

    def register(self, skill: SkillDefinition, enabled: bool = True) -> None:
        """Register a skill.  If ``enabled`` is False it is kept but inactive."""
        with self._lock:
            existing = self._skills.get(skill.name)
            if existing is not None and existing.source != skill.source:
                logger.warning(
                    'skill %r from source %r is being overwritten by source %r',
                    skill.name, existing.source, skill.source,
                )
            self._skills[skill.name] = skill
            if enabled:
                self._enabled.add(skill.name)
            else:
                self._enabled.discard(skill.name)

    def unregister(self, name: str) -> None:
        """Remove a skill from the registry (used by the settings panel)."""
        with self._lock:
            self._skills.pop(name, None)
            self._enabled.discard(name)

    def enable(self, name: str) -> bool:
        """Enable a skill.  Returns True if the skill exists."""
        with self._lock:
            if name in self._skills:
                self._enabled.add(name)
                return True
            return False

    def disable(self, name: str) -> bool:
        """Disable a skill.  Returns True if the skill exists."""
        with self._lock:
            self._enabled.discard(name)
            return name in self._skills

    def is_enabled(self, name: str) -> bool:
        """Return True if the skill exists and is enabled."""
        with self._lock:
            return name in self._enabled and name in self._skills

    def get(self, name: str) -> Optional[SkillDefinition]:
        """Return the skill definition or None."""
        with self._lock:
            return self._skills.get(name)

    def list_skills(self) -> List[SkillDefinition]:
        """Return all registered skills (enabled or not)."""
        with self._lock:
            return list(self._skills.values())

    def list_enabled(self) -> List[SkillDefinition]:
        """Return only enabled skills."""
        with self._lock:
            return [s for s in self._skills.values() if s.name in self._enabled]

    def clear(self) -> None:
        """Clear all skills and enabled state.  Used before hot reload."""
        with self._lock:
            self._skills.clear()
            self._enabled.clear()

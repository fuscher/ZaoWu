"""REST endpoints for agent skill management."""

from __future__ import annotations

import asyncio
import logging

from quart import Blueprint, jsonify, request

from services.skill_registry import SkillRegistry
from services.skill_loader import (
    DEFAULT_SKILLS_DIR,
    enable_skill_state,
    disable_skill_state,
    delete_skill_state,
    reload_skills,
    import_skill_from_markdown,
)

SKILLS_DIR = DEFAULT_SKILLS_DIR

# Maximum allowed size for imported skill markdown content (512 KB).
IMPORT_MAX_CONTENT_BYTES = 512 * 1024

logger = logging.getLogger('routes.agent_skills')


bp = Blueprint('agent_skills', __name__, url_prefix='/api/agent/skills')


@bp.route('', methods=['GET'])
async def list_skills():
    """List all registered skills with their enabled state."""
    registry = SkillRegistry.get_instance()
    return jsonify({
        'ok': True,
        'skills': [
            {
                'name': s.name,
                'description': s.description,
                'tags': s.tags,
                'source': s.source,
                'enabled': registry.is_enabled(s.name),
                'defaultConfig': s.default_config,
                'allowedTools': s.allowed_tools,
            }
            for s in registry.list_skills()
        ],
    })


@bp.route('/<name>/enable', methods=['POST'])
async def enable_skill(name):
    """Enable a skill and persist the state."""
    registry = SkillRegistry.get_instance()
    if not registry.get(name):
        return jsonify({'ok': False, 'error': 'skill not found'}), 404

    registry.enable(name)
    await asyncio.to_thread(enable_skill_state, name, SKILLS_DIR)
    return jsonify({'ok': True})


@bp.route('/<name>/disable', methods=['POST'])
async def disable_skill(name):
    """Disable a skill and persist the state."""
    registry = SkillRegistry.get_instance()
    if not registry.get(name):
        return jsonify({'ok': False, 'error': 'skill not found'}), 404

    registry.disable(name)
    await asyncio.to_thread(disable_skill_state, name, SKILLS_DIR)
    return jsonify({'ok': True})


@bp.route('/<name>', methods=['DELETE'])
async def delete_skill(name):
    """Delete a builtin skill.

    Plugin-provided skills cannot be deleted here; they must be disabled or
    removed by uninstalling the plugin.
    """
    registry = SkillRegistry.get_instance()
    skill = registry.get(name)
    if skill is None:
        return jsonify({'ok': False, 'error': 'skill not found'}), 404
    if skill.source != 'builtin':
        return jsonify({'ok': False, 'error': 'cannot delete plugin-provided skill'}), 403

    registry.unregister(name)
    await asyncio.to_thread(delete_skill_state, name, SKILLS_DIR)
    return jsonify({'ok': True})


@bp.route('/import', methods=['POST'])
async def import_skill():
    """Import a skill from a SKILL.md formatted markdown string."""
    data = await request.get_json(silent=True) or {}
    content = data.get('content')
    if not content or not isinstance(content, str):
        return jsonify({'ok': False, 'error': 'missing content'}), 400
    if len(content) > IMPORT_MAX_CONTENT_BYTES:
        return jsonify({
            'ok': False,
            'error': f'content too large (max {IMPORT_MAX_CONTENT_BYTES // 1024} KB)',
        }), 400

    try:
        skill = await asyncio.to_thread(
            import_skill_from_markdown, content, SKILLS_DIR
        )
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception:
        logger.exception('failed to import skill')
        return jsonify({'ok': False, 'error': 'failed to import skill'}), 500

    return jsonify({
        'ok': True,
        'skill': {
            'name': skill.name,
            'description': skill.description,
            'tags': skill.tags,
            'source': skill.source,
            'enabled': True,
            'defaultConfig': skill.default_config,
            'allowedTools': skill.allowed_tools,
        },
    })


@bp.route('/reload', methods=['POST'])
async def reload_skills_endpoint():
    """Hot-reload skills from disk (development/admin use)."""
    try:
        loaded = await reload_skills(SKILLS_DIR)
        return jsonify({'ok': True, 'loaded': loaded})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500

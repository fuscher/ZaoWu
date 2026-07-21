"""Tests for server-wide skill startup helpers in server_quart.py."""
import asyncio
import json
import os
import sys

import pytest

from services.skill_registry import SkillDefinition, SkillRegistry

# Importing server_quart triggers plugin manager construction; this is safe in
# tests because it only reads the plugins/ directory.
from server_quart import _is_safe_skills_dir, _is_origin_allowed


@pytest.fixture(autouse=True)
def reset_registry_and_plugin_manager():
    """Reset SkillRegistry and restore the original plugin manager after each test."""
    from plugin_system import get_plugin_manager, set_plugin_manager
    original_manager = get_plugin_manager()
    SkillRegistry.reset_instance()
    yield
    set_plugin_manager(original_manager)
    SkillRegistry.reset_instance()


@pytest.fixture
def project_tree(tmp_path):
    """Return a project root and a safe skills directory under it."""
    root = tmp_path / 'project'
    root.mkdir()
    skills_dir = root / 'agent_modules' / 'skills'
    skills_dir.mkdir(parents=True)
    return root, skills_dir


def test_safe_skills_dir_accepted(project_tree):
    root, skills_dir = project_tree
    # Temporarily override BASE_DIR via monkeypatching the module constant.
    import server_quart
    original_base = server_quart.BASE_DIR
    try:
        server_quart.BASE_DIR = str(root)
        assert _is_safe_skills_dir(str(skills_dir)) is True
    finally:
        server_quart.BASE_DIR = original_base


def test_skills_dir_outside_project_rejected(project_tree, tmp_path):
    root, _ = project_tree
    outside_dir = tmp_path / 'outside' / 'skills'
    outside_dir.mkdir(parents=True)
    import server_quart
    original_base = server_quart.BASE_DIR
    try:
        server_quart.BASE_DIR = str(root)
        assert _is_safe_skills_dir(str(outside_dir)) is False
    finally:
        server_quart.BASE_DIR = original_base


def test_skills_dir_traversal_rejected(project_tree):
    root, _ = project_tree
    import server_quart
    original_base = server_quart.BASE_DIR
    try:
        server_quart.BASE_DIR = str(root)
        traversal_path = os.path.join(str(root), 'agent_modules', 'skills', '..', '..', 'etc')
        assert _is_safe_skills_dir(traversal_path) is False
    finally:
        server_quart.BASE_DIR = original_base


def test_missing_skills_dir_rejected(project_tree, tmp_path):
    root, _ = project_tree
    import server_quart
    original_base = server_quart.BASE_DIR
    try:
        server_quart.BASE_DIR = str(root)
        assert _is_safe_skills_dir(str(tmp_path / 'nonexistent')) is False
    finally:
        server_quart.BASE_DIR = original_base


@pytest.mark.skipif(sys.platform == 'win32', reason='symlink creation requires admin on Windows')
def test_symlinked_skills_dir_rejected(project_tree, tmp_path):
    root, skills_dir = project_tree
    symlink_dir = tmp_path / 'skills_link'
    symlink_dir.symlink_to(skills_dir, target_is_directory=True)
    import server_quart
    original_base = server_quart.BASE_DIR
    try:
        server_quart.BASE_DIR = str(root)
        assert _is_safe_skills_dir(str(symlink_dir)) is False
    finally:
        server_quart.BASE_DIR = original_base


def _write_skill(base_dir, name):
    """Create a minimal builtin skill for startup tests."""
    skill_dir = base_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        'name': name,
        'version': '1.0.0',
        'type': 'skill',
        'description': {'zh-CN': name, 'en': name},
    }
    (skill_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    init_code = f'''\
from services.skill_registry import SkillDefinition

def zaowu_register_skills():
    return [SkillDefinition(name={name!r}, description={name!r}, system_prompt='builtin')]
'''
    (skill_dir / '__init__.py').write_text(init_code, encoding='utf-8')


def _fake_plugin_manager(skills):
    """Return a minimal plugin manager for _startup_plugins tests."""
    class FakeManager:
        async def load_all(self):
            pass

        async def collect_routes(self):
            pass

        async def collect_agent_tools(self):
            return []

        async def collect_skills(self):
            return skills

        def _enabled_records(self):
            return []

        async def startup_hooks(self):
            pass

        async def _invoke(self, record, hook):
            pass

    return FakeManager()


def test_startup_plugins_enables_new_plugin_skills_by_default(project_tree, tmp_path):
    """Plugin-provided skills are enabled by default on first load."""
    root, skills_dir = project_tree
    plugins_dir = root / 'plugins'
    plugins_dir.mkdir()

    _write_skill(skills_dir, 'builtin_skill')
    from services.skill_loader import discover_skills
    discover_skills(str(skills_dir))

    plugin_skill = SkillDefinition(
        name='plugin_skill',
        description='plugin skill',
        system_prompt='plugin',
    )

    from plugin_system import set_plugin_manager
    set_plugin_manager(_fake_plugin_manager([plugin_skill]))

    import server_quart
    original_base = server_quart.BASE_DIR
    original_skills_dir = server_quart.DEFAULT_SKILLS_DIR
    try:
        server_quart.BASE_DIR = str(root)
        server_quart.DEFAULT_SKILLS_DIR = str(skills_dir)
        asyncio.run(server_quart._startup_plugins())
    finally:
        server_quart.BASE_DIR = original_base
        server_quart.DEFAULT_SKILLS_DIR = original_skills_dir

    registry = SkillRegistry.get_instance()
    skill = registry.get('plugin_skill')
    assert skill is not None
    assert skill.system_prompt == 'plugin'
    assert registry.is_enabled('plugin_skill') is True


def test_startup_plugins_respects_disabled_state_for_overriding_skill(project_tree, tmp_path):
    """A plugin skill overriding a builtin skill keeps the user's disabled state."""
    root, skills_dir = project_tree
    plugins_dir = root / 'plugins'
    plugins_dir.mkdir()

    _write_skill(skills_dir, 'shared_skill')
    from services.skill_loader import discover_skills, save_skill_state
    save_skill_state(str(skills_dir), {
        'version': 1,
        'enabled': [],
        'disabled': ['shared_skill'],
        'deleted': [],
    })
    discover_skills(str(skills_dir))

    registry = SkillRegistry.get_instance()
    assert registry.is_enabled('shared_skill') is False

    plugin_skill = SkillDefinition(
        name='shared_skill',
        description='plugin skill',
        system_prompt='plugin',
    )

    from plugin_system import set_plugin_manager
    set_plugin_manager(_fake_plugin_manager([plugin_skill]))

    import server_quart
    original_base = server_quart.BASE_DIR
    original_skills_dir = server_quart.DEFAULT_SKILLS_DIR
    try:
        server_quart.BASE_DIR = str(root)
        server_quart.DEFAULT_SKILLS_DIR = str(skills_dir)
        asyncio.run(server_quart._startup_plugins())
    finally:
        server_quart.BASE_DIR = original_base
        server_quart.DEFAULT_SKILLS_DIR = original_skills_dir

    skill = registry.get('shared_skill')
    assert skill is not None
    assert skill.system_prompt == 'plugin'
    assert registry.is_enabled('shared_skill') is False


def test_startup_plugins_skips_deleted_plugin_skills(project_tree, tmp_path):
    """Plugin skills marked as deleted in skill state are not registered."""
    root, skills_dir = project_tree
    plugins_dir = root / 'plugins'
    plugins_dir.mkdir()

    _write_skill(skills_dir, 'builtin_skill')
    from services.skill_loader import discover_skills, save_skill_state
    save_skill_state(str(skills_dir), {
        'version': 1,
        'enabled': [],
        'disabled': [],
        'deleted': ['removed_plugin_skill'],
    })
    discover_skills(str(skills_dir))

    plugin_skill = SkillDefinition(
        name='removed_plugin_skill',
        description='plugin skill',
        system_prompt='plugin',
    )

    from plugin_system import set_plugin_manager
    set_plugin_manager(_fake_plugin_manager([plugin_skill]))

    import server_quart
    original_base = server_quart.BASE_DIR
    original_skills_dir = server_quart.DEFAULT_SKILLS_DIR
    try:
        server_quart.BASE_DIR = str(root)
        server_quart.DEFAULT_SKILLS_DIR = str(skills_dir)
        asyncio.run(server_quart._startup_plugins())
    finally:
        server_quart.BASE_DIR = original_base
        server_quart.DEFAULT_SKILLS_DIR = original_skills_dir

    registry = SkillRegistry.get_instance()
    assert registry.get('removed_plugin_skill') is None


def test_is_origin_allowed_local_and_private():
    """Localhost, loopback, RFC1918 private and link-local origins are allowed."""
    allowed = [
        'http://localhost:5000',
        'http://0.0.0.0:5000',
        'http://127.0.0.1:5000',
        'http://192.168.1.5:5000',
        'http://10.0.0.1:5000',
        'http://172.16.0.1:5000',
        'http://169.254.1.1:5000',
        'ws://192.168.1.5:5000',
    ]
    for origin in allowed:
        assert _is_origin_allowed(origin) is True, origin


def test_is_origin_allowed_rejects_public():
    """Public domains and public IPs are rejected."""
    rejected = [
        'https://evil.com',
        'http://8.8.8.8',
        'http://1.1.1.1',
        'ftp://192.168.1.5',  # invalid scheme
        '',
    ]
    for origin in rejected:
        assert _is_origin_allowed(origin) is False, origin

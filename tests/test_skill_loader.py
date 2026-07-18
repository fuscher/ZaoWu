"""SkillLoader 单元测试。

覆盖技能目录扫描、manifest 校验、状态过滤、配置合并以及状态持久化。
"""
import asyncio
import json

import pytest

from services.skill_loader import (
    discover_skills,
    get_skill_state_path,
    load_skill_state,
    save_skill_state,
    reload_skills,
)
from services.skill_registry import SkillDefinition, SkillRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    """每个测试用例前重置 SkillRegistry 单例。"""
    SkillRegistry.reset_instance()
    yield
    SkillRegistry.reset_instance()


@pytest.fixture
def skills_dir(tmp_path):
    """创建一个临时 skills 目录，并返回其路径。"""
    return str(tmp_path / 'skills')


def _write_skill(
    base_dir,
    name,
    system_prompt='test prompt',
    manifest_type='skill',
    config=None,
    allowed_tools=None,
    code_allowed_tools=None,
):
    """在指定目录下创建一个测试 skill。"""
    skill_dir = base_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        'name': name,
        'version': '1.0.0',
        'type': manifest_type,
        'description': {'zh-CN': name, 'en': name},
    }
    if config is not None:
        manifest['config'] = config
    if allowed_tools is not None:
        manifest['allowed_tools'] = allowed_tools
    (skill_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    allowed_tools_code = ''
    if code_allowed_tools is not None:
        allowed_tools_code = f', allowed_tools={code_allowed_tools!r}'
    init_code = f'''\
from services.skill_registry import SkillDefinition

def zaowu_register_skills():
    return [
        SkillDefinition(
            name={name!r},
            description={name!r},
            system_prompt={system_prompt!r},
            default_config={{'default_key': 'default_value'}},
            tags=['test']{allowed_tools_code},
        )
    ]
'''
    (skill_dir / '__init__.py').write_text(init_code, encoding='utf-8')


def test_discover_skills_loads_valid_skill(skills_dir, tmp_path):
    base = tmp_path / 'skills'
    base.mkdir(parents=True)
    _write_skill(base, 'valid_skill')

    loaded = discover_skills(str(base))
    assert loaded == ['valid_skill']

    registry = SkillRegistry.get_instance()
    skill = registry.get('valid_skill')
    assert skill is not None
    assert skill.name == 'valid_skill'
    assert skill.source == 'builtin'
    assert registry.is_enabled('valid_skill') is True


def test_discover_skills_skips_invalid_type(skills_dir, tmp_path):
    base = tmp_path / 'skills'
    base.mkdir(parents=True)
    _write_skill(base, 'not_a_skill', manifest_type='plugin')

    loaded = discover_skills(str(base))
    assert loaded == []
    assert SkillRegistry.get_instance().get('not_a_skill') is None


def test_discover_skills_skips_deleted(skills_dir, tmp_path):
    base = tmp_path / 'skills'
    base.mkdir(parents=True)
    _write_skill(base, 'deleted_skill')

    state_path = get_skill_state_path(str(base))
    save_skill_state(str(base), {
        'version': 1,
        'enabled': [],
        'deleted': ['deleted_skill'],
    })

    loaded = discover_skills(str(base))
    assert loaded == []
    assert SkillRegistry.get_instance().get('deleted_skill') is None


def test_discover_skills_respects_disabled_state(skills_dir, tmp_path):
    base = tmp_path / 'skills'
    base.mkdir(parents=True)
    _write_skill(base, 'disabled_skill')

    save_skill_state(str(base), {
        'version': 1,
        'enabled': [],
        'disabled': ['disabled_skill'],
        'deleted': [],
    })

    loaded = discover_skills(str(base))
    assert loaded == ['disabled_skill']

    registry = SkillRegistry.get_instance()
    assert registry.get('disabled_skill') is not None
    assert registry.is_enabled('disabled_skill') is False


def test_discover_skills_merges_manifest_config(skills_dir, tmp_path):
    base = tmp_path / 'skills'
    base.mkdir(parents=True)
    _write_skill(base, 'config_skill', config={'default_key': 'manifest_value', 'extra_key': 'extra'})

    discover_skills(str(base))
    skill = SkillRegistry.get_instance().get('config_skill')
    assert skill.default_config['default_key'] == 'manifest_value'
    assert skill.default_config['extra_key'] == 'extra'


def test_load_skill_state_defaults(skills_dir):
    state = load_skill_state(skills_dir)
    assert state == {'version': 1, 'enabled': [], 'disabled': [], 'deleted': []}


def test_save_and_load_skill_state_roundtrip(skills_dir):
    original = {
        'version': 1,
        'enabled': ['skill_a'],
        'disabled': ['skill_c'],
        'deleted': ['skill_b'],
    }
    save_skill_state(skills_dir, original)

    loaded = load_skill_state(skills_dir)
    assert loaded == original


def test_discover_skills_ignores_hidden_directories(skills_dir, tmp_path):
    base = tmp_path / 'skills'
    base.mkdir(parents=True)
    _write_skill(base, 'visible_skill')
    hidden_dir = base / '.hidden'
    hidden_dir.mkdir()
    (hidden_dir / 'manifest.json').write_text('{}', encoding='utf-8')
    (hidden_dir / '__init__.py').write_text('', encoding='utf-8')

    loaded = discover_skills(str(base))
    assert loaded == ['visible_skill']


def test_discover_skills_skips_missing_files(skills_dir, tmp_path):
    base = tmp_path / 'skills'
    base.mkdir(parents=True)
    incomplete_dir = base / 'incomplete'
    incomplete_dir.mkdir()
    (incomplete_dir / 'manifest.json').write_text('{"type": "skill"}', encoding='utf-8')

    loaded = discover_skills(str(base))
    assert loaded == []


def test_reload_skills_preserves_builtin_state(skills_dir, tmp_path):
    """reload_skills clears and rediscovers builtin skills while preserving enabled state."""
    base = tmp_path / 'skills'
    base.mkdir(parents=True)
    _write_skill(base, 'skill_a')
    _write_skill(base, 'skill_b')

    # Pre-mark skill_b as disabled so we can verify state survives reload.
    save_skill_state(str(base), {
        'version': 1,
        'enabled': ['skill_a'],
        'disabled': ['skill_b'],
        'deleted': [],
    })

    loaded = asyncio.run(reload_skills(str(base)))
    assert sorted(loaded) == ['skill_a', 'skill_b']

    registry = SkillRegistry.get_instance()
    assert registry.is_enabled('skill_a') is True
    assert registry.is_enabled('skill_b') is False


def test_discover_skills_merges_localized_description(skills_dir, tmp_path):
    """The localized manifest description overrides the Python description."""
    base = tmp_path / 'skills'
    base.mkdir(parents=True)
    skill_dir = base / 'localized_skill'
    skill_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        'name': 'localized_skill',
        'version': '1.0.0',
        'type': 'skill',
        'description': {'zh-CN': '中文描述', 'en': 'English description'},
    }
    (skill_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    init_code = '''\
from services.skill_registry import SkillDefinition

def zaowu_register_skills():
    return [SkillDefinition(name='localized_skill', description='fallback', system_prompt='prompt')]
'''
    (skill_dir / '__init__.py').write_text(init_code, encoding='utf-8')

    discover_skills(str(base))
    skill = SkillRegistry.get_instance().get('localized_skill')
    assert skill.description == '中文描述'


def test_discover_skills_manifest_allowed_tools_overrides_code(skills_dir, tmp_path):
    """An explicit manifest allowed_tools list overrides the Python declaration."""
    base = tmp_path / 'skills'
    base.mkdir(parents=True)
    _write_skill(
        base,
        'restricted_skill',
        code_allowed_tools=['read_file', 'write_file'],
        allowed_tools=['read_file'],
    )

    discover_skills(str(base))
    skill = SkillRegistry.get_instance().get('restricted_skill')
    assert skill.allowed_tools == ['read_file']


def test_discover_skills_manifest_allowed_tools_empty_restricts_all(skills_dir, tmp_path):
    """An empty manifest allowed_tools list restricts the skill to no tools."""
    base = tmp_path / 'skills'
    base.mkdir(parents=True)
    _write_skill(
        base,
        'no_tools_skill',
        code_allowed_tools=['read_file', 'write_file'],
        allowed_tools=[],
    )

    discover_skills(str(base))
    skill = SkillRegistry.get_instance().get('no_tools_skill')
    assert skill.allowed_tools == []

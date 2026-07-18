"""SkillRegistry 单元测试。

覆盖技能的注册、启用、禁用、删除、查询以及单例行为。
"""
import pytest

from services.skill_registry import SkillDefinition, SkillRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    """每个测试用例前重置 SkillRegistry 单例，保证隔离性。"""
    SkillRegistry.reset_instance()
    yield
    SkillRegistry.reset_instance()


@pytest.fixture
def sample_skill():
    return SkillDefinition(
        name='code_review',
        description='代码审查技能',
        system_prompt='你是一位代码审查专家。',
        default_config={'max_files': 5},
        tags=['code', 'review'],
    )


def test_singleton_instance():
    r1 = SkillRegistry.get_instance()
    r2 = SkillRegistry.get_instance()
    assert r1 is r2


def test_register_and_get(sample_skill):
    registry = SkillRegistry.get_instance()
    registry.register(sample_skill)

    got = registry.get('code_review')
    assert got is sample_skill
    assert got.name == 'code_review'
    assert got.source == 'builtin'


def test_register_disabled_skill(sample_skill):
    registry = SkillRegistry.get_instance()
    registry.register(sample_skill, enabled=False)

    assert registry.get('code_review') is sample_skill
    assert registry.is_enabled('code_review') is False


def test_enable_disable(sample_skill):
    registry = SkillRegistry.get_instance()
    registry.register(sample_skill, enabled=False)

    assert registry.enable('code_review') is True
    assert registry.is_enabled('code_review') is True

    assert registry.disable('code_review') is True
    assert registry.is_enabled('code_review') is False


def test_enable_unknown_skill_returns_false():
    registry = SkillRegistry.get_instance()
    assert registry.enable('unknown') is False


def test_disable_unknown_skill_returns_false():
    registry = SkillRegistry.get_instance()
    assert registry.disable('unknown') is False


def test_is_enabled_for_unknown_skill():
    registry = SkillRegistry.get_instance()
    assert registry.is_enabled('unknown') is False


def test_unregister(sample_skill):
    registry = SkillRegistry.get_instance()
    registry.register(sample_skill)
    assert registry.is_enabled('code_review') is True

    registry.unregister('code_review')
    assert registry.get('code_review') is None
    assert registry.is_enabled('code_review') is False


def test_list_skills_and_list_enabled(sample_skill):
    registry = SkillRegistry.get_instance()
    skill_a = SkillDefinition(name='skill_a', description='A')
    skill_b = SkillDefinition(name='skill_b', description='B')

    registry.register(skill_a, enabled=True)
    registry.register(skill_b, enabled=False)

    all_skills = registry.list_skills()
    assert len(all_skills) == 2
    assert {s.name for s in all_skills} == {'skill_a', 'skill_b'}

    enabled_skills = registry.list_enabled()
    assert len(enabled_skills) == 1
    assert enabled_skills[0].name == 'skill_a'


def test_clear_registry():
    registry = SkillRegistry.get_instance()
    registry.register(SkillDefinition(name='skill_a', description='A'))
    registry.register(SkillDefinition(name='skill_b', description='B'))

    registry.clear()
    assert registry.list_skills() == []
    assert registry.list_enabled() == []
    assert registry.get('skill_a') is None


def test_register_overrides_existing():
    registry = SkillRegistry.get_instance()
    first = SkillDefinition(name='same', description='first', system_prompt='first prompt')
    second = SkillDefinition(name='same', description='second', system_prompt='second prompt')

    registry.register(first)
    registry.register(second)

    assert registry.get('same') is second
    assert registry.get('same').system_prompt == 'second prompt'

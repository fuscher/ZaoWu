"""Tests for importing skills from markdown files."""
import json
import os

import pytest

from services.skill_loader import import_skill_from_markdown
from services.skill_registry import SkillRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    SkillRegistry.reset_instance()
    yield
    SkillRegistry.reset_instance()


@pytest.fixture
def skills_dir(tmp_path):
    return str(tmp_path / 'skills')


def test_import_skill_from_markdown_creates_directory(skills_dir):
    content = '''---
name: Test Skill
description: A test skill
allowed_tools:
  - read_file
  - search_code
config:
  max_files: 3
---

You are a test assistant.
'''
    skill = import_skill_from_markdown(content, skills_dir)

    assert skill.name == 'test_skill'
    assert skill.description == 'A test skill'
    assert skill.system_prompt == 'You are a test assistant.'
    assert skill.allowed_tools == ['read_file', 'search_code']
    assert skill.default_config == {'max_files': 3}

    skill_dir = os.path.join(skills_dir, 'test_skill')
    assert os.path.isdir(skill_dir)
    assert os.path.isfile(os.path.join(skill_dir, 'manifest.json'))
    assert os.path.isfile(os.path.join(skill_dir, '__init__.py'))

    with open(os.path.join(skill_dir, 'manifest.json'), 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    assert manifest['type'] == 'skill'
    assert manifest['name'] == 'test_skill'
    assert manifest['allowed_tools'] == ['read_file', 'search_code']
    assert manifest['config'] == {'max_files': 3}


def test_import_skill_with_localized_description(skills_dir):
    content = '''---
name: localized_skill
description:
  zh-CN: 本地化技能
  en: Localized Skill
---

Prompt.
'''
    skill = import_skill_from_markdown(content, skills_dir)
    assert skill.name == 'localized_skill'
    assert skill.description == '本地化技能'


def test_import_skill_without_name_raises(skills_dir):
    content = 'Just a plain prompt.'
    with pytest.raises(ValueError, match='name is required'):
        import_skill_from_markdown(content, skills_dir)


def test_import_skill_requires_name(skills_dir):
    content = '''---
description: missing name
---

Prompt.
'''
    with pytest.raises(ValueError, match='name is required'):
        import_skill_from_markdown(content, skills_dir)


def test_import_skill_rejects_duplicate(skills_dir):
    content = '''---
name: dup
---

Prompt.
'''
    import_skill_from_markdown(content, skills_dir)
    with pytest.raises(ValueError, match='already exists'):
        import_skill_from_markdown(content, skills_dir)


def test_import_skill_registers_in_registry(skills_dir):
    content = '''---
name: reg_skill
---

Prompt.
'''
    skill = import_skill_from_markdown(content, skills_dir)
    registry = SkillRegistry.get_instance()
    assert registry.get('reg_skill') is skill
    assert registry.is_enabled('reg_skill') is True


def test_import_skill_rollback_on_write_failure(skills_dir, monkeypatch):
    """Verify that a failed __init__.py write cleans up the skill directory."""
    content = '''---
name: rollback_test
---

Prompt.
'''
    original_open = open

    call_count = 0

    def failing_open(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Let manifest.json write succeed (first open), fail on __init__.py (second)
        if call_count == 2 and ('w' in args[1] if len(args) > 1 else 'w' in kwargs.get('mode', '')):
            raise OSError('disk full')
        return original_open(*args, **kwargs)

    monkeypatch.setattr('builtins.open', failing_open)

    with pytest.raises(OSError, match='disk full'):
        import_skill_from_markdown(content, skills_dir)

    skill_dir = os.path.join(skills_dir, 'rollback_test')
    assert not os.path.exists(skill_dir), 'skill directory should be rolled back after write failure'


def test_import_skill_non_ascii_name(skills_dir):
    content = '''---
name: 代码审查
description: 代码审查技能
---

你是一位代码审查专家。
'''
    skill = import_skill_from_markdown(content, skills_dir)
    assert skill.name == '代码审查'
    assert os.path.isdir(os.path.join(skills_dir, '代码审查'))


def test_import_skill_rejects_path_traversal_name(skills_dir):
    """Names containing path separators must be normalised to a single dir."""
    content = '''---
name: ../evil_skill
description: evil
---

Prompt.
'''
    skill = import_skill_from_markdown(content, skills_dir)
    # The normalised name should not escape the skills directory.
    assert skill.name == 'evil_skill'
    assert not os.path.exists(os.path.join(os.path.dirname(skills_dir), 'evil_skill'))
    assert os.path.isdir(os.path.join(skills_dir, 'evil_skill'))


@pytest.mark.skipif(os.name == 'nt', reason='symlink creation may require admin on Windows')
def test_import_skill_rejects_symlink(skills_dir):
    """A pre-existing symlink at the target path must be rejected."""
    target = os.path.join(skills_dir, 'link_target')
    link_path = os.path.join(skills_dir, 'symlink_skill')
    os.makedirs(skills_dir, exist_ok=True)
    os.mkdir(target)
    os.symlink(target, link_path)

    content = '''---
name: symlink_skill
---

Prompt.
'''
    with pytest.raises(ValueError, match='already exists'):
        import_skill_from_markdown(content, skills_dir)

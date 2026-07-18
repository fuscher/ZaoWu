"""Agent skills REST 端点集成测试。

使用 Quart 的 test_client 验证列表、启用、禁用、删除端点的行为。
"""
import json
import os

import pytest

from services.skill_registry import SkillDefinition, SkillRegistry


pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def reset_registry():
    """每个测试用例前重置 SkillRegistry 单例。"""
    SkillRegistry.reset_instance()
    yield
    SkillRegistry.reset_instance()


@pytest.fixture
def app(tmp_path, monkeypatch):
    """构造已注册 skill 路由的 Quart app，并将状态文件指向临时目录。"""
    from server_quart import app
    import routes.agent_skills as agent_skills_module

    skills_dir = str(tmp_path / 'skills')
    os.makedirs(skills_dir, exist_ok=True)
    monkeypatch.setattr(agent_skills_module, 'SKILLS_DIR', skills_dir)

    return app


@pytest.fixture
def sample_skill():
    return SkillDefinition(
        name='code_review',
        description='code review skill',
        system_prompt='你是一位代码审查专家。',
    )


async def test_list_skills_empty(app):
    async with app.test_client() as client:
        resp = await client.get('/api/agent/skills')
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data['ok'] is True
        assert data['skills'] == []


async def test_list_skills_returns_registered_skills(app, sample_skill):
    SkillRegistry.get_instance().register(sample_skill)

    async with app.test_client() as client:
        resp = await client.get('/api/agent/skills')
        data = await resp.get_json()
        assert data['ok'] is True
        assert len(data['skills']) == 1
        skill = data['skills'][0]
        assert skill['name'] == 'code_review'
        assert skill['enabled'] is True
        assert skill['source'] == 'builtin'


async def test_enable_skill(app, sample_skill):
    SkillRegistry.get_instance().register(sample_skill, enabled=False)

    async with app.test_client() as client:
        resp = await client.post('/api/agent/skills/code_review/enable')
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data['ok'] is True
        assert SkillRegistry.get_instance().is_enabled('code_review') is True


async def test_disable_skill(app, sample_skill):
    SkillRegistry.get_instance().register(sample_skill, enabled=True)

    async with app.test_client() as client:
        resp = await client.post('/api/agent/skills/code_review/disable')
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data['ok'] is True
        assert SkillRegistry.get_instance().is_enabled('code_review') is False


async def test_enable_unknown_skill_returns_404(app):
    async with app.test_client() as client:
        resp = await client.post('/api/agent/skills/unknown/enable')
        assert resp.status_code == 404


async def test_delete_builtin_skill(app, sample_skill):
    SkillRegistry.get_instance().register(sample_skill)

    async with app.test_client() as client:
        resp = await client.delete('/api/agent/skills/code_review')
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data['ok'] is True
        assert SkillRegistry.get_instance().get('code_review') is None


async def test_delete_plugin_skill_forbidden(app):
    plugin_skill = SkillDefinition(
        name='plugin_skill',
        description='plugin skill',
        source='some_plugin',
    )
    SkillRegistry.get_instance().register(plugin_skill)

    async with app.test_client() as client:
        resp = await client.delete('/api/agent/skills/plugin_skill')
        assert resp.status_code == 403
        data = await resp.get_json()
        assert data['ok'] is False


async def test_delete_unknown_skill_returns_404(app):
    async with app.test_client() as client:
        resp = await client.delete('/api/agent/skills/unknown')
        assert resp.status_code == 404


async def test_import_skill_from_markdown(app):
    async with app.test_client() as client:
        resp = await client.post(
            '/api/agent/skills/import',
            json={
                'content': '''---
name: imported_skill
description: Imported from markdown
allowed_tools:
  - read_file
---

You are an imported assistant.
'''
            },
        )
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data['ok'] is True
        assert data['skill']['name'] == 'imported_skill'
        assert data['skill']['enabled'] is True
        assert SkillRegistry.get_instance().is_enabled('imported_skill') is True


async def test_import_skill_missing_content_returns_400(app):
    async with app.test_client() as client:
        resp = await client.post('/api/agent/skills/import', json={})
        assert resp.status_code == 400
        data = await resp.get_json()
        assert data['ok'] is False


async def test_import_skill_content_too_large_returns_400(app):
    oversized = '---\nname: big\n---\n' + 'x' * (512 * 1024 + 1)
    async with app.test_client() as client:
        resp = await client.post('/api/agent/skills/import', json={'content': oversized})
        assert resp.status_code == 400
        data = await resp.get_json()
        assert 'too large' in data['error']

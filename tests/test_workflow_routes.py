"""Workflow REST 端点集成测试。

使用 Quart 的 test_client 验证工作流的创建、列表、获取、更新、删除和执行端点。
"""
import json
import os

import pytest


pytestmark = pytest.mark.anyio


@pytest.fixture
def app(tmp_path, monkeypatch):
    """构造已注册 workflow 路由的 Quart app，并将工作流持久化文件指向临时目录。"""
    from server_quart import app
    import services.workflow_service as workflow_service_module

    workflows_file = str(tmp_path / 'workflows.json')
    monkeypatch.setattr(workflow_service_module, 'WORKFLOWS_FILE', workflows_file)

    return app


@pytest.fixture
def sample_workflow():
    return {
        'id': 'wf-sample',
        'name': 'Sample Workflow',
        'nodes': [
            {'id': 'start', 'type': 'start', 'position': {'x': 0, 'y': 0}, 'label': 'Start',
             'config': {'defaultValue': 'hello'}},
            {'id': 'end', 'type': 'end', 'position': {'x': 200, 'y': 0}, 'label': 'End', 'config': {}},
        ],
        'edges': [
            {'id': 'e1', 'source': 'start', 'sourcePort': 'default',
             'target': 'end', 'targetPort': 'default'},
        ],
    }


async def test_create_workflow(app, sample_workflow):
    async with app.test_client() as client:
        resp = await client.post('/api/workflows', json=sample_workflow)
        assert resp.status_code == 201
        data = await resp.get_json()
        assert data['ok'] is True
        assert data['workflow']['id'] == 'wf-sample'
        assert data['workflow']['version'] == 1


async def test_list_workflows(app, sample_workflow):
    async with app.test_client() as client:
        await client.post('/api/workflows', json=sample_workflow)
        resp = await client.get('/api/workflows')
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data['ok'] is True
        assert len(data['workflows']) == 1
        assert data['workflows'][0]['id'] == 'wf-sample'


async def test_get_workflow(app, sample_workflow):
    async with app.test_client() as client:
        await client.post('/api/workflows', json=sample_workflow)
        resp = await client.get('/api/workflows/wf-sample')
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data['ok'] is True
        assert data['workflow']['name'] == 'Sample Workflow'


async def test_get_workflow_not_found(app):
    async with app.test_client() as client:
        resp = await client.get('/api/workflows/nonexistent')
        assert resp.status_code == 404
        data = await resp.get_json()
        assert data['ok'] is False


async def test_update_workflow(app, sample_workflow):
    async with app.test_client() as client:
        await client.post('/api/workflows', json=sample_workflow)
        updated = {**sample_workflow, 'name': 'Updated Workflow'}
        resp = await client.put('/api/workflows/wf-sample', json=updated)
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data['ok'] is True
        assert data['workflow']['name'] == 'Updated Workflow'
        assert data['workflow']['version'] == 2


async def test_delete_workflow(app, sample_workflow):
    async with app.test_client() as client:
        await client.post('/api/workflows', json=sample_workflow)
        resp = await client.delete('/api/workflows/wf-sample')
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data['ok'] is True

        resp = await client.get('/api/workflows/wf-sample')
        assert resp.status_code == 404


async def test_run_workflow_validation_error(app):
    """缺少开始节点的工作流应返回 400 验证错误。"""
    bad_workflow = {
        'id': 'wf-bad',
        'name': 'Bad Workflow',
        'nodes': [
            {'id': 'end', 'type': 'end', 'position': {'x': 0, 'y': 0}, 'label': 'End', 'config': {}},
        ],
        'edges': [],
    }
    async with app.test_client() as client:
        await client.post('/api/workflows', json=bad_workflow)
        resp = await client.post('/api/workflows/wf-bad/run', json={'initialInput': ''})
        assert resp.status_code == 400
        data = await resp.get_json()
        assert data['ok'] is False
        assert 'errors' in data


async def test_run_workflow_not_found(app):
    async with app.test_client() as client:
        resp = await client.post('/api/workflows/nonexistent/run', json={'initialInput': ''})
        assert resp.status_code == 404

"""AgentService 端到端集成测试（mock LLM）。

验证一次完整的智能体交互：
LLM 产生 delta + 工具调用 -> 工具执行 -> 结果返回 -> 最终总结，
以及 SQLite 的逐轮持久化。
"""
import asyncio
import json
import os

import pytest

import agent_modules.agent_core.agent_service as agent_module
from agent_modules.agent_core import AgentService
from services.tool_registry import ToolRegistry
from services.conversation_store import ConversationStore
import server_quart


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    """准备隔离的 SQLite store 与 providers.json + 项目目录。"""
    project_path = tmp_path / 'project'
    project_path.mkdir()
    (project_path / 'hello.txt').write_text('Hello from ZaoWu!', encoding='utf-8')

    provider_file = tmp_path / 'providers.json'
    monkeypatch.setattr(agent_module, 'PROVIDERS_FILE', str(provider_file))

    provider_file.write_text(json.dumps({
        'providers': [{
            'id': 'test-provider',
            'name': 'Test',
            'apiBase': 'http://localhost:9999',
            'apiKey': 'test-key',
            'models': [{'id': 'test-model'}],
        }]
    }, ensure_ascii=False), encoding='utf-8')

    # Create SQLite store with initial conversation
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    store = ConversationStore(str(tmp_path / 'test.db'))

    async def _init():
        await store.ensure_tables()
        await store.create({
            'id': 'conv-1',
            'title': 'Test',
            'providerId': 'test-provider',
            'modelId': 'test-model',
            'agentConfig': {'enabled': True, 'maxIterations': 5},
            'createdAt': '2024-01-01T00:00:00+00:00',
            'updatedAt': '2024-01-01T00:00:00+00:00',
        })
        await store.append_message('conv-1', {
            'id': 'msg-1', 'role': 'user',
            'content': 'Read hello.txt', 'timestamp': 1,
        })

    loop.run_until_complete(_init())
    loop.close()

    monkeypatch.setattr(server_quart, 'get_conversation_store', lambda: store)

    return project_path, store


def test_agent_end_to_end_read_file(agent_env):
    project_path, store = agent_env
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    service = AgentService(
        ToolRegistry.get_instance(),
        project_path=str(project_path),
        limit_path=str(project_path),
        stop_event=asyncio.Event(),
    )

    file_path = str(project_path / 'hello.txt')

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        yield {'type': 'delta', 'delta': 'I will read the file for you.\n'}
        yield {
            'type': 'tool_call_part',
            'tool_call': {
                'requestId': 'call_1',
                'name': 'read_file',
                'arguments': {'path': file_path},
            },
        }

    service._stream_llm = mock_stream_llm

    async def run():
        events = []
        async for event in service.process_message('conv-1', 'Read hello.txt'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    loop.close()

    types = []
    for ev in events:
        assert ev.startswith('data: ')
        payload = json.loads(ev[6:])
        types.append(payload.get('type'))

    assert 'delta' in types
    assert 'tool_call_start' in types
    assert 'tool_call_end' in types
    assert 'done' in types

    done_event = next(
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'done'
    )
    assert done_event['done'] is True

    # 验证持久化
    async def _check():
        conv = await store.get('conv-1')
        return conv
    loop2 = asyncio.new_event_loop()
    asyncio.set_event_loop(loop2)
    conv = loop2.run_until_complete(_check())
    loop2.close()

    roles = [m['role'] for m in conv['messages']]
    assert 'assistant' in roles
    assert 'tool' in roles

    tool_msg = next(m for m in conv['messages'] if m['role'] == 'tool')
    assert tool_msg['tool_call_id'] == 'call_1'
    assert tool_msg['name'] == 'read_file'
    result = json.loads(tool_msg['content'])
    assert result['success'] is True
    assert 'Hello from ZaoWu!' in result['content']


def test_agent_loop_detection_triggers_and_persists(agent_env):
    project_path, _store = agent_env
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    service = AgentService(
        ToolRegistry.get_instance(),
        project_path=str(project_path),
        limit_path=str(project_path),
        stop_event=asyncio.Event(),
    )

    file_path = str(project_path / 'hello.txt')

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # LLM 始终返回同样的工具调用，触发循环检测
        yield {
            'type': 'tool_call_part',
            'tool_call': {
                'requestId': 'call_loop',
                'name': 'read_file',
                'arguments': {'path': file_path},
            },
        }

    service._stream_llm = mock_stream_llm

    async def run():
        events = []
        async for event in service.process_message('conv-1', 'loop test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    loop.close()

    contents = []
    for ev in events:
        payload = json.loads(ev[6:])
        if payload.get('type') == 'delta' and payload.get('id') == 'system':
            contents.append(payload.get('delta', ''))

    assert any('检测到重复调用' in c for c in contents)

    done = json.loads(events[-1][6:])
    assert done['type'] == 'done'


def test_agent_write_file_requires_confirmation_and_executes_when_approved(agent_env, tmp_path, monkeypatch):
    project_path, _store = agent_env
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    service = AgentService(
        ToolRegistry.get_instance(),
        project_path=str(project_path),
        limit_path=str(project_path),
        stop_event=asyncio.Event(),
    )
    monkeypatch.setattr(service, 'CONFIRMATION_TIMEOUT', 2)

    file_path = str(project_path / 'new.txt')

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        yield {'type': 'delta', 'delta': 'I will create the file.\n'}
        yield {
            'type': 'tool_call_part',
            'tool_call': {
                'requestId': 'call_write',
                'name': 'write_file',
                'arguments': {'path': file_path, 'content': 'approved content'},
            },
        }

    service._stream_llm = mock_stream_llm

    async def approve_after_delay():
        await asyncio.sleep(0.1)
        service.submit_confirmation('call_write', True)

    async def run():
        task = loop.create_task(approve_after_delay())
        events = []
        async for event in service.process_message('conv-1', 'Write new.txt'):
            events.append(event)
        await task
        return events

    events = loop.run_until_complete(run())
    loop.close()

    types = [json.loads(ev[6:]).get('type') for ev in events]
    assert 'requires_confirmation' in types
    assert 'tool_call_end' in types

    done = json.loads(events[-1][6:])
    assert done['type'] == 'done'

    # 验证文件已写入
    assert (project_path / 'new.txt').read_text(encoding='utf-8') == 'approved content'


def test_agent_write_file_rejected_does_not_execute(agent_env, tmp_path, monkeypatch):
    project_path, _store = agent_env
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    service = AgentService(
        ToolRegistry.get_instance(),
        project_path=str(project_path),
        limit_path=str(project_path),
        stop_event=asyncio.Event(),
    )
    monkeypatch.setattr(service, 'CONFIRMATION_TIMEOUT', 2)

    file_path = str(project_path / 'rejected.txt')

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        yield {
            'type': 'tool_call_part',
            'tool_call': {
                'requestId': 'call_write',
                'name': 'write_file',
                'arguments': {'path': file_path, 'content': 'should not exist'},
            },
        }

    service._stream_llm = mock_stream_llm

    async def reject_after_delay():
        await asyncio.sleep(0.1)
        service.submit_confirmation('call_write', False)

    async def run():
        task = loop.create_task(reject_after_delay())
        events = []
        async for event in service.process_message('conv-1', 'Write rejected.txt'):
            events.append(event)
        await task
        return events

    events = loop.run_until_complete(run())
    loop.close()

    tool_end = next(
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'tool_call_end'
    )
    assert tool_end['toolResult']['success'] is False
    assert '拒绝' in tool_end['toolResult']['error']

    # 验证文件未写入
    assert not (project_path / 'rejected.txt').exists()

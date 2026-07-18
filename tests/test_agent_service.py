"""AgentService 核心逻辑单元测试。

本模块主要覆盖不依赖真实 LLM 网络请求的静态/同步方法：
循环检测、工具调用合并、消息构建、SSE 事件格式化。
"""
import asyncio
import json

import pytest

from agent_modules.agent_core import AgentService
from services.skill_registry import SkillDefinition
from services.tool_registry import ToolRegistry


@pytest.fixture
def agent_service():
    """提供已设置事件循环的 AgentService 实例（兼容 Python 3.9）。"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    service = AgentService(
        ToolRegistry.get_instance(),
        stop_event=asyncio.Event(),
    )
    yield service
    loop.close()


def test_hash_args_is_stable_and_distinguishes():
    h1 = AgentService._hash_args({'path': '/a/b', 'count': 1})
    h2 = AgentService._hash_args({'path': '/a/b', 'count': 1})
    h3 = AgentService._hash_args({'path': '/a/b', 'count': 2})
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 12


def test_merge_tool_call_appends_new():
    existing = []
    new = {'requestId': 'call_1', 'name': 'read_file', 'arguments': {'path': '/a'}}
    result = AgentService._merge_tool_call(existing, new)
    assert result is existing
    assert result == [new]


def test_merge_tool_call_updates_existing():
    existing = [{'requestId': 'call_1', 'name': 'read_file', 'arguments': {'path': '/a'}}]
    updated = {'requestId': 'call_1', 'name': 'read_file', 'arguments': {'path': '/b'}}
    result = AgentService._merge_tool_call(existing, updated)
    assert result == [updated]


def test_delta_event_format():
    event = AgentService._delta_event('msg-1', 'hello')
    assert event.startswith('data: ')
    payload = json.loads(event[6:])
    assert payload['id'] == 'msg-1'
    assert payload['type'] == 'delta'
    assert payload['delta'] == 'hello'
    assert payload['done'] is False


def test_tool_call_start_event_format():
    tc = {'requestId': 'call_1', 'name': 'read_file', 'arguments': {'path': '/a'}}
    event = AgentService._tool_call_start_event('msg-1', tc)
    payload = json.loads(event[6:])
    assert payload['type'] == 'tool_call_start'
    assert payload['toolCall'] == tc


def test_tool_call_end_event_format():
    result = {'success': True, 'content': 'ok'}
    event = AgentService._tool_call_end_event('msg-1', 'call_1', result)
    payload = json.loads(event[6:])
    assert payload['type'] == 'tool_call_end'
    assert payload['toolResult']['requestId'] == 'call_1'
    assert payload['toolResult']['success'] is True


def test_done_event_format():
    event = AgentService._done_event('msg-1', 'final content')
    payload = json.loads(event[6:])
    assert payload['type'] == 'done'
    assert payload['done'] is True
    assert payload['content'] == 'final content'


def test_requires_confirmation_event_format():
    tc = {'requestId': 'call_1', 'name': 'write_file', 'arguments': {'path': '/a', 'content': 'x'}}
    event = AgentService._requires_confirmation_event('msg-1', tc)
    payload = json.loads(event[6:])
    assert payload['type'] == 'requires_confirmation'
    assert payload['toolCall'] == tc


def test_submit_confirmation_sets_result_and_event(agent_service):
    service = agent_service
    request_id = 'call_1'
    event = asyncio.Event()
    service._confirmation_events[request_id] = event
    ok = service.submit_confirmation(request_id, True)
    assert ok is True
    assert event.is_set()
    assert service._confirmation_results[request_id] is True


def test_submit_confirmation_unknown_request_returns_false(agent_service):
    service = agent_service
    ok = service.submit_confirmation('nonexistent', True)
    assert ok is False


def test_wait_for_confirmation_approved(agent_service):
    service = agent_service
    loop = asyncio.get_event_loop()

    async def approve_after_delay():
        await asyncio.sleep(0.05)
        service.submit_confirmation('call_1', True)

    async def run():
        task = loop.create_task(approve_after_delay())
        result = await service._wait_for_confirmation('call_1')
        await task
        return result

    assert loop.run_until_complete(run()) is True


def test_wait_for_confirmation_timeout(agent_service, monkeypatch):
    service = agent_service
    monkeypatch.setattr(service, 'CONFIRMATION_TIMEOUT', 0.05)
    loop = asyncio.get_event_loop()
    assert loop.run_until_complete(service._wait_for_confirmation('call_1')) is False


def test_build_messages_structure(agent_service):
    service = agent_service
    conv = {
        'messages': [
            {'role': 'system', 'content': 'old system'},
            {'role': 'user', 'content': 'hi'},
            {
                'role': 'assistant',
                'content': None,
                'tool_calls': [{'id': 'call_1', 'type': 'function'}],
            },
            {'role': 'tool', 'tool_call_id': 'call_1', 'name': 'read_file', 'content': '{}'},
        ],
    }
    messages = service._build_messages(conv, 'new question')

    # 系统提示词被替换为最新
    assert messages[0]['role'] == 'system'
    assert 'ZaoWu' in messages[0]['content']

    # 历史中的旧 system 被跳过
    assert all(m['role'] != 'system' for m in messages[1:])

    # 保留 tool_calls / tool_call_id
    assistant_msg = next(m for m in messages if m['role'] == 'assistant')
    assert 'tool_calls' in assistant_msg
    tool_msg = next(m for m in messages if m['role'] == 'tool')
    assert tool_msg['tool_call_id'] == 'call_1'

    # 用户消息不再重复追加
    assert not any(m.get('content') == 'new question' for m in messages)


def test_build_system_prompt_replaces_placeholders(agent_service):
    service = agent_service
    conv = {
        'agentConfig': {
            'systemPrompt': 'Project: <<PROJECT_PATH>>, Git: <<GIT_BRANCH>>',
        },
    }
    prompt = service._build_system_prompt(conv)
    assert '<<PROJECT_PATH>>' not in prompt
    assert '<<GIT_BRANCH>>' not in prompt
    assert service.project_path in prompt


def test_build_system_prompt_injects_enabled_skill(agent_service):
    service = agent_service
    skill = SkillDefinition(
        name='code_review',
        description='code review skill',
        system_prompt='你是一位代码审查专家。',
    )
    service.skill_registry.register(skill)

    conv = {
        'agentConfig': {
            'selectedSkill': 'code_review',
        },
    }
    prompt = service._build_system_prompt(conv)
    assert '## 当前技能' in prompt
    assert '你是一位代码审查专家。' in prompt


def test_build_system_prompt_ignores_disabled_skill(agent_service):
    service = agent_service
    skill = SkillDefinition(
        name='code_review',
        description='code review skill',
        system_prompt='你是一位代码审查专家。',
    )
    service.skill_registry.register(skill, enabled=False)

    conv = {
        'agentConfig': {
            'selectedSkill': 'code_review',
        },
    }
    prompt = service._build_system_prompt(conv)
    assert '## 当前技能' not in prompt
    assert '你是一位代码审查专家。' not in prompt


def test_build_system_prompt_ignores_unknown_skill(agent_service):
    service = agent_service
    conv = {
        'agentConfig': {
            'selectedSkill': 'unknown_skill',
        },
    }
    prompt = service._build_system_prompt(conv)
    assert '## 当前技能' not in prompt


def test_resolve_skill_config_merges_default_and_user_config(agent_service):
    service = agent_service
    skill = SkillDefinition(
        name='code_review',
        description='code review skill',
        default_config={'max_files': 5, 'strict': False},
    )
    service.skill_registry.register(skill)

    conv = {
        'agentConfig': {
            'selectedSkill': 'code_review',
            'skillConfig': {
                'code_review': {'max_files': 10},
            },
        },
    }
    config = service._resolve_skill_config(conv)
    assert config['max_files'] == 10
    assert config['strict'] is False


def test_resolve_skill_config_returns_empty_without_selected_skill(agent_service):
    service = agent_service
    assert service._resolve_skill_config({}) == {}
    assert service._resolve_skill_config({'agentConfig': {}}) == {}


def test_build_sandbox_allows_all_tools_without_skill(agent_service):
    service = agent_service
    sandbox = service._build_sandbox({'agentConfig': {}})
    assert sandbox.allowed_tools == set()


def test_build_sandbox_restricts_to_allowed_tools(agent_service):
    service = agent_service
    skill = SkillDefinition(
        name='restricted',
        description='restricted skill',
        allowed_tools=['read_file', 'search_code'],
    )
    service.skill_registry.register(skill)

    sandbox = service._build_sandbox({'agentConfig': {'selectedSkill': 'restricted'}})
    assert sandbox.allowed_tools == {'read_file', 'search_code'}


def test_build_sandbox_unrestricted_when_skill_disabled(agent_service):
    service = agent_service
    skill = SkillDefinition(
        name='restricted',
        description='restricted skill',
        allowed_tools=['read_file'],
    )
    service.skill_registry.register(skill, enabled=False)

    sandbox = service._build_sandbox({'agentConfig': {'selectedSkill': 'restricted'}})
    assert sandbox.allowed_tools == set()

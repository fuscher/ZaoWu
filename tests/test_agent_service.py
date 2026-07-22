"""AgentService 核心逻辑单元测试。

本模块主要覆盖不依赖真实 LLM 网络请求的静态/同步方法：
循环检测、工具调用合并、消息构建、SSE 事件格式化。
"""
import asyncio
import json
import os

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


def test_delta_event_preserves_chinese():
    event = AgentService._delta_event('msg-1', '中文')
    payload = json.loads(event[6:])
    assert payload['delta'] == '中文'
    # 不应出现 \uXXXX 转义，确保 SSE 原始流可直接阅读
    assert r'\u4e2d' not in event


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


# ── Stage 9: F05 连续死循环检测 ───────────────────────────────


def _make_tool_call(name, args, request_id=None):
    """构造工具调用字典。"""
    return {
        'requestId': request_id or f'call_{name}_{args}',
        'name': name,
        'arguments': args,
    }


def test_f05_within_iteration_aaa_triggers(agent_service, monkeypatch):
    """F05: 单轮内 3 个相同工具调用（A-A-A）应触发循环检测。"""
    service = agent_service
    loop = asyncio.get_event_loop()

    file_path = '/tmp/test.txt'
    tc = _make_tool_call('read_file', {'path': file_path}, 'call_a')

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # 单轮返回 3 个完全相同的工具调用
        for i in range(3):
            yield {'type': 'tool_call_part', 'tool_call': {**tc, 'requestId': f'call_a_{i}'}}

    service._stream_llm = mock_stream_llm

    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id,
            'providerId': 'test-provider',
            'modelId': 'test-model',
            'agentConfig': {'enabled': True, 'maxIterations': 5},
            'messages': [],
        }

    async def mock_append_message(conv_id, msg):
        pass

    async def mock_inject_batch(messages, conv_id, calls, results):
        pass

    monkeypatch.setattr(service, '_get_conversation', mock_get_conversation)
    monkeypatch.setattr(service, '_append_message', mock_append_message)
    monkeypatch.setattr(service, '_inject_tool_results_batch', mock_inject_batch)

    # Mock sandbox to avoid real file execution
    class _FakeSandbox:
        def build_openai_tools_spec(self):
            return []

        async def execute(self, name, args):
            return {'success': True, 'content': 'ok'}

    monkeypatch.setattr(service, '_build_sandbox', lambda conv: _FakeSandbox())
    monkeypatch.setattr(service, '_get_provider', lambda conv: {
        'id': 'test-provider', 'apiBase': 'http://localhost', 'apiKey': 'k', 'models': [{'id': 'test-model'}]
    })

    async def run():
        events = []
        async for event in service.process_message('conv-f05a', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    contents = [
        json.loads(ev[6:])['delta']
        for ev in events
        if json.loads(ev[6:]).get('type') == 'delta'
        and json.loads(ev[6:]).get('id') == 'system'
    ]
    assert any('连续重复调用' in c for c in contents), 'A-A-A should trigger loop detection'


def test_f05_alternating_ababa_no_false_positive(agent_service, monkeypatch):
    """F05: 交替调用 A-B-A-B-A 不应被误判为死循环。"""
    service = agent_service
    loop = asyncio.get_event_loop()

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # 交替返回 read_file 和 search_code（不同工具/参数 = 不同 key）
        for i, name in enumerate(['read_file', 'search_code', 'read_file', 'search_code', 'read_file']):
            yield {
                'type': 'tool_call_part',
                'tool_call': _make_tool_call(name, {'query': str(i)}, f'call_{i}'),
            }

    service._stream_llm = mock_stream_llm

    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id, 'providerId': 'test-provider', 'modelId': 'test-model',
            'agentConfig': {'enabled': True, 'maxIterations': 5}, 'messages': [],
        }

    async def mock_append_message(conv_id, msg):
        pass

    async def mock_inject_batch(messages, conv_id, calls, results):
        pass

    monkeypatch.setattr(service, '_get_conversation', mock_get_conversation)
    monkeypatch.setattr(service, '_append_message', mock_append_message)
    monkeypatch.setattr(service, '_inject_tool_results_batch', mock_inject_batch)

    class _FakeSandbox:
        def build_openai_tools_spec(self):
            return []

        async def execute(self, name, args):
            return {'success': True, 'content': 'ok'}

    monkeypatch.setattr(service, '_build_sandbox', lambda conv: _FakeSandbox())
    monkeypatch.setattr(service, '_get_provider', lambda conv: {
        'id': 'test-provider', 'apiBase': 'http://localhost', 'apiKey': 'k', 'models': [{'id': 'test-model'}]
    })

    async def run():
        events = []
        async for event in service.process_message('conv-f05b', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    system_deltas = [
        json.loads(ev[6:])['delta']
        for ev in events
        if json.loads(ev[6:]).get('type') == 'delta'
        and json.loads(ev[6:]).get('id') == 'system'
    ]
    assert not any('连续重复调用' in c for c in system_deltas), 'A-B-A-B-A should NOT trigger loop detection'


# ── Stage 9: F12 确认竞态与过期 ID ────────────────────────────


def test_f12_submit_confirmation_before_wait(agent_service):
    """F12: 用户在 _wait_for_confirmation 创建 event 之前就提交确认（竞态），结果应被正确消费。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    request_id = 'call_race_1'

    # 先注册 pending id 并提交确认（此时 event 尚未创建）
    service._pending_confirmation_ids.add(request_id)
    ok = service.submit_confirmation(request_id, True)
    assert ok is True
    # 结果应被预缓存
    assert service._confirmation_results[request_id] is True

    # 随后 _wait_for_confirmation 应直接消费预缓存结果，不阻塞
    async def run():
        return await service._wait_for_confirmation(request_id)

    result = loop.run_until_complete(run())
    assert result is True
    # pending id 应被清理
    assert request_id not in service._pending_confirmation_ids


def test_f12_submit_confirmation_stale_id_returns_false(agent_service):
    """F12/F17: 对不在 _pending_confirmation_ids 也不在 _confirmation_events 的 request_id 提交确认，应返回 False。"""
    service = agent_service
    # 不注册任何 pending id
    ok = service.submit_confirmation('totally_unknown', True)
    assert ok is False


def test_f12_submit_confirmation_double_submit(agent_service):
    """F12: 同一 request_id 重复提交第二次应返回 False（已解决）。"""
    service = agent_service
    request_id = 'call_double'
    service._pending_confirmation_ids.add(request_id)

    first = service.submit_confirmation(request_id, True)
    assert first is True
    assert request_id not in service._pending_confirmation_ids  # 第一次后应移除

    second = service.submit_confirmation(request_id, False)
    assert second is False  # 第二次提交应被拒绝


# ── Stage 9: F19 安全沙箱回退 ────────────────────────────────


def test_f19_fallback_to_home_zaowu(monkeypatch):
    """F19: 无项目时 _get_project_paths 应回退到 ~/.ZaoWu 安全沙箱。"""
    # Mock read_projects 返回空列表
    from routes import explorer
    monkeypatch.setattr(explorer, 'read_projects', lambda: [])

    paths = AgentService._get_project_paths(limit_path=None)
    assert len(paths) == 1
    expected = os.path.join(os.path.expanduser('~'), '.ZaoWu')
    assert os.path.realpath(expected) == paths[0] or paths[0].endswith('.ZaoWu')


def test_f19_limit_path_takes_priority(tmp_path):
    """F19: 指定 limit_path 时应优先返回该路径，不走回退。"""
    project = tmp_path / 'myproject'
    project.mkdir()

    paths = AgentService._get_project_paths(limit_path=str(project))
    assert len(paths) == 1
    assert os.path.realpath(str(project)) == paths[0]


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

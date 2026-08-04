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
    # 技能改为「全部启用即生效」后，_get_enabled_skills 读取全局 registry 全部
    # enabled skills；测试间需保证 registry 干净，避免相互污染。
    service.skill_registry.clear()
    yield service
    service.skill_registry.clear()
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
    loop = asyncio.get_event_loop()
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
    messages = loop.run_until_complete(service._build_messages(conv, 'new question'))

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
    loop = asyncio.get_event_loop()
    conv = {
        'agentConfig': {
            'systemPrompt': 'Project: <<PROJECT_PATH>>, Git: <<GIT_BRANCH>>',
        },
    }
    prompt = loop.run_until_complete(service._build_system_prompt(conv))
    assert '<<PROJECT_PATH>>' not in prompt
    assert '<<GIT_BRANCH>>' not in prompt
    # <<PROJECT_PATH>> 填充真实白名单（project_bases），而非单一展示路径
    for p in service.executor.project_bases:
        assert p in prompt


def test_build_system_prompt_injects_all_enabled_skills(agent_service):
    service = agent_service
    skill_a = SkillDefinition(
        name='aaa_skill',
        description='a skill',
        system_prompt='你是技能 A。',
    )
    skill_b = SkillDefinition(
        name='bbb_skill',
        description='b skill',
        system_prompt='你是技能 B。',
    )
    service.skill_registry.register(skill_a)
    service.skill_registry.register(skill_b)

    loop = asyncio.get_event_loop()
    prompt = loop.run_until_complete(service._build_system_prompt({}))
    # 所有 enabled skills 均注入，按 name 字典序拼接
    assert '## 当前技能：aaa_skill' in prompt
    assert '你是技能 A。' in prompt
    assert '## 当前技能：bbb_skill' in prompt
    assert '你是技能 B。' in prompt
    assert prompt.index('aaa_skill') < prompt.index('bbb_skill')


def test_build_system_prompt_ignores_disabled_skill(agent_service):
    service = agent_service
    skill = SkillDefinition(
        name='code_review',
        description='code review skill',
        system_prompt='你是一位代码审查专家。',
    )
    service.skill_registry.register(skill, enabled=False)

    loop = asyncio.get_event_loop()
    prompt = loop.run_until_complete(service._build_system_prompt({}))
    assert '## 当前技能' not in prompt
    assert '你是一位代码审查专家。' not in prompt


def test_build_system_prompt_no_skill_section_without_enabled_skills(agent_service):
    service = agent_service
    # 无任何启用技能时不注入技能段（取代原 ignores_unknown_skill：警告分支已移除）
    loop = asyncio.get_event_loop()
    prompt = loop.run_until_complete(service._build_system_prompt({}))
    assert '## 当前技能' not in prompt


def test_resolve_merged_skill_config_merges_multiple_skills(agent_service):
    service = agent_service
    skill_a = SkillDefinition(
        name='aaa_skill',
        description='a',
        default_config={'key_a': 'a_default', 'shared': 'from_a'},
    )
    skill_b = SkillDefinition(
        name='bbb_skill',
        description='b',
        default_config={'key_b': 'b_default', 'shared': 'from_b'},
    )
    service.skill_registry.register(skill_a)
    service.skill_registry.register(skill_b)

    conv = {
        'agentConfig': {
            'skillConfig': {
                'aaa_skill': {'max_files': 10},
            },
        },
    }
    config = service._resolve_merged_skill_config(conv)
    assert config['key_a'] == 'a_default'   # aaa default
    assert config['key_b'] == 'b_default'   # bbb default
    assert config['max_files'] == 10        # aaa user skillConfig 覆盖 default
    # 冲突 key 按 skill.name 序后者覆盖：bbb 在 aaa 之后
    assert config['shared'] == 'from_b'


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


def test_stop_event_prevents_tool_execution_after_stream(agent_service, monkeypatch):
    """3.1 回归：流式期间用户点停止，llm_stream 仍 yield 已积累的 tool_call_part，
    回到 process_message 后 collected_tool_calls 非空但 stop_event 已置位，
    此时应立即终止，不再执行任何工具。"""
    service = agent_service
    loop = asyncio.get_event_loop()

    tc = _make_tool_call('read_file', {'path': '/tmp/test.txt'}, 'call_stop_1')

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # 模拟流式过程中已积累工具调用，随后用户点击停止（llm_stream 检测后置位）
        yield {'type': 'tool_call_part', 'tool_call': tc}
        service.stop_event.set()

    service._stream_llm = mock_stream_llm

    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id, 'providerId': 'test-provider', 'modelId': 'test-model',
            'agentConfig': {'enabled': True, 'maxIterations': 5}, 'messages': [],
        }

    async def mock_append_message(conv_id, msg):
        pass

    monkeypatch.setattr(service, '_get_conversation', mock_get_conversation)
    monkeypatch.setattr(service, '_append_message', mock_append_message)
    monkeypatch.setattr(service, '_get_provider', lambda conv: {
        'id': 'test-provider', 'apiBase': 'http://localhost', 'apiKey': 'k', 'models': [{'id': 'test-model'}]
    })

    execute_calls = []

    class _FakeSandbox:
        def build_openai_tools_spec(self):
            return []

        async def execute(self, name, args):
            execute_calls.append((name, args))
            return {'success': True, 'content': 'ok'}

    monkeypatch.setattr(service, '_build_sandbox', lambda conv: _FakeSandbox())

    async def run():
        events = []
        async for event in service.process_message('conv-stop', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())

    # 关键断言：stop 后不应执行任何工具
    assert execute_calls == [], 'no tool should execute after stop'
    # 应有终止文案
    assert any('已被用户终止' in ev for ev in events), 'should emit termination notice'


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


def test_resolve_merged_skill_config_empty_without_enabled_skills(agent_service):
    service = agent_service
    assert service._resolve_merged_skill_config({}) == {}
    assert service._resolve_merged_skill_config({'agentConfig': {}}) == {}


def test_build_sandbox_allows_all_tools_without_enabled_skills(agent_service):
    service = agent_service
    sandbox = service._build_sandbox({'agentConfig': {}})
    assert sandbox.allowed_tools == set()


def test_build_sandbox_merges_allowed_tools_union(agent_service):
    service = agent_service
    skill_a = SkillDefinition(
        name='aaa_skill',
        description='a',
        allowed_tools=['read_file', 'search_code'],
    )
    skill_b = SkillDefinition(
        name='bbb_skill',
        description='b',
        allowed_tools=['search_code', 'write_file'],
    )
    service.skill_registry.register(skill_a)
    service.skill_registry.register(skill_b)

    sandbox = service._build_sandbox({'agentConfig': {}})
    assert sandbox.allowed_tools == {'read_file', 'search_code', 'write_file'}


def test_build_sandbox_unrestricted_when_any_skill_has_empty_allowed_tools(agent_service):
    """任一 enabled skill 无白名单（空）= 不限制 → 全放行。"""
    service = agent_service
    skill_a = SkillDefinition(
        name='aaa_skill',
        description='a',
        allowed_tools=['read_file'],
    )
    skill_b = SkillDefinition(
        name='bbb_skill',
        description='b',
        allowed_tools=[],  # 空 = 不限制
    )
    service.skill_registry.register(skill_a)
    service.skill_registry.register(skill_b)

    sandbox = service._build_sandbox({'agentConfig': {}})
    assert sandbox.allowed_tools == set()


def test_build_sandbox_unrestricted_when_all_skills_disabled(agent_service):
    service = agent_service
    skill = SkillDefinition(
        name='restricted',
        description='restricted skill',
        allowed_tools=['read_file'],
    )
    service.skill_registry.register(skill, enabled=False)

    sandbox = service._build_sandbox({'agentConfig': {}})
    assert sandbox.allowed_tools == set()


def test_requires_approval_tools_includes_edit_file():
    """edit_file 与 write_file / run_command 同属需确认工具集。"""
    assert 'edit_file' in AgentService.REQUIRES_APPROVAL_TOOLS
    assert 'write_file' in AgentService.REQUIRES_APPROVAL_TOOLS
    assert 'run_command' in AgentService.REQUIRES_APPROVAL_TOOLS


def test_f04_auto_approve_writes_covers_edit_file(agent_service, monkeypatch):
    """F04: autoApproveWrites=True 时，edit_file 应跳过用户确认直接执行。"""
    service = agent_service
    loop = asyncio.get_event_loop()

    tc = {'requestId': 'call_edit_1', 'name': 'edit_file',
          'arguments': {'path': '/tmp/e.py', 'old_string': 'a', 'new_string': 'b'}}

    call_count = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # 仅第一轮返回工具调用；第二轮不 yield → collected_tool_calls 为空 → 退出循环
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc}

    service._stream_llm = mock_stream_llm

    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id, 'providerId': 'test-provider', 'modelId': 'test-model',
            'agentConfig': {'enabled': True, 'maxIterations': 5, 'autoApproveWrites': True},
            'messages': [],
        }

    async def mock_append_message(conv_id, msg):
        pass

    async def mock_inject_batch(messages, conv_id, calls, results):
        pass

    monkeypatch.setattr(service, '_get_conversation', mock_get_conversation)
    monkeypatch.setattr(service, '_append_message', mock_append_message)
    monkeypatch.setattr(service, '_inject_tool_results_batch', mock_inject_batch)

    execute_calls = []

    class _FakeSandbox:
        def build_openai_tools_spec(self):
            return []

        async def execute(self, name, args):
            execute_calls.append((name, args))
            return {'success': True, 'content': 'ok'}

    monkeypatch.setattr(service, '_build_sandbox', lambda conv: _FakeSandbox())
    monkeypatch.setattr(service, '_get_provider', lambda conv: {
        'id': 'test-provider', 'apiBase': 'http://localhost', 'apiKey': 'k',
        'models': [{'id': 'test-model'}],
    })

    async def run():
        events = []
        async for event in service.process_message('conv-f04-edit', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())

    # 不应产生 requires_confirmation 事件（autoApproveWrites 跳过确认）
    assert not any('requires_confirmation' in ev for ev in events)
    # sandbox.execute 应被调用 1 次（edit_file）
    assert len(execute_calls) == 1
    assert execute_calls[0][0] == 'edit_file'

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
    # 阶段三 6.1：确认结果改为三态 dict
    assert service._confirmation_results[request_id] == {
        'approved': True, 'scope': 'once', 'feedback': None,
    }


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

    # 阶段三 6.1：返回三态 dict，approved=True
    result = loop.run_until_complete(run())
    assert result == {'approved': True, 'scope': 'once', 'feedback': None}


def test_wait_for_confirmation_timeout(agent_service, monkeypatch):
    service = agent_service
    monkeypatch.setattr(service, 'CONFIRMATION_TIMEOUT', 0.05)
    loop = asyncio.get_event_loop()
    # 阶段三 6.1：超时返回 None（与"拒绝"区分）
    assert loop.run_until_complete(service._wait_for_confirmation('call_1')) is None


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
    # 结果应被预缓存（三态 dict）
    assert service._confirmation_results[request_id] == {
        'approved': True, 'scope': 'once', 'feedback': None,
    }

    # 随后 _wait_for_confirmation 应直接消费预缓存结果，不阻塞
    async def run():
        return await service._wait_for_confirmation(request_id)

    result = loop.run_until_complete(run())
    assert result == {'approved': True, 'scope': 'once', 'feedback': None}
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


def test_default_rules_mark_write_tools_as_ask():
    """阶段三 6.1：默认规则从 ToolDefinition.requires_approval 元数据生成。
    write_file/edit_file/run_command 标注 requires_approval=True → 默认 ask；
    read_file 等只读工具 → 默认 allow。REQUIRES_APPROVAL_TOOLS 硬编码已删除。"""
    from services.tool_approval import build_default_rules
    from services.tool_registry import ToolRegistry
    rules = {r.action: r.effect for r in build_default_rules(ToolRegistry.get_instance())}
    assert rules.get('write_file') == 'ask'
    assert rules.get('edit_file') == 'ask'
    assert rules.get('run_command') == 'ask'
    assert rules.get('read_file') == 'allow'
    # 硬编码常量已删除，改由元数据驱动
    assert not hasattr(AgentService, 'REQUIRES_APPROVAL_TOOLS')


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


# ── 阶段二 N2-I2：overflow→压缩→重试环路 ──────────────────────


def test_context_overflow_triggers_compaction_retry(agent_service, monkeypatch):
    """N2-I2：_stream_llm 抛 context_overflow → process_message 压缩后原地重走。

    验证：
    - 主动压缩未触发（proactive 返回 None，compacted_once=False）
    - 首轮 overflow → 被动压缩 → compacted_once=True → continue
    - 次轮 _stream_llm 成功 → 正常结束
    - 已压缩过再次 overflow 不再重试（防死循环）
    """
    from agent_modules.agent_core.llm_stream import LLMError

    service = agent_service
    loop = asyncio.get_event_loop()

    stream_calls = [0]
    compact_calls = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        stream_calls[0] += 1
        if stream_calls[0] == 1:
            # 首轮：上下文超限
            raise LLMError('context_overflow', 400, 'maximum context length exceeded',
                           retryable=False)
        # 次轮：压缩后成功
        yield {'type': 'delta', 'delta': 'recovered'}

    service._stream_llm = mock_stream_llm

    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id, 'providerId': 'p', 'modelId': 'm',
            'agentConfig': {'enabled': True, 'maxIterations': 5},
            'messages': [{'role': 'user', 'content': 'x'}],
        }

    async def mock_compact(self, conv, system_prompt, max_tokens, provider):
        compact_calls[0] += 1
        if compact_calls[0] == 1:
            # 主动压缩：未超预算 → 不压缩
            return None, None
        # 被动压缩（overflow 触发）：返回压缩后的新消息
        return [
            {'role': 'system', 'content': system_prompt},
            {'role': 'system', 'content': '历史摘要：\n摘要内容'},
            {'role': 'user', 'content': 'x'},
        ], '摘要内容'

    async def mock_append_message(conv_id, msg):
        pass

    async def mock_build(self, conv):
        return 'system prompt'

    monkeypatch.setattr(service, '_get_conversation', mock_get_conversation)
    monkeypatch.setattr(service, '_context', type('Ctx', (), {
        'compact_if_needed': mock_compact,
        'build': mock_build,
    })())
    monkeypatch.setattr(service, '_append_message', mock_append_message)
    monkeypatch.setattr(service, '_build_sandbox', lambda conv: type('S', (), {
        'build_openai_tools_spec': lambda self: [],
    })())
    monkeypatch.setattr(service, '_get_provider', lambda conv: {
        'id': 'p', 'apiBase': 'http://localhost', 'apiKey': 'k',
        'models': [{'id': 'm'}],
    })

    async def run():
        events = []
        async for event in service.process_message('conv-overflow', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())

    # _stream_llm 被调用 2 次（首轮 overflow + 次轮成功）
    assert stream_calls[0] == 2
    # compact_if_needed 被调用 2 次（主动 + 被动）
    assert compact_calls[0] == 2

    deltas = [
        json.loads(ev[6:])['delta']
        for ev in events
        if json.loads(ev[6:]).get('type') == 'delta'
    ]
    # 被动压缩提示出现
    assert any('已自动压缩早期对话并重试' in d for d in deltas)
    # 压缩后重试的正文出现
    assert any('recovered' in d for d in deltas)


def test_context_overflow_twice_does_not_loop_forever(agent_service, monkeypatch):
    """N2-I2：已压缩过仍 overflow → 不再重试，直接提示结束（compacted_once 防死循环）。"""
    from agent_modules.agent_core.llm_stream import LLMError

    service = agent_service
    loop = asyncio.get_event_loop()

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # 每轮都 overflow
        raise LLMError('context_overflow', 400, 'too long', retryable=False)
        yield  # noqa: unreachable

    service._stream_llm = mock_stream_llm

    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id, 'providerId': 'p', 'modelId': 'm',
            'agentConfig': {'enabled': True, 'maxIterations': 5},
            'messages': [{'role': 'user', 'content': 'x'}],
        }

    compact_calls = [0]

    async def mock_compact(self, conv, system_prompt, max_tokens, provider):
        compact_calls[0] += 1
        if compact_calls[0] == 1:
            return None, None  # 主动不压缩
        return [{'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': 'x'}], '摘要'

    async def mock_build(self, conv):
        return 'system prompt'

    monkeypatch.setattr(service, '_get_conversation', mock_get_conversation)
    monkeypatch.setattr(service, '_context', type('Ctx', (), {
        'compact_if_needed': mock_compact,
        'build': mock_build,
    })())
    monkeypatch.setattr(service, '_append_message', lambda *a, **kw: _async_none())
    monkeypatch.setattr(service, '_build_sandbox', lambda conv: type('S', (), {
        'build_openai_tools_spec': lambda self: [],
    })())
    monkeypatch.setattr(service, '_get_provider', lambda conv: {
        'id': 'p', 'apiBase': 'http://localhost', 'apiKey': 'k',
        'models': [{'id': 'm'}],
    })

    async def run():
        events = []
        async for event in service.process_message('conv-overflow2', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())

    # 最多 2 次 _stream_llm（首轮 overflow→压缩→continue，次轮 overflow→直接结束）
    # compact 最多 2 次（主动 + 被动各 1）
    assert compact_calls[0] == 2
    # 以 done 事件结束（不崩溃）
    assert any(json.loads(ev[6:]).get('type') == 'done' for ev in events)


async def _async_none():
    return None


# ── 阶段三 6.1/6.2：审批引擎 + plan 模式集成测试 ───────────────


def _stub_agent_env(service, monkeypatch, conv_payload, stream_llm_mock,
                    sandbox_execute_spy=None, load_rules=None):
    """统一桩件：为 process_message 集成测试注入 mock，避免真实 DB/LLM。

    - conv_payload: mock _get_conversation 返回的 conv dict
    - stream_llm_mock: 替换 _stream_llm 的异步生成器函数
    - sandbox_execute_spy: list，记录 sandbox.execute 调用（None 则用空 sandbox）
    - load_rules: async 函数，替换 _load_persisted_rules（默认返回 []）
    """
    service._stream_llm = stream_llm_mock

    async def mock_get_conversation(conv_id):
        return conv_payload

    async def mock_append_message(conv_id, msg):
        pass

    async def mock_inject_batch(messages, conv_id, calls, results):
        pass

    if load_rules is None:
        async def load_rules(conv_id):
            return []

    monkeypatch.setattr(service, '_get_conversation', mock_get_conversation)
    monkeypatch.setattr(service, '_append_message', mock_append_message)
    monkeypatch.setattr(service, '_inject_tool_results_batch', mock_inject_batch)
    monkeypatch.setattr(service, '_load_persisted_rules', load_rules)
    monkeypatch.setattr(service, '_get_provider', lambda conv: {
        'id': 'p', 'apiBase': 'http://localhost', 'apiKey': 'k',
        'models': [{'id': 'm'}],
    })

    class _FakeSandbox:
        def build_openai_tools_spec(self):
            return []

        async def execute(self, name, args):
            if sandbox_execute_spy is not None:
                sandbox_execute_spy.append((name, args))
            return {'success': True, 'content': 'ok'}

    monkeypatch.setattr(service, '_build_sandbox', lambda conv: _FakeSandbox())


def test_plan_mode_denies_write_file_without_confirmation(agent_service, monkeypatch):
    """6.2：plan 模式下 write_file 被 deny 规则拦截，不发起确认、不执行。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    tc = _make_tool_call('write_file', {'path': '/a/b.py', 'content': 'x'}, 'call_plan_1')

    call_count = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc}

    conv = {
        'id': 'conv-plan', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5, 'preset': 'plan'},
        'messages': [],
    }
    execute_spy = []
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm, sandbox_execute_spy=execute_spy)

    async def run():
        events = []
        async for event in service.process_message('conv-plan', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())

    # 不应出现 requires_confirmation（plan 直接 deny，无需询问）
    assert not any('requires_confirmation' in ev for ev in events)
    # sandbox.execute 不应被调用（deny 在执行前拦截）
    assert execute_spy == []
    # 应有 tool_call_end 且 success=False
    end_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'tool_call_end'
    ]
    assert len(end_events) == 1
    assert end_events[0]['toolResult']['success'] is False
    assert '禁止' in end_events[0]['toolResult']['error']


def test_plan_mode_run_command_also_denied(agent_service, monkeypatch):
    """6.2：plan 模式下 run_command 同样被 deny（覆盖 command:* 规则）。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    tc = _make_tool_call('run_command', {'command': 'ls', 'cwd': '/a'}, 'call_plan_cmd')

    call_count = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc}

    conv = {
        'id': 'conv-plan2', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5, 'preset': 'plan'},
        'messages': [],
    }
    execute_spy = []
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm, sandbox_execute_spy=execute_spy)

    async def run():
        events = []
        async for event in service.process_message('conv-plan2', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    assert execute_spy == []
    assert not any('requires_confirmation' in ev for ev in events)


def test_plan_mode_readonly_tool_executes_normally(agent_service, monkeypatch):
    """6.2：plan 模式下只读工具（read_file）正常执行，不受 deny 影响。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    tc = _make_tool_call('read_file', {'path': '/a/b.py'}, 'call_plan_read')

    call_count = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc}

    conv = {
        'id': 'conv-plan3', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5, 'preset': 'plan'},
        'messages': [],
    }
    execute_spy = []
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm, sandbox_execute_spy=execute_spy)

    async def run():
        events = []
        async for event in service.process_message('conv-plan3', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    # read_file 默认 allow → 直接执行
    assert len(execute_spy) == 1
    assert execute_spy[0][0] == 'read_file'
    assert not any('requires_confirmation' in ev for ev in events)


def test_build_sandbox_plan_mode_restricts_to_readonly(agent_service):
    """6.2：_build_sandbox 在 plan 模式下只暴露只读工具集。"""
    service = agent_service
    sandbox = service._build_sandbox({'agentConfig': {'preset': 'plan'}})
    # 只读工具可见
    assert 'read_file' in sandbox.allowed_tools
    assert 'search_code' in sandbox.allowed_tools
    # 写工具不在白名单
    assert 'write_file' not in sandbox.allowed_tools
    assert 'edit_file' not in sandbox.allowed_tools
    assert 'run_command' not in sandbox.allowed_tools


def test_build_sandbox_build_mode_unrestricted(agent_service):
    """6.2：build 模式（默认）不限制工具可见性（由 skill 决定）。"""
    service = agent_service
    sandbox = service._build_sandbox({'agentConfig': {'preset': 'build'}})
    assert sandbox.allowed_tools == set()  # 空=全放行


def test_build_sandbox_plan_intersects_with_skill_whitelist(agent_service):
    """6.2：plan 模式与 skill 白名单取交集；skill 只能收窄不能放开写工具。"""
    service = agent_service
    skill = SkillDefinition(
        name='reader_skill',
        description='只读技能',
        allowed_tools=['read_file', 'search_code'],  # 都是只读
    )
    service.skill_registry.register(skill)
    try:
        sandbox = service._build_sandbox({'agentConfig': {'preset': 'plan'}})
        # 交集：{read_file, search_code} ∩ readonly = {read_file, search_code}
        assert sandbox.allowed_tools == {'read_file', 'search_code'}
    finally:
        service.skill_registry.unregister('reader_skill')


def test_build_system_prompt_plan_mode_appends_suffix(agent_service):
    """6.2：plan 模式系统提示词末尾追加只读声明。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    prompt = loop.run_until_complete(
        service._build_system_prompt({'agentConfig': {'preset': 'plan'}})
    )
    assert '规划模式' in prompt
    assert '不能修改文件或执行命令' in prompt
    # build 模式无后缀
    prompt_build = loop.run_until_complete(
        service._build_system_prompt({'agentConfig': {'preset': 'build'}})
    )
    assert '规划模式' not in prompt_build


def test_three_state_always_persists_rule_and_skips_next_confirmation(
    agent_service, monkeypatch,
):
    """6.1：用户选 scope='always' 批准 → 持久化规则 + 本轮后续相同调用直接放行。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    tc = _make_tool_call('write_file', {'path': '/a/b.py', 'content': 'x'}, 'call_always_1')

    persist_calls = []

    async def mock_persist(conv_id, action, resource, effect):
        persist_calls.append((conv_id, action, resource, effect))

    monkeypatch.setattr(service, '_persist_approval_rule', mock_persist)

    # 首轮：发确认事件后，用户用 scope=always 批准
    async def approve_after_confirm(request_id):
        await asyncio.sleep(0.05)
        service.submit_confirmation(request_id, True, scope='always')

    call_count = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc}

    conv = {
        'id': 'conv-always', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }

    # 拦截 _wait_for_confirmation：启动批准任务，返回真实等待
    original_wait = service._wait_for_confirmation

    async def patched_wait(request_id):
        task = loop.create_task(approve_after_confirm(request_id))
        result = await original_wait(request_id)
        await task
        return result

    monkeypatch.setattr(service, '_wait_for_confirmation', patched_wait)
    execute_spy = []
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm, sandbox_execute_spy=execute_spy)

    async def run():
        events = []
        async for event in service.process_message('conv-always', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())

    # 持久化规则被调用一次（action=write_file, resource=file:/a/b.py, effect=allow）
    assert len(persist_calls) == 1
    assert persist_calls[0] == ('conv-always', 'write_file', 'file:/a/b.py', 'allow')
    # 工具最终被执行（批准后执行）
    assert len(execute_spy) == 1


def test_reject_with_feedback_fed_back_to_model(agent_service, monkeypatch):
    """6.1：用户拒绝并附 feedback → tool result error 含 feedback 文本，模型可见。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    tc = _make_tool_call('run_command', {'command': 'rm -rf /', 'cwd': '/a'}, 'call_reject_1')

    async def reject_with_feedback(request_id):
        await asyncio.sleep(0.05)
        service.submit_confirmation(
            request_id, False, feedback='禁止删除操作',
        )

    call_count = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc}

    conv = {
        'id': 'conv-reject', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }

    original_wait = service._wait_for_confirmation

    async def patched_wait(request_id):
        task = loop.create_task(reject_with_feedback(request_id))
        result = await original_wait(request_id)
        await task
        return result

    monkeypatch.setattr(service, '_wait_for_confirmation', patched_wait)
    execute_spy = []
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm, sandbox_execute_spy=execute_spy)

    async def run():
        events = []
        async for event in service.process_message('conv-reject', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())

    # 工具未执行（被拒）
    assert execute_spy == []
    # tool_call_end 含 feedback
    end_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'tool_call_end'
    ]
    assert len(end_events) == 1
    assert end_events[0]['toolResult']['success'] is False
    assert '禁止删除操作' in end_events[0]['toolResult']['error']


def test_auto_approve_writes_does_not_leak_across_conversations(
    agent_service, monkeypatch,
):
    """N2-M3：autoApproveWrites 规则每会话构建，会话 A 的自动批准不影响会话 B。

    会话 A 设 autoApproveWrites=True，会话 B 不设。两个会话独立调用 process_message，
    B 的 write_file 仍需确认（不被 A 的规则放行）。规则在内存中不跨 process_message 调用累积。
    """
    service = agent_service
    loop = asyncio.get_event_loop()

    # 会话 A：autoApproveWrites=True，write_file 直接放行
    tc_a = _make_tool_call('write_file', {'path': '/a/x.py', 'content': 'x'}, 'call_a_1')
    call_count_a = [0]

    async def stream_a(provider, messages, tools, **kwargs):
        if call_count_a[0] == 0:
            call_count_a[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc_a}

    conv_a = {
        'id': 'conv-a', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5, 'autoApproveWrites': True},
        'messages': [],
    }
    execute_spy_a = []
    _stub_agent_env(service, monkeypatch, conv_a, stream_a, sandbox_execute_spy=execute_spy_a)

    async def run_a():
        events = []
        async for event in service.process_message('conv-a', 'test'):
            events.append(event)
        return events

    events_a = loop.run_until_complete(run_a())
    # A：autoApproveWrites → allow，无需确认直接执行
    assert len(execute_spy_a) == 1
    assert not any('requires_confirmation' in ev for ev in events_a)

    # 会话 B：不设 autoApproveWrites，write_file 应发起确认（ask）
    tc_b = _make_tool_call('write_file', {'path': '/b/y.py', 'content': 'y'}, 'call_b_1')
    call_count_b = [0]

    async def stream_b(provider, messages, tools, **kwargs):
        if call_count_b[0] == 0:
            call_count_b[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc_b}

    conv_b = {
        'id': 'conv-b', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},  # 无 autoApproveWrites
        'messages': [],
    }
    execute_spy_b = []

    # B 的确认：超时返回 None（不批准），避免测试阻塞
    async def wait_timeout(request_id):
        return None

    _stub_agent_env(service, monkeypatch, conv_b, stream_b, sandbox_execute_spy=execute_spy_b)
    monkeypatch.setattr(service, '_wait_for_confirmation', wait_timeout)
    # 缩短超时避免测试慢
    monkeypatch.setattr(service, 'CONFIRMATION_TIMEOUT', 0.05)

    async def run_b():
        events = []
        async for event in service.process_message('conv-b', 'test'):
            events.append(event)
        return events

    events_b = loop.run_until_complete(run_b())
    # B：write_file 走 ask → 发起确认 → 超时不执行
    assert any('requires_confirmation' in ev for ev in events_b)
    assert execute_spy_b == []  # 未批准，未执行


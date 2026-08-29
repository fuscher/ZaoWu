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


def test_get_provider_handles_null_providers_field(agent_service, tmp_path, monkeypatch):
    """providers.json 里 providers 为 null 不应让 _get_provider 抛 TypeError。

    旧代码 `data.get('providers', [])` 在 key 存在但值为 null 时返回 None（默认值
    仅在 key 缺失时使用）→ `for p in None` 抛 TypeError，被外层 except 吞掉，
    静默显示 'provider not configured'。修复后 `or []` 兜底，行为一致。
    """
    providers_file = tmp_path / 'providers.json'
    providers_file.write_text('{"providers": null}', encoding='utf-8')
    monkeypatch.setattr(
        'agent_modules.agent_core.agent_service.PROVIDERS_FILE', str(providers_file)
    )
    # 不抛异常，返回 None（provider not configured）
    assert agent_service._get_provider({'providerId': 'p1'}) is None


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
    # 阶段 A5：循环中断文案迁移到 notice 事件（不再混流 delta）
    notices = [
        json.loads(ev[6:])
        for ev in events
        if json.loads(ev[6:]).get('type') == 'notice'
    ]
    assert any('连续重复调用' in n.get('message', '') for n in notices), \
        'A-A-A should trigger loop detection'
    # 阶段 A4：以 quality=stopped 的 done 事件结束（字面量 (loop detected, stopped) 已根除）
    done_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'done'
    ]
    assert done_events and done_events[-1].get('quality') == 'stopped'


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


# ── S13-P0-2: maxIterations 读取处兜底钳制（防御历史脏数据） ─────

@pytest.mark.parametrize('configured, expected', [
    (0, 1),       # 脏数据 0 → 钳制到下限 1（max(1, min(100, 0))）
    ('abc', 10),  # 脏数据非 int → 回退默认 10
    (True, 10),   # bool（int 子类）→ 回退默认 10
    (200, 100),   # 越界 → 钳制上限 100
    (5, 5),       # 合法 → 原样
])
def test_max_iterations_clamped_read(agent_service, monkeypatch, configured, expected):
    """S13-P0-2: maxIterations 读取处兜底钳制（防御历史脏数据），
    每轮均产出工具调用使循环持续到 for 耗尽 → notice 声明实际循环上限。"""
    service = agent_service
    loop = asyncio.get_event_loop()

    counter = {'n': 0}

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # 每轮返回不同参数的工具调用（避免 F05 streak 误判），持续循环到 for 耗尽
        n = counter['n']
        counter['n'] += 1
        yield {
            'type': 'tool_call_part',
            'tool_call': _make_tool_call(
                'read_file', {'path': f'/tmp/t{n}.txt'}, f'call_{n}'
            ),
        }

    service._stream_llm = mock_stream_llm

    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id,
            'providerId': 'test-provider',
            'modelId': 'test-model',
            'agentConfig': {'enabled': True, 'maxIterations': configured},
            'messages': [],
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
        async for event in service.process_message('conv-maxit', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    # 每轮都有工具 → for 耗尽 → quality=incomplete，notice 声明实际循环上限
    notices = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'notice'
    ]
    reached = next(
        (n for n in notices if n.get('code') == 'max_iterations_reached'), None
    )
    assert reached is not None, 'expect max_iterations_reached notice'
    assert f'（{expected}）' in reached.get('message', ''), \
        f'expected clamped cap {expected}, got {reached.get("message")}'
    done_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'done'
    ]
    assert done_events and done_events[-1].get('quality') == 'incomplete'


# ── S13-P1-2: 遥测聚合（usage/tool_count/iterations/quality/duration） ─────

def test_telemetry_records_aggregated_fields(agent_service, monkeypatch):
    """S13-P1-2: process_message 收尾调用 record_agent_run，
    usage 累计、工具/轮次计数、quality、duration_ms 字段齐全。"""
    service = agent_service
    loop = asyncio.get_event_loop()

    counter = {'n': 0}

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # 模拟真实 _stream_llm 的 usage 拦截累计（测试聚焦聚合路径）
        n = counter['n']
        counter['n'] += 1
        service._tokens_in += 100
        service._tokens_out += 50
        if tools is None:
            # S15-E-P1-3（E10）：耗尽总结重试走 tools=None 纯文本
            yield {'type': 'delta', 'delta': f'summary-{n}'}
            return
        yield {
            'type': 'tool_call_part',
            'tool_call': _make_tool_call(
                'read_file', {'path': f'/tmp/t{n}.txt'}, f'call_{n}'
            ),
        }

    service._stream_llm = mock_stream_llm

    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id,
            'providerId': 'test-provider',
            'modelId': 'test-model',
            'agentConfig': {'enabled': True, 'maxIterations': 10},
            'messages': [],
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

    import services.agent_telemetry as telemetry
    calls = []
    monkeypatch.setattr(
        telemetry, 'record_agent_run',
        lambda **fields: calls.append(fields),
    )

    async def run():
        events = []
        async for event in service.process_message('conv-telemetry', 'test'):
            events.append(event)
        return events

    loop.run_until_complete(run())

    assert len(calls) == 1, 'expect exactly one telemetry record'
    rec = calls[0]
    assert rec['conv_id'] == 'conv-telemetry'
    assert rec['model'] == 'test-model'
    assert rec['tokens_in'] == 100 * 11, f"got {rec['tokens_in']}"
    assert rec['tokens_out'] == 50 * 11, f"got {rec['tokens_out']}"
    assert rec['tool_count'] == 10, f"got {rec['tool_count']}"
    assert rec['iterations'] == 10, f"got {rec['iterations']}"
    assert rec['quality'] == 'incomplete', f"got {rec['quality']}"
    assert rec['error_code'] is None
    assert isinstance(rec['duration_ms'], int) and rec['duration_ms'] >= 0


def test_telemetry_write_failure_does_not_break(agent_service, monkeypatch):
    """S13-P1-2: record_agent_run 抛异常不阻断 process_message 主流程。"""
    service = agent_service
    loop = asyncio.get_event_loop()

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # 空响应：IdleDetector 重试一次后终态 empty（不再有更多 LLM 调用）
        if False:
            yield  # pragma: no cover — 空生成器，永不产出事件

    service._stream_llm = mock_stream_llm

    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id,
            'providerId': 'test-provider',
            'modelId': 'test-model',
            'agentConfig': {'enabled': True, 'maxIterations': 10},
            'messages': [],
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

    import services.agent_telemetry as telemetry

    def _boom(**fields):
        raise RuntimeError('disk full')

    monkeypatch.setattr(telemetry, 'record_agent_run', _boom)

    async def run():
        events = []
        async for event in service.process_message('conv-telemetry-fail', 'test'):
            events.append(event)
        return events

    # 主流程不抛异常
    events = loop.run_until_complete(run())
    done_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'done'
    ]
    assert done_events, 'process_message should still complete normally'


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

    async def mock_compact(self, conv, system_prompt, max_tokens, provider,
                           ref_tokens=0):
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

    # 阶段 A5：压缩提示迁移到 notice(code=compacted) + phase(compacting) 结构化事件
    notices = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'notice'
    ]
    assert any(n.get('code') == 'compacted' for n in notices), \
        'compaction should emit notice(compacted)'
    phases = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'phase'
    ]
    assert any(p.get('phase') == 'compacting' for p in phases), \
        'compaction should emit phase(compacting)'
    # 压缩后重试的正文出现（模型 delta 通道不变）
    deltas = [
        json.loads(ev[6:])['delta'] for ev in events
        if json.loads(ev[6:]).get('type') == 'delta'
    ]
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

    async def mock_compact(self, conv, system_prompt, max_tokens, provider,
                           ref_tokens=0):
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
    # 阶段 A3/A4：已压缩过再次 overflow → 结构化 error 事件收尾（不再兜底 done 通道）
    error_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'error'
    ]
    assert error_events, 'overflow after compaction should emit error event'
    assert error_events[-1].get('code') == 'context_too_long'


async def _async_none():
    return None


# ── maxTokens 取值链：会话级 → 全局 config → 4096 ─────────────


def _make_max_tokens_run(service, loop, conv_payload, global_config=None,
                         monkeypatch=None, tmp_path=None):
    """跑一轮 process_message 并捕获传给 _stream_llm 的 max_tokens。

    返回 (events, max_tokens_list)。conv 无历史消息 → 主动压缩不触发，
    一轮 delta 即收尾，_stream_llm 恰好调用一次。
    """
    captured = []

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        captured.append(kwargs.get('max_tokens'))
        yield {'type': 'delta', 'delta': 'ok'}

    _stub_agent_env(service, monkeypatch, conv_payload, mock_stream_llm)

    if global_config is not None:
        cfg_file = tmp_path / 'chat_config.json'
        cfg_file.write_text(json.dumps(global_config), encoding='utf-8')
        monkeypatch.setattr(
            'agent_modules.agent_core.agent_service.CONFIG_FILE', str(cfg_file)
        )

    async def run():
        events = []
        async for event in service.process_message('conv-mt', 'test'):
            events.append(event)
        return events
        return events

    events = loop.run_until_complete(run())
    return events, captured


def test_agent_uses_conv_level_max_tokens(agent_service, monkeypatch, tmp_path):
    """会话级 maxTokens 优先：conv.maxTokens=2000 → _stream_llm 收到 2000。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    conv = {
        'id': 'conv-mt', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'maxTokens': 2000,
        'messages': [],
    }
    # 即使全局配置存在也不应覆盖会话级值
    events, captured = _make_max_tokens_run(
        service, loop, conv, global_config={'maxTokens': 3000},
        monkeypatch=monkeypatch, tmp_path=tmp_path,
    )
    assert captured == [2000]
    assert any('done' in ev for ev in events)


def test_agent_falls_back_to_global_config_max_tokens(agent_service, monkeypatch, tmp_path):
    """会话未设置 maxTokens（None）→ 回退全局 config 的 3000。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    conv = {
        'id': 'conv-mt', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    events, captured = _make_max_tokens_run(
        service, loop, conv, global_config={'maxTokens': 3000},
        monkeypatch=monkeypatch, tmp_path=tmp_path,
    )
    assert captured == [3000]


def test_agent_defaults_to_4096_when_config_missing(agent_service, monkeypatch, tmp_path):
    """全局 config 文件不存在 → 兜底 4096。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    conv = {
        'id': 'conv-mt', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    # CONFIG_FILE 指向不存在的路径
    monkeypatch.setattr(
        'agent_modules.agent_core.agent_service.CONFIG_FILE',
        str(tmp_path / 'does_not_exist.json'),
    )
    events, captured = _make_max_tokens_run(
        service, loop, conv, monkeypatch=monkeypatch, tmp_path=tmp_path,
    )
    assert captured == [4096]


def test_agent_defaults_to_4096_when_config_corrupt(agent_service, monkeypatch, tmp_path):
    """全局 config 文件损坏 → 兜底 4096（不崩溃）。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    conv = {
        'id': 'conv-mt', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    cfg_file = tmp_path / 'chat_config.json'
    cfg_file.write_text('{not valid json', encoding='utf-8')
    monkeypatch.setattr(
        'agent_modules.agent_core.agent_service.CONFIG_FILE', str(cfg_file)
    )
    events, captured = _make_max_tokens_run(
        service, loop, conv, monkeypatch=monkeypatch, tmp_path=tmp_path,
    )
    assert captured == [4096]


def test_agent_ignores_conv_none_max_tokens(agent_service, monkeypatch, tmp_path):
    """conv.maxTokens 显式 None（旧库迁移后）→ 回退全局，而非当 0/4096。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    conv = {
        'id': 'conv-mt', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'maxTokens': None,
        'messages': [],
    }
    events, captured = _make_max_tokens_run(
        service, loop, conv, global_config={'maxTokens': 3000},
        monkeypatch=monkeypatch, tmp_path=tmp_path,
    )
    assert captured == [3000]


def test_agent_clamps_generation_tokens(agent_service, monkeypatch, tmp_path):
    """生成参数钳制：压缩预算 1M 时，发送给 LLM 的 max_tokens 钳制到 131072。"""
    from agent_modules.agent_core.agent_service import MAX_GENERATION_TOKENS
    service = agent_service
    loop = asyncio.get_event_loop()
    conv = {
        'id': 'conv-mt', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'maxTokens': 1000000,
        'messages': [],
    }
    events, captured = _make_max_tokens_run(
        service, loop, conv, monkeypatch=monkeypatch, tmp_path=tmp_path,
    )
    assert captured == [MAX_GENERATION_TOKENS]


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
    assert '计划模式' in prompt
    assert '不能修改文件或执行命令' in prompt
    # build 模式无后缀
    prompt_build = loop.run_until_complete(
        service._build_system_prompt({'agentConfig': {'preset': 'build'}})
    )
    assert '计划模式' not in prompt_build


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


# ── 阶段 A：结构化 SSE 事件协议（设计文档 §3.2.1 / §5） ──────────


def test_phase_event_format():
    """A1: phase 事件结构（thinking/compacting/retrying/handoff/done）。"""
    event = AgentService._phase_event('msg-1', 'compacting', detail='预算触发主动压缩')
    payload = json.loads(event[6:])
    assert payload['type'] == 'phase'
    assert payload['id'] == 'msg-1'
    assert payload['phase'] == 'compacting'
    assert payload['detail'] == '预算触发主动压缩'
    assert 'ts' in payload
    # ensure_ascii=False：中文不转义为 \uXXXX
    assert r'\u' not in event


def test_tool_part_event_format():
    """A1: tool_part 事件结构（含 reason）。"""
    event = AgentService._tool_part_event(
        'msg-1', 'call_1', 'denied', reason='plan_mode_readonly',
    )
    payload = json.loads(event[6:])
    assert payload['type'] == 'tool_part'
    assert payload['requestId'] == 'call_1'
    assert payload['part'] == 'denied'
    assert payload['reason'] == 'plan_mode_readonly'
    # 无 reason 时不带该字段
    event2 = AgentService._tool_part_event('msg-1', 'call_2', 'running')
    assert 'reason' not in json.loads(event2[6:])
    # D3: ensure_ascii=False — 含中文 reason 不转义（tool_part 中文信号最强场景）
    event3 = AgentService._tool_part_event(
        'msg-1', 'call_3', 'denied', reason='plan_mode_readonly',
    )
    assert r'\u' not in event3


def test_notice_event_format():
    """A1: notice 事件结构（level/code/message/recoverable）。"""
    event = AgentService._notice_event(
        'warn', 'intent_not_executed', '模型声明了工具意图但未执行', recoverable=True,
    )
    payload = json.loads(event[6:])
    assert payload['type'] == 'notice'
    assert payload['id'] == 'system'
    assert payload['level'] == 'warn'
    assert payload['code'] == 'intent_not_executed'
    assert payload['recoverable'] is True
    # D3: ensure_ascii=False — message 中文不转义为 \uXXXX（含中文必现场景）
    assert r'\u' not in event
    assert payload['message'] == '模型声明了工具意图但未执行'
    # 未传 recoverable 时不带该字段
    event2 = AgentService._notice_event('info', 'compacted', '已压缩')
    assert 'recoverable' not in json.loads(event2[6:])


def test_error_event_v2_format():
    """A1: error 事件结构（code/message/kind/recovery/traceId）。"""
    recovery = [{'label': '重试', 'action': 'retry'}]
    event = AgentService._error_event_v2(
        'msg-1', 'llm_auth', 'API 鉴权失败', kind='auth',
        recovery=recovery, trace_id='agent-error-a1b2',
    )
    payload = json.loads(event[6:])
    assert payload['type'] == 'error'
    assert payload['code'] == 'llm_auth'
    assert payload['kind'] == 'auth'
    assert payload['recovery'] == recovery
    assert payload['traceId'] == 'agent-error-a1b2'
    assert 'done' not in payload  # 与 done 通道彻底分离
    # D3: ensure_ascii=False — message 与 recovery label 中文不转义（含中文必现场景）
    assert r'\u' not in event
    assert payload['message'] == 'API 鉴权失败'
    assert payload['recovery'][0]['label'] == '重试'


def test_done_event_quality_and_summary():
    """A1: done 事件携带 quality/summary/phase_history。"""
    event = AgentService._done_event(
        'msg-1', 'final', quality='idle',
        summary='未执行声明的工具操作', phase_history=['thinking', 'done'],
    )
    payload = json.loads(event[6:])
    assert payload['type'] == 'done'
    assert payload['quality'] == 'idle'
    assert payload['summary'] == '未执行声明的工具操作'
    assert payload['phase_history'] == ['thinking', 'done']
    # 默认 quality=success（向后兼容旧 done）
    event2 = AgentService._done_event('msg-2', 'ok')
    assert json.loads(event2[6:])['quality'] == 'success'


# ── 阶段 A2：ErrorClassifier 异常映射 ──────────────────────────


def test_error_classifier_auth():
    from agent_modules.agent_core.error_classifier import classify
    from agent_modules.agent_core.llm_stream import LLMError
    payload = classify(LLMError('auth', 401, 'unauthorized', retryable=False))
    assert payload['code'] == 'llm_auth'
    assert payload['kind'] == 'auth'
    assert any(r['action'] == 'open:settings:providers' for r in payload['recovery'])


def test_error_classifier_rate_limit():
    from agent_modules.agent_core.error_classifier import classify
    from agent_modules.agent_core.llm_stream import LLMError
    payload = classify(LLMError('rate_limit', 429, 'slow down', retryable=True))
    assert payload['code'] == 'llm_rate_limit'
    assert any(r['action'] == 'retry' for r in payload['recovery'])


def test_error_classifier_context_overflow():
    from agent_modules.agent_core.error_classifier import classify
    from agent_modules.agent_core.llm_stream import LLMError
    payload = classify(LLMError('context_overflow', 400, 'too long', retryable=False))
    assert payload['code'] == 'context_too_long'
    actions = {r['action'] for r in payload['recovery']}
    assert 'clear_messages' in actions
    assert 'open:model_switcher' in actions


def test_error_classifier_timeout_and_connect():
    from agent_modules.agent_core.error_classifier import classify
    import httpx
    payload = classify(httpx.TimeoutException('timeout'))
    assert payload['code'] == 'timeout'
    payload2 = classify(httpx.ConnectError('refused'))
    assert payload2['code'] == 'connect_failed'


def test_error_classifier_llm_timeout_kind_maps_to_timeout():
    """主流程修复：_stream_llm 把 httpx.TimeoutException 包装为 LLMError('timeout')，
    classify 必须识别该 kind → code=timeout（此前落入 internal 兜底，语义丢失）。"""
    from agent_modules.agent_core.error_classifier import classify
    from agent_modules.agent_core.llm_stream import LLMError
    payload = classify(LLMError('timeout', 0, 'httpx.TimeoutException: timed out',
                                retryable=False))
    assert payload['code'] == 'timeout'
    assert payload['kind'] == 'timeout'
    assert any(r['action'] == 'retry' for r in payload['recovery'])


def test_error_classifier_llm_connect_error_kind_maps_to_connect_failed():
    """主流程修复：_stream_llm 把 httpx.ConnectError 包装为 LLMError('connect_error')，
    classify 必须识别该 kind → code=connect_failed（此前落入 internal 兜底）。"""
    from agent_modules.agent_core.error_classifier import classify
    from agent_modules.agent_core.llm_stream import LLMError
    payload = classify(LLMError('connect_error', 0, 'httpx.ConnectError: refused',
                                retryable=False))
    assert payload['code'] == 'connect_failed'
    assert payload['kind'] == 'connect_error'
    assert any(r['action'] == 'open:settings:providers' for r in payload['recovery'])


def test_error_classifier_internal_has_trace_id_support():
    from agent_modules.agent_core.error_classifier import classify, new_trace_id
    payload = classify(ValueError('boom'))
    assert payload['code'] == 'internal'
    assert payload['kind'] == 'ValueError'
    assert any(r['action'] == 'retry' for r in payload['recovery'])
    tid = new_trace_id()
    assert tid.startswith('agent-error-')


# ── 阶段 A3/A4：错误分流与 quality 端到端 ─────────────────────


def test_llm_auth_error_emits_error_event(agent_service, monkeypatch):
    """A3: LLMError(auth) → type:error code=llm_auth（非 done，非 delta 文本混流）。"""
    service = agent_service
    loop = asyncio.get_event_loop()

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        from agent_modules.agent_core.llm_stream import LLMError
        raise LLMError('auth', 401, 'unauthorized', retryable=False)
        yield  # noqa

    conv = {
        'id': 'conv-auth', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm)

    async def run():
        events = []
        async for event in service.process_message('conv-auth', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    error_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'error'
    ]
    assert error_events, 'auth error should emit structured error event'
    assert error_events[-1]['code'] == 'llm_auth'
    # 不再以 done 通道出现
    assert not any(json.loads(ev[6:]).get('type') == 'done' for ev in events)
    # 不混流 delta 文本
    assert not any('请求失败' in json.loads(ev[6:]).get('delta', '') for ev in events)


def test_rate_limit_error_emits_error_event(agent_service, monkeypatch):
    """A3: LLMError(rate_limit) → type:error code=llm_rate_limit。"""
    service = agent_service
    loop = asyncio.get_event_loop()

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        from agent_modules.agent_core.llm_stream import LLMError
        raise LLMError('rate_limit', 429, 'slow down', retryable=False)
        yield  # noqa

    conv = {
        'id': 'conv-rl', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm)

    async def run():
        events = []
        async for event in service.process_message('conv-rl', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    error_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'error'
    ]
    assert error_events and error_events[-1]['code'] == 'llm_rate_limit'


def test_timeout_connect_error_emits_error_event(agent_service, monkeypatch):
    """A3: httpx 网络异常 → 结构化 error 事件（timeout/connect_failed）。"""
    import httpx
    service = agent_service
    loop = asyncio.get_event_loop()

    for exc, code in [
        (httpx.TimeoutException('slow'), 'timeout'),
        (httpx.ConnectError('refused'), 'connect_failed'),
    ]:
        def make_stream(exc):
            async def mock_stream_llm(provider, messages, tools, **kwargs):
                raise exc
                yield  # noqa
            return mock_stream_llm

        conv = {
            'id': f'conv-net-{code}', 'providerId': 'p', 'modelId': 'm',
            'agentConfig': {'enabled': True, 'maxIterations': 5},
            'messages': [],
        }
        _stub_agent_env(service, monkeypatch, conv, make_stream(exc))

        async def run():
            events = []
            async for event in service.process_message(f'conv-net-{code}', 'test'):
                events.append(event)
            return events

        events = loop.run_until_complete(run())
        error_events = [
            json.loads(ev[6:]) for ev in events
            if json.loads(ev[6:]).get('type') == 'error'
        ]
        assert error_events and error_events[-1]['code'] == code, code


def test_unhandled_exception_emits_error_event(agent_service, monkeypatch):
    """A3: 未捕获异常 → type:error code=internal + 落库 error_fallback metadata。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    persisted = []

    async def mock_get_conversation(conv_id):
        raise ValueError('boom in store')
        return None  # noqa

    async def mock_append_message(conv_id, msg):
        persisted.append(msg)

    monkeypatch.setattr(service, '_get_conversation', mock_get_conversation)
    monkeypatch.setattr(service, '_append_message', mock_append_message)

    async def run():
        events = []
        async for event in service.process_message('conv-err', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    error_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'error'
    ]
    assert error_events
    assert error_events[-1]['code'] == 'internal'
    assert error_events[-1]['traceId'].startswith('agent-error-')
    assert any(r['action'] == 'retry' for r in error_events[-1]['recovery'])
    # 落库 metadata：quality=error_fallback + error_code
    assert persisted, 'error message should be persisted'
    meta = persisted[0].get('metadata', {})
    assert meta.get('quality') == 'error_fallback'
    assert meta.get('error_code') == 'internal'


def test_no_completed_literal_in_output(agent_service, monkeypatch):
    """A4: 空转终态不再产生 (completed) 字面量（SSE 与落库双通道）。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    persisted = []

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # 模型两轮都完全空响应（无正文无工具）
        return
        yield  # noqa

    conv = {
        'id': 'conv-empty-lit', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm)

    async def mock_append(conv_id, msg):
        persisted.append(msg)

    monkeypatch.setattr(service, '_append_message', mock_append)

    async def run():
        events = []
        async for event in service.process_message('conv-empty-lit', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    assert not any('(completed)' in ev for ev in events)
    assert all('(completed)' not in (m.get('content') or '') for m in persisted)
    # 落库摘要非空 + quality=empty
    assert persisted, 'final message should be persisted'
    final_msg = persisted[-1]
    assert final_msg['content'] == '模型未生成有效响应，请重试。'
    assert final_msg['metadata']['quality'] == 'empty'


def test_metadata_quality_persisted_on_success(agent_service, monkeypatch):
    """A6: 正常完成落库 metadata.quality=success，SSE done 携带 quality。

    阶段 B2：mock 文本含结论性信号（结论词），否则 IdleDetector 会判 idle。
    """
    service = agent_service
    loop = asyncio.get_event_loop()
    persisted = []

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        yield {'type': 'delta', 'delta': '已经完成。结果是成功。'}

    conv = {
        'id': 'conv-meta', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm)

    async def mock_append(conv_id, msg):
        persisted.append(msg)

    monkeypatch.setattr(service, '_append_message', mock_append)

    async def run():
        events = []
        async for event in service.process_message('conv-meta', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    done_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'done'
    ]
    assert done_events[-1]['quality'] == 'success'
    assert persisted[-1]['metadata']['quality'] == 'success'


def test_stop_emits_quality_stopped_and_notice(agent_service, monkeypatch):
    """A4: 用户停止 → notice(user_stopped) + done quality=stopped + 落库 stopped。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    persisted = []

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        service.stop_event.set()  # 模拟流式开始后用户点停止
        return
        yield  # noqa

    conv = {
        'id': 'conv-stop2', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm)

    async def mock_append(conv_id, msg):
        persisted.append(msg)

    monkeypatch.setattr(service, '_append_message', mock_append)

    async def run():
        events = []
        async for event in service.process_message('conv-stop2', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    notices = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'notice'
    ]
    assert any(n.get('code') == 'user_stopped' for n in notices)
    done_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'done'
    ]
    assert done_events and done_events[-1]['quality'] == 'stopped'
    # 落库不含 (已停止) 字面量
    assert all('(已停止)' not in (m.get('content') or '') for m in persisted)


def test_plan_mode_empty_final_quality_constrained(agent_service, monkeypatch):
    """A4: plan 模式无文本无工具 → quality=constrained（只读解释语义，不标 empty）。"""
    service = agent_service
    loop = asyncio.get_event_loop()

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        return
        yield  # noqa

    conv = {
        'id': 'conv-plan-empty', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5, 'preset': 'plan'},
        'messages': [],
    }
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm)

    async def run():
        events = []
        async for event in service.process_message('conv-plan-empty', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    done_events = [
        json.loads(ev[6:]) for ev in events
        if json.loads(ev[6:]).get('type') == 'done'
    ]
    assert done_events and done_events[-1]['quality'] == 'constrained'
    assert '计划模式' in done_events[-1]['content']


# ── 阶段 B1：IntentMatcher + ConclusiveSignalMatcher ───────────


def test_intent_matcher_hits_chinese_commitment():
    from agent_modules.agent_core.intent_patterns import IntentMatcher
    m = IntentMatcher()
    for text in ['我先读取这个文件', '让我检查一下配置', '接下来调用 read_file',
                 '我将修改 src/main.py', '我来读取测试文件', '我去查看日志']:
        assert m.matches(text), text


def test_intent_matcher_hits_english_commitment():
    from agent_modules.agent_core.intent_patterns import IntentMatcher
    m = IntentMatcher()
    for text in ["I'll read the file", 'let me check the config', 'going to edit main.py',
                 'I will modify this', 'let me look at the tests']:
        assert m.matches(text), text


def test_intent_matcher_excludes_advisory():
    from agent_modules.agent_core.intent_patterns import IntentMatcher
    m = IntentMatcher()
    # 建议性弱信号 → 负例（"建议你手动删除 X" 是建议不是承诺）
    assert not m.matches('建议你手动删除那个文件')
    assert not m.matches('我建议你先重启服务')
    assert not m.matches('你可以直接修改配置')
    assert not m.matches('i suggest you delete it')
    assert not m.matches('you could check the log')
    # 承诺 + 建议混合 → 建议整段排除
    assert not m.matches('我先读取文件，但我建议你手动删除')


def test_intent_matcher_short_text_and_plain():
    from agent_modules.agent_core.intent_patterns import IntentMatcher
    m = IntentMatcher()
    assert not m.matches('嗯')
    assert not m.matches('好')
    assert not m.matches('这个比较复杂')
    assert not m.matches('我先了解一下')  # 无承诺执行语义


def test_intent_matcher_locator_phrases_not_matched_as_intent():
    """R3 防御回归："我先定位…"是承诺性但无结论信号 → 应判 idle（软警告）。

    若 IntentMatcher 误把"定位"当结论词（或当承诺命中但后续被误判 success），
    标注集样本会兜住；此处直接断言定位短语在意图与结论两通道均为 False。
    """
    from agent_modules.agent_core.intent_patterns import IntentMatcher, ConclusiveSignalMatcher
    m = IntentMatcher()
    c = ConclusiveSignalMatcher()
    for text in ['我先定位这个 bug', '我先定位问题所在', '让我先定位一下']:
        assert not m.matches(text), f'{text} 不应命中承诺意图'
        assert not c.is_conclusive(text), f'{text} 不应命中结论信号'


def test_conclusive_locator_zh_danger_variant():
    """危险变体防御（2026-08-07）："我先定位到问题所在"承诺未兑现但含"到"，
    (b) 结论词若保留"定位到"会误判 success。已改"已定位到"——完成语义保留、
    承诺变体排除。断言两通道行为 + 完成语义负例不受影响。
    """
    from agent_modules.agent_core.intent_patterns import ConclusiveSignalMatcher
    c = ConclusiveSignalMatcher()
    # 承诺变体（含"到"）：不命中结论信号
    assert not c.is_conclusive('我先定位到问题所在')
    # 完成语义（"已定位到"）：命中结论信号
    assert c.is_conclusive('已定位到问题所在')
    # 裸"定位到"根因陈述：不再命中（非完成语义）
    assert not c.is_conclusive('定位到内存泄漏在缓存层')


def test_conclusive_signal_code_block():
    from agent_modules.agent_core.intent_patterns import ConclusiveSignalMatcher
    m = ConclusiveSignalMatcher()
    assert m.is_conclusive('代码如下：```python\nx = 1\n```')
    assert m.is_conclusive('函数签名是 `def foo()`')
    assert not m.is_conclusive('这里什么都没有')


def test_conclusive_signal_keywords():
    from agent_modules.agent_core.intent_patterns import ConclusiveSignalMatcher
    m = ConclusiveSignalMatcher()
    for text in ['结论是这里存在内存泄漏', '综上所述，问题出在缓存',
                 '已经完成全部修改', '修改了 main.py 第 42 行',
                 '结果是测试全部通过', '原因是登录态过期',
                 'the issue is the cache', "i've fixed the bug",
                 'in conclusion, it works']:
        assert m.is_conclusive(text), text
    # 裸"建议/已经/result"不入选（弱信号）
    assert not m.is_conclusive('已经')
    assert not m.is_conclusive('result')
    # 建议性前缀排除
    assert not m.is_conclusive('建议你手动删除那个文件')


def test_conclusive_signal_sentence_length():
    from agent_modules.agent_core.intent_patterns import ConclusiveSignalMatcher
    m = ConclusiveSignalMatcher()
    # ≥40 字符 且 ≥2 句末标点 → 结论性
    long_text = '这个问题需要从两个方面来看。第一是内存分配的策略问题。第二是对象生命周期管理的缺陷。'
    assert len(long_text) >= 40
    assert m.is_conclusive(long_text)
    # 短文本无结论词 → 非结论性（"这个问题已经很复杂了"应为 idle）
    assert not m.is_conclusive('这个问题已经很复杂了')
    assert not m.is_conclusive('我先了解一下背景')


# ── 阶段 B2：IdleDetector 决策图全分支 ────────────────────────


def test_idle_detector_no_text_with_history_tools_success():
    from agent_modules.agent_core.idle_detector import IdleDetector
    d = IdleDetector()
    dec = d.detect(collected_text='', full_text='',
                   executed_tool_names=['read_file'], preset='build')
    assert dec.quality == 'success'
    assert dec.action == 'terminal'


def test_idle_detector_no_text_plan_constrained():
    from agent_modules.agent_core.idle_detector import IdleDetector
    d = IdleDetector()
    dec = d.detect(collected_text='', full_text='',
                   executed_tool_names=[], preset='plan')
    assert dec.quality == 'constrained'
    assert dec.action == 'terminal'


def test_idle_detector_empty_retries_once_then_terminal():
    from agent_modules.agent_core.idle_detector import IdleDetector
    d = IdleDetector()
    # build + 无文本无工具：首次 empty+重试，二次 empty 终态
    dec1 = d.detect(collected_text='', full_text='',
                    executed_tool_names=[], preset='build')
    assert dec1.quality == 'empty'
    assert dec1.action == 'retry_empty'
    assert dec1.notice_code == 'retrying_empty'
    dec2 = d.detect(collected_text='', full_text='',
                    executed_tool_names=[], preset='build')
    assert dec2.quality == 'empty'
    assert dec2.action == 'terminal'


def test_idle_detector_intent_first_correction_then_terminal():
    from agent_modules.agent_core.idle_detector import IdleDetector
    d = IdleDetector()
    dec1 = d.detect(collected_text='我先读取这个文件', full_text='',
                    executed_tool_names=[], preset='build')
    assert dec1.quality == 'idle'
    assert dec1.action == 'inject_correction_retry'
    assert dec1.notice_code == 'intent_not_executed'
    assert dec1.correction and '系统纠正' in dec1.correction
    # 二次仍 idle → 终态
    dec2 = d.detect(collected_text='我先读取这个文件', full_text='',
                    executed_tool_names=[], preset='build')
    assert dec2.quality == 'idle'
    assert dec2.action == 'terminal'


def test_idle_detector_retry_counts_persist_without_reset():
    """重试计数在实例内累积且两通道独立：空响应重试不消耗说而不做的纠正机会。"""
    from agent_modules.agent_core.idle_detector import IdleDetector
    d = IdleDetector()
    # 空响应重试后 empty_retry_count=1
    d.detect(collected_text='', full_text='',
             executed_tool_names=[], preset='build')
    assert d.empty_retry_count == 1
    # 再次空响应 → 终态（不会无限重试）
    dec = d.detect(collected_text='', full_text='',
                   executed_tool_names=[], preset='build')
    assert dec.action == 'terminal'
    assert dec.quality == 'empty'


def test_idle_detector_counts_independent_empty_then_intent():
    """独立计数：空响应重试后，说而不做仍可获得一次纠正机会（master「idle 首次可纠正」）。

    回归场景：首轮空响应 → retry_empty（empty_retry_count=1）→ 次轮"我先读取…"
    承诺文本 → 仍应 inject_correction_retry（idle_retry_count 未被空响应消耗）。
    """
    from agent_modules.agent_core.idle_detector import IdleDetector
    d = IdleDetector()
    # 首轮空响应 → retry_empty
    dec1 = d.detect(collected_text='', full_text='',
                    executed_tool_names=[], preset='build')
    assert dec1.action == 'retry_empty'
    assert d.empty_retry_count == 1
    # 次轮承诺文本 → 仍可纠正（idle 计数独立）
    dec2 = d.detect(collected_text='我先读取这个文件', full_text='',
                    executed_tool_names=[], preset='build')
    assert dec2.action == 'inject_correction_retry'
    assert dec2.quality == 'idle'
    assert d.idle_retry_count == 1
    # 三仍承诺 → idle 终态（idle 计数已用尽）
    dec3 = d.detect(collected_text='我先读取文件', full_text='',
                    executed_tool_names=[], preset='build')
    assert dec3.action == 'terminal'
    assert dec3.quality == 'idle'
    # 四仍空响应 → 终态 empty（empty 计数也已用尽）
    dec4 = d.detect(collected_text='', full_text='',
                    executed_tool_names=[], preset='build')
    assert dec4.action == 'terminal'
    assert dec4.quality == 'empty'


def test_idle_detector_plan_write_intent_handoff():
    from agent_modules.agent_core.idle_detector import IdleDetector
    d = IdleDetector()
    dec = d.detect(collected_text='我将修改 src/main.py', full_text='',
                   executed_tool_names=[], preset='plan')
    assert dec.quality == 'constrained'
    assert dec.action == 'handoff'
    assert dec.notice_code == 'plan_ready_for_build'


def test_idle_detector_conclusive_text_success():
    from agent_modules.agent_core.idle_detector import IdleDetector
    d = IdleDetector()
    dec = d.detect(collected_text='结论是这里存在内存泄漏', full_text='',
                   executed_tool_names=[], preset='build')
    assert dec.quality == 'success'
    assert dec.action == 'terminal'


def test_idle_detector_plain_text_idle_soft_warning():
    from agent_modules.agent_core.idle_detector import IdleDetector
    d = IdleDetector()
    dec = d.detect(collected_text='这个问题已经很复杂了', full_text='',
                   executed_tool_names=[], preset='build')
    assert dec.quality == 'idle'
    assert dec.action == 'terminal'  # 软警告，不重试


# ── 阶段 B3：主循环接入 IdleDetector 端到端 ───────────────────


def _run_process(service, monkeypatch, conv, stream_mock, loop=None):
    """统一跑 process_message 收集事件。"""
    _stub_agent_env(service, monkeypatch, conv, stream_mock)
    if loop is None:
        loop = asyncio.get_event_loop()

    async def run():
        events = []
        async for event in service.process_message(conv['id'], 'test'):
            events.append(event)
        return events

    return loop.run_until_complete(run())


def _events_of(events, etype):
    return [json.loads(ev[6:]) for ev in events if json.loads(ev[6:]).get('type') == etype]


def test_text_only_turn_with_intent_detected_as_idle(agent_service, monkeypatch):
    """§8.1: 文本含"我先读取"+无 tool_call → quality=idle + notice(intent_not_executed)。"""
    service = agent_service
    call_count = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # 首轮：承诺文本无工具 → 纠正注入重试；次轮：仍承诺 → idle 终态
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'delta', 'delta': '我先读取这个文件看看'}
        else:
            yield {'type': 'delta', 'delta': '我先读取文件确认'}

    conv = {
        'id': 'conv-idle-intent', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    events = _run_process(service, monkeypatch, conv, mock_stream_llm)

    notices = _events_of(events, 'notice')
    assert any(n.get('code') == 'intent_not_executed' for n in notices)
    done = _events_of(events, 'done')[-1]
    assert done['quality'] == 'idle'


def test_idle_first_retry_then_success(agent_service, monkeypatch):
    """§8.1: 首次 idle 注入纠正后第二轮成功 → quality=success。"""
    service = agent_service
    call_count = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'delta', 'delta': '我先读取这个文件'}
        elif call_count[0] == 1:
            call_count[0] += 1
            # 纠正后第二轮：直接调用工具（read_file）→ 正常执行
            yield {'type': 'tool_call_part', 'tool_call': _make_tool_call(
                'read_file', {'path': '/tmp/test.txt'}, 'call_rec_1')}
        else:
            # 第三轮：mock 耗尽空转（无文本无工具）→ 有历史工具 → success 终态
            return
            yield  # noqa

    conv = {
        'id': 'conv-idle-recover', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    events = _run_process(service, monkeypatch, conv, mock_stream_llm)
    assert any(
        json.loads(ev[6:]).get('code') == 'intent_not_executed'
        for ev in events if json.loads(ev[6:]).get('type') == 'notice'
    )
    done = _events_of(events, 'done')[-1]
    assert done['quality'] == 'success'


def test_plan_mode_write_intent_constrained_handoff(agent_service, monkeypatch):
    """§8.1: plan 模式+文本含写意图 → quality=constrained + phase:handoff + recovery CTA。"""
    service = agent_service

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        yield {'type': 'delta', 'delta': '我将修改 services/auth.py 实现重构'}

    conv = {
        'id': 'conv-plan-intent', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5, 'preset': 'plan'},
        'messages': [],
    }
    events = _run_process(service, monkeypatch, conv, mock_stream_llm)

    phases = _events_of(events, 'phase')
    assert any(p.get('phase') == 'handoff' for p in phases)
    notices = _events_of(events, 'notice')
    assert any(n.get('code') == 'plan_ready_for_build' for n in notices)
    done = _events_of(events, 'done')[-1]
    assert done['quality'] == 'constrained'
    recovery = done.get('recovery') or []
    actions = {r['action'] for r in recovery}
    assert 'switch_preset:build' in actions
    assert 'scroll_to_plan' in actions


def test_done_phase_history_present(agent_service, monkeypatch):
    """B3: done 携带 phase_history（thinking → retrying → done），metadata 同步落库。"""
    service = agent_service
    call_count = [0]
    persisted = []

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'delta', 'delta': '我先读取这个文件'}
        else:
            yield {'type': 'delta', 'delta': '结论是问题已定位'}

    conv = {
        'id': 'conv-phase', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm)

    async def mock_append(conv_id, msg):
        persisted.append(msg)

    monkeypatch.setattr(service, '_append_message', mock_append)

    async def run():
        events = []
        async for event in service.process_message('conv-phase', 'test'):
            events.append(event)
        return events

    events = asyncio.get_event_loop().run_until_complete(run())
    done = _events_of(events, 'done')[-1]
    ph = done.get('phase_history') or []
    assert ph and ph[0] == 'thinking'
    assert ph[-1] == 'done'
    assert 'retrying' in ph
    assert persisted[-1].get('metadata', {}).get('phase_history') == ph


def test_correction_message_not_persisted(agent_service, monkeypatch):
    """B4/B3 防污染：纠正消息仅注入内存，不落库；下轮重建不含。"""
    service = agent_service
    call_count = [0]
    persisted = []

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'delta', 'delta': '我先读取这个文件'}
        else:
            yield {'type': 'delta', 'delta': '结论是问题已定位'}

    conv = {
        'id': 'conv-nocorr', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm)

    async def mock_append(conv_id, msg):
        persisted.append(msg)

    monkeypatch.setattr(service, '_append_message', mock_append)

    async def run():
        events = []
        async for event in service.process_message('conv-nocorr', 'test'):
            events.append(event)
        return events

    asyncio.get_event_loop().run_until_complete(run())
    assert all('系统纠正' not in (m.get('content') or '') for m in persisted)


# ── 阶段 B4：ToolPart 六态发射 ────────────────────────────────


def test_plan_mode_deny_emits_tool_part_denied(agent_service, monkeypatch):
    """§8.1: plan 模式强行调用 write_file(模拟) → tool_part:denied reason=plan_mode_readonly。"""
    service = agent_service
    tc = _make_tool_call('write_file', {'path': '/a/b.py', 'content': 'x'}, 'call_tp_1')
    call_count = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc}
        else:
            yield {'type': 'delta', 'delta': '结论是已完成'}

    conv = {
        'id': 'conv-tp-deny', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5, 'preset': 'plan'},
        'messages': [],
    }
    execute_spy = []
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm, sandbox_execute_spy=execute_spy)

    async def run():
        events = []
        async for event in service.process_message('conv-tp-deny', 'test'):
            events.append(event)
        return events

    events = asyncio.get_event_loop().run_until_complete(run())
    parts = _events_of(events, 'tool_part')
    denied = [p for p in parts if p['part'] == 'denied']
    assert denied, 'plan deny should emit tool_part denied'
    assert denied[0]['reason'] == 'plan_mode_readonly'
    # 生命周期序列：generating → denied（无 running，未执行）
    assert parts[0]['part'] == 'generating'
    assert all(p['part'] != 'running' for p in parts)
    assert execute_spy == []


def test_tool_part_allow_running_success_sequence(agent_service, monkeypatch):
    """B4: allow 路径 generating → running → success 序列。"""
    service = agent_service
    tc = _make_tool_call('read_file', {'path': '/tmp/a.py'}, 'call_tp_2')
    call_count = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc}
        else:
            yield {'type': 'delta', 'delta': '结论是读取完成'}

    conv = {
        'id': 'conv-tp-allow', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    events = _run_process(service, monkeypatch, conv, mock_stream_llm)
    parts = _events_of(events, 'tool_part')
    seq = [p['part'] for p in parts]
    assert seq == ['generating', 'running', 'success']


def test_tool_phase_event_emitted_and_in_phase_history(agent_service, monkeypatch):
    """第三轮修复：工具轮必须发 phase:tool 事件（实时 PhaseStrip），且 phase_history
    同步含 tool（此前事件发射与历史记录两条路径脱节——实时只有 thinking→done，
    历史回退却有 tool，前后端不一致）。"""
    service = agent_service
    tc = _make_tool_call('read_file', {'path': '/tmp/a.py'}, 'call_tp_phase')
    call_count = [0]
    persisted = []

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc}
        else:
            yield {'type': 'delta', 'delta': '结论是读取完成'}

    conv = {
        'id': 'conv-tp-phase', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm)

    async def mock_append(conv_id, msg):
        persisted.append(msg)

    monkeypatch.setattr(service, '_append_message', mock_append)

    async def run():
        events = []
        async for event in service.process_message('conv-tp-phase', 'test'):
            events.append(event)
        return events

    events = asyncio.get_event_loop().run_until_complete(run())
    # 实时：必须出现 phase:tool 事件
    phases = _events_of(events, 'phase')
    assert any(p['phase'] == 'tool' for p in phases), \
        '工具轮必须发射 phase:tool（实时 PhaseStrip 展示）'
    # 历史：done.phase_history 与落库 metadata 均含 tool
    done = _events_of(events, 'done')[-1]
    ph = done.get('phase_history') or []
    assert 'tool' in ph
    assert persisted[-1].get('metadata', {}).get('phase_history') == ph


def test_tool_part_ask_timeout_denied_reason(agent_service, monkeypatch):
    """B4: ask 分支超时 → denied reason=timeout（ToolCard 不卡 permission_pending）。"""
    service = agent_service
    tc = _make_tool_call('write_file', {'path': '/a/b.py', 'content': 'x'}, 'call_tp_3')
    call_count = [0]

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield {'type': 'tool_call_part', 'tool_call': tc}
        else:
            yield {'type': 'delta', 'delta': '结论是未执行'}

    conv = {
        'id': 'conv-tp-ask', 'providerId': 'p', 'modelId': 'm',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
        'messages': [],
    }
    _stub_agent_env(service, monkeypatch, conv, mock_stream_llm)

    async def wait_timeout(request_id):
        return None

    monkeypatch.setattr(service, '_wait_for_confirmation', wait_timeout)
    monkeypatch.setattr(service, 'CONFIRMATION_TIMEOUT', 0.05)

    async def run():
        events = []
        async for event in service.process_message('conv-tp-ask', 'test'):
            events.append(event)
        return events

    events = asyncio.get_event_loop().run_until_complete(run())
    parts = _events_of(events, 'tool_part')
    seq = [p['part'] for p in parts]
    assert 'permission_pending' in seq
    denied = [p for p in parts if p['part'] == 'denied']
    assert denied and denied[0]['reason'] == 'timeout'


# ── 阶段 B5：标注集指标（§8.2） ───────────────────────────────


def test_idle_annotation_set_metrics():
    """§8.2 标注集：召回 ≥90%、精确 ≥90%、误报 ≤10%。

    predicted_idle = quality in ('idle', 'constrained')（说而不做/被约束均为 idle 判定）。
    """
    from agent_modules.agent_core.idle_detector import IdleDetector
    from tests.agent_idle_annotation_set import ANNOTATION_SET

    tp = fp = tn = fn = 0
    for text, preset, expected_idle in ANNOTATION_SET:
        detector = IdleDetector()  # 每样本新建（无跨样本重试污染）
        dec = detector.detect(
            collected_text=text,
            full_text='', executed_tool_names=[], preset=preset,
        )
        predicted_idle = dec.quality in ('idle', 'constrained')
        if predicted_idle and expected_idle:
            tp += 1
        elif predicted_idle and not expected_idle:
            fp += 1
        elif not predicted_idle and not expected_idle:
            tn += 1
        else:
            fn += 1

    assert tp + fn > 0
    recall = tp / (tp + fn)
    precision = tp / (tp + fp) if (tp + fp) else 0
    fpr = fp / (fp + tn) if (fp + tn) else 0
    assert recall >= 0.90, f'recall={recall:.2f} < 0.90 (tp={tp}, fn={fn})'
    assert precision >= 0.90, f'precision={precision:.2f} < 0.90 (tp={tp}, fp={fp})'
    assert fpr <= 0.10, f'fpr={fpr:.2f} > 0.10 (fp={fp}, tn={tn})'


# ── Stage 12 P0 回归测试 ────────────────────────────────────


def _make_p0_mocks(service, monkeypatch, max_iterations=3):
    """P0 测试共用的 mock 基础设施。"""
    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id,
            'providerId': 'test-provider',
            'modelId': 'test-model',
            'agentConfig': {'enabled': True, 'maxIterations': max_iterations},
            'messages': [],
        }

    async def mock_append_message(conv_id, msg):
        pass

    async def mock_inject_batch(messages, conv_id, calls, results):
        # 模拟注入：向 messages 追加 assistant+tool 消息，否则后续迭代看不到工具结果
        tool_calls_block = [{
            'id': tc['requestId'], 'type': 'function',
            'function': {'name': tc['name'], 'arguments': json.dumps(tc['arguments'])},
        } for tc in calls]
        messages.append({'role': 'assistant', 'content': None, 'tool_calls': tool_calls_block})
        for tc, result in zip(calls, results):
            messages.append({
                'role': 'tool', 'tool_call_id': tc['requestId'],
                'name': tc['name'], 'content': json.dumps(result),
            })

    async def mock_build_system_prompt(conv):
        return 'You are a test assistant.'

    class _FakeSandbox:
        def build_openai_tools_spec(self):
            return []

        async def execute(self, name, args):
            return {'success': True, 'content': 'ok'}

    monkeypatch.setattr(service, '_get_conversation', mock_get_conversation)
    monkeypatch.setattr(service, '_append_message', mock_append_message)
    monkeypatch.setattr(service, '_inject_tool_results_batch', mock_inject_batch)
    monkeypatch.setattr(service, '_build_system_prompt', mock_build_system_prompt)
    monkeypatch.setattr(service, '_build_sandbox', lambda conv: _FakeSandbox())
    monkeypatch.setattr(service, '_get_provider', lambda conv: {
        'id': 'test-provider', 'apiBase': 'http://localhost', 'apiKey': 'k',
        'models': [{'id': 'test-model'}],
    })
    monkeypatch.setattr(service, '_read_global_config', lambda: {})


# ── P0-2: 截断判失败 ─────────────────────────────────────────


def test_p02_truncated_tool_calls_are_failed_and_retried(agent_service, monkeypatch):
    """P0-2: finish_reason=='length' + 有工具调用 → 工具不执行，回喂纠正消息重试。
    第二轮正常完成。"""
    from agent_modules.agent_core.idle_detector import IdleDetector, IdleDecision

    service = agent_service
    loop = asyncio.get_event_loop()
    _make_p0_mocks(service, monkeypatch)

    tc = _make_tool_call('read_file', {'path': '/tmp/x'}, 'call_trunc_1')
    call_idx = iter([0, 1])

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        idx = next(call_idx)
        if idx == 0:
            yield {'type': 'tool_call_part', 'tool_call': tc}
            yield {'type': 'finish_reason', 'reason': 'length'}
        else:
            yield {'type': 'delta', 'delta': 'done'}
            yield {'type': 'finish_reason', 'reason': 'stop'}
        yield {'type': 'usage', 'tokens_in': 100, 'tokens_out': 50}

    service._stream_llm = mock_stream_llm
    # 第二轮无工具调用时 IdleDetector 需返回 terminal
    monkeypatch.setattr(IdleDetector, 'detect', lambda self, **kw:
        IdleDecision(action='terminal', quality='success'))

    async def run():
        events = []
        async for event in service.process_message('conv-p02', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    payloads = [json.loads(ev[6:]) for ev in events]

    # 截断的工具应被标记为 failed
    failed_parts = [p for p in payloads if p.get('type') == 'tool_part' and p.get('part') == 'failed']
    assert any(p.get('reason') == 'truncated' for p in failed_parts), \
        'truncated tool calls should be marked failed with reason=truncated'

    # 应有截断 notice
    notices = [p for p in payloads if p.get('type') == 'notice']
    assert any('截断' in n.get('message', '') for n in notices), \
        'should emit truncation notice'

    # 最终 done 事件 quality 应为 success（第二轮正常完成）
    done_events = [p for p in payloads if p.get('type') == 'done']
    assert done_events[-1].get('quality') == 'success'


def test_p02_finish_reason_stop_does_not_trigger_truncation(agent_service, monkeypatch):
    """P0-2: finish_reason=='stop' 不应触发截断逻辑。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    _make_p0_mocks(service, monkeypatch)

    execute_calls = []

    class _TrackingSandbox:
        def build_openai_tools_spec(self):
            return []

        async def execute(self, name, args):
            execute_calls.append(name)
            return {'success': True, 'content': 'ok'}

    monkeypatch.setattr(service, '_build_sandbox', lambda conv: _TrackingSandbox())

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        yield {'type': 'tool_call_part', 'tool_call': _make_tool_call('read_file', {'path': '/a'}, 'call_stop_1')}
        yield {'type': 'finish_reason', 'reason': 'stop'}
        yield {'type': 'usage', 'tokens_in': 100, 'tokens_out': 50}

    service._stream_llm = mock_stream_llm

    async def run():
        events = []
        async for event in service.process_message('conv-p02b', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    # finish_reason=stop 时工具应正常执行
    assert 'read_file' in execute_calls, 'stop finish_reason should not prevent tool execution'


# ── P0-3: 轮次上限标 incomplete ──────────────────────────────


def test_p03_max_iterations_exhausted_marks_incomplete(agent_service, monkeypatch):
    """P0-3: 纯工具轮跑满 max_iterations → quality='incomplete' + notice。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    _make_p0_mocks(service, monkeypatch, max_iterations=2)

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        # 每轮都返回一个工具调用，让循环耗尽
        yield {'type': 'tool_call_part', 'tool_call': _make_tool_call('read_file', {'path': '/tmp/x'}, f'call_iter_{id(messages)}')}
        yield {'type': 'usage', 'tokens_in': 100, 'tokens_out': 50}

    service._stream_llm = mock_stream_llm

    async def run():
        events = []
        async for event in service.process_message('conv-p03', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())
    payloads = [json.loads(ev[6:]) for ev in events]

    done_events = [p for p in payloads if p.get('type') == 'done']
    assert done_events, 'should have a done event'
    assert done_events[-1].get('quality') == 'incomplete', \
        f'expected quality=incomplete, got {done_events[-1].get("quality")}'

    notices = [p for p in payloads if p.get('type') == 'notice']
    assert any(n.get('code') == 'max_iterations_reached' for n in notices), \
        'should emit max_iterations_reached notice'


# ── P0-1: 工具并行执行 ──────────────────────────────────────


def test_p01_parallel_tools_executed_concurrently(agent_service, monkeypatch):
    """P0-1: 多个 parallel allow 工具应并发执行（asyncio.gather）。"""
    from agent_modules.agent_core.idle_detector import IdleDetector, IdleDecision

    service = agent_service
    loop = asyncio.get_event_loop()
    _make_p0_mocks(service, monkeypatch)

    execution_log = []
    call_idx = iter([0, 1])

    class _TrackingSandbox:
        def build_openai_tools_spec(self):
            return []

        async def execute(self, name, args):
            execution_log.append(('start', name, asyncio.get_event_loop().time()))
            await asyncio.sleep(0.05)
            execution_log.append(('end', name, asyncio.get_event_loop().time()))
            return {'success': True, 'content': f'ok:{name}'}

    monkeypatch.setattr(service, '_build_sandbox', lambda conv: _TrackingSandbox())

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        idx = next(call_idx)
        if idx == 0:
            yield {'type': 'tool_call_part', 'tool_call': _make_tool_call('read_file', {'path': '/a'}, 'call_p1')}
            yield {'type': 'tool_call_part', 'tool_call': _make_tool_call('search_code', {'query': 'x'}, 'call_p2')}
        else:
            yield {'type': 'delta', 'delta': 'analysis complete'}
        yield {'type': 'usage', 'tokens_in': 100, 'tokens_out': 50}

    service._stream_llm = mock_stream_llm
    monkeypatch.setattr(IdleDetector, 'detect', lambda self, **kw:
        IdleDecision(action='terminal', quality='success'))

    async def run():
        events = []
        async for event in service.process_message('conv-p01', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())

    # 两个工具都应被执行
    executed_names = {name for _, name, _ in execution_log}
    assert executed_names == {'read_file', 'search_code'}, 'both tools should execute'

    # 并发验证：两个 start 之间的时间差应远小于 0.05s（串行时差 ≈ 0.05s）
    starts = [(name, t) for op, name, t in execution_log if op == 'start']
    starts.sort(key=lambda x: x[1])
    gap = starts[1][1] - starts[0][1]
    assert gap < 0.02, f'parallel tools should start concurrently, gap={gap:.3f}s'

    # done 事件应为 success
    done_events = [json.loads(ev[6:]) for ev in events if json.loads(ev[6:]).get('type') == 'done']
    assert done_events[-1].get('quality') == 'success'


def test_p01_sequential_tools_stay_serial(agent_service, monkeypatch):
    """P0-1: sequential 工具（write_file）仍串行执行。"""
    from agent_modules.agent_core.idle_detector import IdleDetector, IdleDecision
    import services.tool_approval as approval_mod

    service = agent_service
    loop = asyncio.get_event_loop()
    _make_p0_mocks(service, monkeypatch, max_iterations=1)

    execution_log = []

    class _TrackingSandbox:
        def build_openai_tools_spec(self):
            return []

        async def execute(self, name, args):
            execution_log.append(('start', name, asyncio.get_event_loop().time()))
            await asyncio.sleep(0.05)
            execution_log.append(('end', name, asyncio.get_event_loop().time()))
            return {'success': True, 'content': f'ok:{name}'}

    monkeypatch.setattr(service, '_build_sandbox', lambda conv: _TrackingSandbox())
    # write_file/edit_file 需 approval → mock evaluate 为 always allow
    # 必须 patch import 侧（agent_service），不能只 patch 源模块
    monkeypatch.setattr('agent_modules.agent_core.agent_service.evaluate', lambda name, resource, rules: 'allow')

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        yield {'type': 'tool_call_part', 'tool_call': _make_tool_call('write_file', {'path': '/a', 'content': 'x'}, 'call_s1')}
        yield {'type': 'tool_call_part', 'tool_call': _make_tool_call('edit_file', {'path': '/b', 'old_string': 'o', 'new_string': 'n'}, 'call_s2')}
        yield {'type': 'usage', 'tokens_in': 100, 'tokens_out': 50}

    service._stream_llm = mock_stream_llm

    async def run():
        events = []
        async for event in service.process_message('conv-p01b', 'test'):
            events.append(event)
        return events

    events = loop.run_until_complete(run())

    # 串行验证：第二个 start 应在第一个 end 之后
    starts = [(name, t) for op, name, t in execution_log if op == 'start']
    ends = [(name, t) for op, name, t in execution_log if op == 'end']
    assert len(starts) == 2 and len(ends) == 2
    # write_file 先执行（按 LLM 返回顺序）
    assert starts[0][0] == 'write_file'
    assert starts[1][0] == 'edit_file'
    # 第二个 start 应在第一个 end 之后（串行）
    assert starts[1][1] >= ends[0][1], 'sequential tools should not overlap'


# ── S14-P0-2: @ 引用解析与注入 ────────────────────────────────


def _make_project_ref(project_id='proj-1', relpath='src/main.py'):
    return {'projectId': project_id, 'path': relpath}


def test_resolve_references_empty_returns_empty():
    service = AgentService(ToolRegistry.get_instance(), stop_event=asyncio.Event())
    try:
        segments, tokens = service._resolve_references([], 4096)
        assert segments == [] and tokens == 0
    finally:
        service.skill_registry.clear()


def test_resolve_references_virtual_project_rejected(agent_service):
    with pytest.raises(ValueError, match='虚拟项目'):
        agent_service._resolve_references(
            [_make_project_ref('virtual-room1', 'a.py')], 4096,
        )


def test_resolve_references_invalid_shape(agent_service):
    with pytest.raises(ValueError, match='projectId'):
        agent_service._resolve_references([{'path': 'a.py'}], 4096)
    with pytest.raises(ValueError, match='path'):
        agent_service._resolve_references([{'projectId': 'p1'}], 4096)


def test_resolve_references_unknown_project(agent_service, monkeypatch):
    from routes import explorer
    monkeypatch.setattr(explorer, 'read_projects', lambda: [])
    with pytest.raises(ValueError, match='不存在'):
        agent_service._resolve_references(
            [_make_project_ref('missing-1', 'a.py')], 4096,
        )


def test_resolve_references_out_of_whitelist(agent_service, monkeypatch, tmp_path):
    """项目已注册但其路径不在 executor 白名单（未绑定 + 非注册路径）→ 越界拒绝"""
    from routes import explorer
    project = {'id': 'proj-out', 'path': str(tmp_path)}
    monkeypatch.setattr(explorer, 'read_projects', lambda: [project])
    # agent_service 的 executor 白名单是 cwd/~/.ZaoWu，不含 tmp_path → 越界
    with pytest.raises(ValueError, match='范围'):
        agent_service._resolve_references(
            [_make_project_ref('proj-out', 'a.py')], 4096,
        )


def test_resolve_references_archived_project(agent_service, monkeypatch, tmp_path):
    from routes import explorer
    (tmp_path / '.zaowu').write_text(
        json.dumps({'archived': True}), encoding='utf-8',
    )
    project = {'id': 'proj-arc', 'path': str(tmp_path)}
    monkeypatch.setattr(explorer, 'read_projects', lambda: [project])
    # limit_path=tmp_path → 白名单仅该项目；但已归档 → 明确文案
    service = AgentService(
        ToolRegistry.get_instance(), stop_event=asyncio.Event(),
        limit_path=str(tmp_path),
    )
    try:
        with pytest.raises(ValueError, match='归档'):
            service._resolve_references(
                [_make_project_ref('proj-arc', 'a.py')], 4096,
            )
    finally:
        service.skill_registry.clear()


def test_resolve_references_valid_and_same_name_distinguish(
    agent_service, monkeypatch, tmp_path,
):
    """同名项目按 projectId 精确区分；命中白名单的文件内容被读取"""
    from routes import explorer
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'main.py').write_text(
        'print("hello")\n', encoding='utf-8',
    )
    project = {'id': 'proj-1', 'path': str(tmp_path)}
    monkeypatch.setattr(explorer, 'read_projects', lambda: [project])
    service = AgentService(
        ToolRegistry.get_instance(), stop_event=asyncio.Event(),
        limit_path=str(tmp_path),
    )
    try:
        segments, tokens = service._resolve_references(
            [_make_project_ref('proj-1', 'src/main.py')], 4096,
        )
        from services.context_service import estimate_tokens
        assert len(segments) == 1
        assert 'print("hello")' in segments[0]['content']
        assert segments[0]['truncated'] is False
        assert tokens == estimate_tokens(segments[0]['content'])
    finally:
        service.skill_registry.clear()


def test_resolve_references_truncation(agent_service, monkeypatch, tmp_path):
    from routes import explorer
    big = 'x' * 5000
    (tmp_path / 'big.txt').write_text(big, encoding='utf-8')
    project = {'id': 'proj-big', 'path': str(tmp_path)}
    monkeypatch.setattr(explorer, 'read_projects', lambda: [project])
    service = AgentService(
        ToolRegistry.get_instance(), stop_event=asyncio.Event(),
        limit_path=str(tmp_path),
    )
    try:
        # context_budget=100 → 预算 20 = 20 token → 截断
        segments, tokens = service._resolve_references(
            [_make_project_ref('proj-big', 'big.txt')], 100,
        )
        assert len(segments) == 1
        assert segments[0]['truncated'] is True
        from services.context_service import estimate_tokens
        assert estimate_tokens(segments[0]['content']) <= 20
        assert 0 < segments[0]['chars'] < 5000
    finally:
        service.skill_registry.clear()


def test_resolve_references_binary_rejected(agent_service, monkeypatch, tmp_path):
    from routes import explorer
    (tmp_path / 'bin.dat').write_bytes(b'\x00\x01\x02binary')
    project = {'id': 'proj-bin', 'path': str(tmp_path)}
    monkeypatch.setattr(explorer, 'read_projects', lambda: [project])
    service = AgentService(
        ToolRegistry.get_instance(), stop_event=asyncio.Event(),
        limit_path=str(tmp_path),
    )
    try:
        with pytest.raises(ValueError, match='文本'):
            service._resolve_references(
                [_make_project_ref('proj-bin', 'bin.dat')], 4096,
            )
    finally:
        service.skill_registry.clear()


def test_build_messages_injects_ref_before_current_user_message():
    """S14-P0-2: 引用段作为 user 消息注入到当前用户消息之前"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    service = AgentService(ToolRegistry.get_instance(), stop_event=asyncio.Event())
    try:
        conv = {
            'messages': [
                {'role': 'user', 'content': 'early'},
                {'role': 'assistant', 'content': 'ok'},
                {'role': 'user', 'content': '当前消息'},
            ],
        }
        segments = [
            {'display': '@/Proj/src/main.py', 'content': 'CODE', 'truncated': False, 'chars': 4},
        ]
        messages = loop.run_until_complete(
            service._build_messages(conv, '当前消息', ref_segments=segments)
        )
        roles = [m['role'] for m in messages]
        assert roles[-2:] == ['user', 'user']
        assert messages[-2]['content'].startswith('[文件引用]')
        assert 'CODE' in messages[-2]['content']
        assert messages[-1]['content'] == '当前消息'
        # 无引用时不注入
        messages2 = loop.run_until_complete(
            service._build_messages(conv, '当前消息')
        )
        assert len(messages2) == len(messages) - 1
        assert messages2[-1]['content'] == '当前消息'
    finally:
        service.skill_registry.clear()
        loop.close()


def test_insert_ref_segment_reinjects_after_compaction():
    """S14-P0-2: 主动压缩重建消息列表后，引用段重新注入（不丢失引用上下文）。"""
    segments = [
        {'display': '@/Proj/a.py', 'content': 'CODE', 'truncated': False, 'chars': 4},
    ]
    # 模拟 compact_if_needed 返回的结构：[system, 摘要 system, ...recent 含当前 user]
    messages = [
        {'role': 'system', 'content': 'sys'},
        {'role': 'system', 'content': '历史摘要：\n...'},
        {'role': 'user', 'content': '当前消息'},
    ]
    AgentService._insert_ref_segment(messages, segments)
    roles = [m['role'] for m in messages]
    assert roles == ['system', 'system', 'user', 'user']
    assert messages[-2]['content'].startswith('[文件引用]')
    assert messages[-1]['content'] == '当前消息'


def test_telemetry_defaults_register_ref_fields():
    from services.agent_telemetry import _DEFAULTS
    assert 'ref_files_count' in _DEFAULTS
    assert 'ref_tokens' in _DEFAULTS




# ── S15：配置链路与智能体体验（E1/E2/E9）────────────────────

def test_s15_e1_fallback_prefers_conv_new_fields(agent_service, monkeypatch):
    """S15-E-P0-1（E1）：conv 级 contextBudget/maxGenerationTokens 优先于 maxTokens 回退。

    压缩预算（compact_if_needed 第三参）取 conv.contextBudget，生成上限
    （_stream_llm max_tokens）取 conv.maxGenerationTokens，不再落回旧 maxTokens。
    """
    service = agent_service
    loop = asyncio.get_event_loop()

    captured = {'max_tokens': None, 'budget': None}

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        captured['max_tokens'] = kwargs.get('max_tokens')
        yield {'type': 'delta', 'delta': '任务已完成'}

    async def mock_compact(conv, system_prompt, budget, provider, ref_tokens=0):
        captured['budget'] = budget
        return None, None

    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id, 'providerId': 'test-provider', 'modelId': 'test-model',
            'contextBudget': 9000, 'maxGenerationTokens': 5000, 'maxTokens': 4096,
            'agentConfig': {'enabled': True}, 'messages': [],
        }

    async def mock_append(conv_id, msg):
        pass

    class _FakeSandbox:
        def build_openai_tools_spec(self):
            return []

        async def execute(self, name, args):
            return {'success': True, 'content': 'ok'}

    monkeypatch.setattr(service, '_get_conversation', mock_get_conversation)
    monkeypatch.setattr(service, '_append_message', mock_append)
    monkeypatch.setattr(service, '_build_sandbox', lambda conv: _FakeSandbox())
    monkeypatch.setattr(service, '_get_provider', lambda conv: {
        'id': 'test-provider', 'apiBase': 'http://localhost', 'apiKey': 'k',
        'models': [{'id': 'test-model'}],
    })
    monkeypatch.setattr(service._context, 'compact_if_needed', mock_compact)
    monkeypatch.setattr(service, '_stream_llm', mock_stream_llm)

    async def run():
        async for _ in service.process_message('conv-e1', 'test'):
            pass

    loop.run_until_complete(run())
    assert captured['budget'] == 9000, f"got {captured['budget']}"
    assert captured['max_tokens'] == 5000, f"got {captured['max_tokens']}"


def test_s15_e2_auto_approve_allows_run_command_without_ask(agent_service, monkeypatch):
    """S15-E-P0-2（E2）：autoApproveWrites=true 时 run_command 直接 allow，不发确认。"""
    service = agent_service
    loop = asyncio.get_event_loop()
    events = []
    executed = []

    async def mock_stream_llm(provider, messages, tools, **kwargs):
        yield {'type': 'tool_call_part', 'tool_call': {
            'requestId': 'call_rc', 'name': 'run_command',
            'arguments': {'command': 'git status', 'cwd': '/'},
        }}

    async def mock_get_conversation(conv_id):
        return {
            'id': conv_id, 'providerId': 'test-provider', 'modelId': 'test-model',
            'agentConfig': {'enabled': True, 'autoApproveWrites': True, 'maxIterations': 1},
            'messages': [],
        }

    class _FakeSandbox:
        def build_openai_tools_spec(self):
            return []

        async def execute(self, name, args):
            executed.append((name, args))
            return {'success': True, 'content': 'ok'}

    async def mock_append(conv_id, msg):
        pass

    monkeypatch.setattr(service, '_get_conversation', mock_get_conversation)
    monkeypatch.setattr(service, '_append_message', mock_append)
    monkeypatch.setattr(service, '_build_sandbox', lambda conv: _FakeSandbox())
    monkeypatch.setattr(service, '_get_provider', lambda conv: {
        'id': 'test-provider', 'apiBase': 'http://localhost', 'apiKey': 'k',
        'models': [{'id': 'test-model'}],
    })
    monkeypatch.setattr(service, '_stream_llm', mock_stream_llm)

    async def run():
        async for ev in service.process_message('conv-e2', 'run it'):
            events.append(json.loads(ev[6:]))

    loop.run_until_complete(run())
    types = [e.get('type') for e in events]
    assert 'requires_confirmation' not in types, 'run_command 不应卡确认'
    assert executed, 'run_command 应被执行'
    assert executed[0][0] == 'run_command'


def test_s15_e9_tool_text_matcher():
    """S15-E-P0-6（E9）：ToolTextMatcher 命中 XML/JSON/伪函数调用，建议性负则排除。"""
    from agent_modules.agent_core.intent_patterns import ToolTextMatcher
    m = ToolTextMatcher()
    assert m.matches('<function=write_file path="/a">')
    assert m.matches('<tool_call>read_file</tool_call>')
    assert m.matches('<tool name="edit_file">')
    assert m.matches('{"type": "function"}')
    assert m.matches('"tool_calls": [{"function": {...}}]')
    assert m.matches('write_file("/a/b.txt")')
    assert m.matches('git_status()')
    # 建议性负则：整段排除（"你可以调用 X" 是建议不是调用）
    assert not m.matches('你可以调用 write_file(/a) 来写入文件')
    assert not m.matches('我建议你手动执行 git_status()')
    # 正常结论文本不误触发
    assert not m.matches('任务已完成，一切正常')


def test_s15_e9_idle_detector_textified_tool_call_injects_correction():
    """S15-E-P0-6（E9）：文本化工具调用走 inject_correction_retry，一次机会后终态。"""
    from agent_modules.agent_core.idle_detector import IdleDetector
    detector = IdleDetector()
    d = detector.detect(
        collected_text='<function=write_file path="/a">',
        full_text='', executed_tool_names=[], preset='build',
    )
    assert d.action == 'inject_correction_retry'
    assert d.notice_code == 'intent_not_executed'
    assert '文本形式输出' in d.correction
    # 二次文本化 → 终态（一次纠正机会已消耗）
    d2 = detector.detect(
        collected_text='<function=write_file path="/a">',
        full_text='', executed_tool_names=[], preset='build',
    )
    assert d2.action == 'terminal'
    assert d2.quality == 'idle'


def test_s15_e11_build_rules_deny_after_auto_approve(agent_service, monkeypatch):
    """S15-E-P2-2（G14）：persisted deny 追加在 autoApproveWrites 之后 → 显式拒绝不被自动批准覆盖。"""
    from services.tool_approval import ApprovalRule, evaluate
    service = agent_service
    loop = asyncio.get_event_loop()

    async def fake_load(conv_id):
        return [
            ApprovalRule('run_command', 'command:git push*', 'deny'),
            ApprovalRule('run_command', 'command:git status', 'allow'),
        ]

    monkeypatch.setattr(service, '_load_persisted_rules', fake_load)
    rules = loop.run_until_complete(
        service._build_approval_rules('c1', {'autoApproveWrites': True})
    )
    # 自动批准开启时，persisted deny 仍压过 autoApprove allow（D20）
    assert evaluate('run_command', 'command:git push origin main', rules) == 'deny'
    # persisted allow 仍生效
    assert evaluate('run_command', 'command:git status', rules) == 'allow'
    # 未持久化的命令仍被自动批准 allow
    assert evaluate('run_command', 'command:ls', rules) == 'allow'

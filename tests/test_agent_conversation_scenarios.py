"""智能体对话模块 · 模拟用户对话场景测试（场景化验收）。

目标：像真实用户一样与 AgentService 对话，验证智能体核心行为：

- 场景 1：build 模式，用户要求写文件 → 模型调 write_file → 用户批准 → 文件创建
- 场景 2：plan 模式（只读）→ 写工具不可见、强行调用被 deny、系统提示词含只读声明
- 场景 3：plan → build 切换后重新发送 → 写操作恢复
- 场景 4：plan 模式下模型空转（无正文无工具）→ 结束消息明确解释只读约束（P0 验收）
- 场景 5：三态确认 scope=always → 持久化为会话级规则，且不跨会话泄漏（N2-M3）
- 场景 6：拒绝并输入原因 → feedback 回喂模型（CorrectedError 语义）
- 场景 7：Provider 流式 chunk 携带 tool_calls: null → 对话不崩溃（回归防御）

所有 LLM 响应用脚本化 mock 模拟（不真实联网），模式参照
tests/test_agent_integration.py 的隔离环境。
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

# 保证从仓库根 import
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_modules.agent_core.agent_service as agent_module
import server_quart
from services.conversation_store import ConversationStore
from services.tool_registry import ToolRegistry
from agent_modules.agent_core.agent_service import AgentService


# ── 环境 fixture：隔离 store + provider + 项目目录 ────────────

@pytest.fixture
def scenario_env(tmp_path, monkeypatch):
    """构造隔离的对话环境：SQLite store、providers.json、项目目录、干净技能注册表。"""
    project_path = tmp_path / 'project'
    project_path.mkdir()
    (project_path / 'hello.txt').write_text('Hello from ZaoWu!', encoding='utf-8')

    provider_file = tmp_path / 'providers.json'
    monkeypatch.setattr(agent_module, 'PROVIDERS_FILE', str(provider_file))
    provider_file.write_text(json.dumps({
        'providers': [{
            'id': 'test-provider', 'name': 'Test',
            'apiBase': 'http://localhost:9999', 'apiKey': 'test-key',
            'models': [{'id': 'test-model'}],
        }]
    }, ensure_ascii=False), encoding='utf-8')

    store = ConversationStore(str(tmp_path / 'test.db'))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(store.ensure_tables())
    loop.close()

    monkeypatch.setattr(server_quart, 'get_conversation_store', lambda: store)

    def make_service():
        svc = AgentService(
            ToolRegistry.get_instance(),
            project_path=str(project_path),
            limit_path=str(project_path),
            stop_event=asyncio.Event(),
        )
        # 技能改「全部启用即生效」后，测试间清空 registry 防相互污染
        svc.skill_registry.clear()
        svc.CONFIRMATION_TIMEOUT = 3
        return svc

    return SimpleNamespace(
        project_path=project_path, store=store, make_service=make_service,
    )


# ── 脚本化 LLM mock：按轮次返回预定义事件 ─────────────────────

class ScriptedLLM:
    """按调用顺序逐轮 yield 预定义事件；超出轮次后重复最后一轮。

    ``rounds``: List[List[dict]]，每轮是 process_message 一次迭代的 LLM 事件。
    """

    def __init__(self, rounds: List[List[dict]]):
        self._rounds = list(rounds)
        self.calls = 0

    async def __call__(self, provider, messages, tools, **kwargs):
        idx = min(self.calls, len(self._rounds) - 1)
        self.calls += 1
        for ev in self._rounds[idx]:
            yield ev
        yield {'type': 'usage', 'prompt_tokens': 10, 'completion_tokens': 5}


def _tool_call(name: str, path: str, content: str = 'hello', request_id: str = 'call_1'):
    """构造一条 tool_call_part 事件。"""
    return {
        'type': 'tool_call_part',
        'tool_call': {'requestId': request_id, 'name': name,
                      'arguments': {'path': path, 'content': content}},
    }


# ── 对话运行 helper ──────────────────────────────────────────

def _run_dialog(service, conv_id, content, confirm=None):
    """运行一次 process_message，收集全部 SSE 事件与结构化类型。

    ``confirm``: 可选回调 ``(service, request_id) -> bool``，在事件循环内
    收到 ``requires_confirmation`` 时立即调用（模拟用户在确认面板出现时点击，
    避免 run 结束后提交导致 _wait_for_confirmation 超时）。
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    events = []

    async def run():
        async for ev in service.process_message(conv_id, content):
            events.append(ev)
            if confirm is not None:
                p = json.loads(ev[6:])
                if p.get('type') == 'requires_confirmation':
                    # 同步提交（submit_confirmation 是同步方法，直接 set event）
                    ok = confirm(service, p['toolCall']['requestId'])
                    assert ok, 'confirmation should be accepted'

    loop.run_until_complete(run())
    loop.close()
    parsed = [json.loads(ev[6:]) for ev in events]
    return parsed


def _new_conv(env, conv_id='conv-1', preset='build', agent_config=None):
    """创建带 agentConfig（含 preset）的会话，并写入一条用户消息。"""
    cfg = {'enabled': True, 'maxIterations': 5, 'preset': preset}
    if agent_config:
        cfg.update(agent_config)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def create():
        await env.store.create({
            'id': conv_id, 'title': 'Test', 'providerId': 'test-provider',
            'modelId': 'test-model', 'agentConfig': cfg,
            'createdAt': '2024-01-01T00:00:00+00:00',
            'updatedAt': '2024-01-01T00:00:00+00:00',
        })
        await env.store.append_message(conv_id, {
            'id': f'msg-{conv_id}-1', 'role': 'user', 'content': 'init', 'timestamp': 1,
        })

    loop.run_until_complete(create())
    loop.close()


def _confirm(service, request_id, approved=True, scope='once', feedback=None):
    """提交用户确认（同步方法，供事件驱动回调调用）。"""
    return service.submit_confirmation(request_id, approved, scope=scope, feedback=feedback)


# ── 场景 1：build 模式写文件全流程 ───────────────────────────

def test_scenario1_build_mode_write_file(scenario_env):
    """用户要求创建文件 → 模型调 write_file → 用户批准 → 文件落盘。"""
    env = scenario_env
    _new_conv(env, preset='build')
    file_path = str(env.project_path / 'new.txt')
    service = env.make_service()
    # 第一轮只调工具不输出正文 → 无正文有工具 → 摘要收尾；
    # 第二轮无事件（无正文无工具）→ 退出循环
    service._stream_llm = ScriptedLLM([
        [_tool_call('write_file', file_path, 'approved content')],
        [],
    ])

    parsed = _run_dialog(
        service, 'conv-1', 'Create new.txt',
        confirm=lambda s, rid: _confirm(s, rid, approved=True),
    )

    types = [p.get('type') for p in parsed]
    assert 'requires_confirmation' in types, 'write_file 需确认'
    assert (env.project_path / 'new.txt').read_text(encoding='utf-8') == 'approved content'
    # 无正文有工具 → 摘要收尾
    done = parsed[-1]
    assert done['type'] == 'done'
    assert done['content'] == '已执行工具：write_file'


# ── 场景 2：plan 模式只读约束 ────────────────────────────────

def test_scenario2_plan_mode_readonly(scenario_env):
    """plan 模式：写工具不可见、强行调用被 deny、提示词含只读声明。"""
    env = scenario_env
    _new_conv(env, preset='plan')
    file_path = str(env.project_path / 'new.txt')
    service = env.make_service()

    # 1) 工具可见性：build_openai_tools_spec 不含写工具
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    conv = loop.run_until_complete(service._get_conversation('conv-1'))
    sandbox = service._build_sandbox(conv)
    spec_names = {t['function']['name'] for t in sandbox.build_openai_tools_spec()}
    assert 'write_file' not in spec_names
    assert 'edit_file' not in spec_names
    assert 'run_command' not in spec_names
    assert 'read_file' in spec_names

    # 2) 系统提示词含计划模式声明
    prompt = loop.run_until_complete(service._build_system_prompt(conv))
    assert '当前模式：计划模式' in prompt
    loop.close()

    # 3) 强行调用 write_file → 被 deny（不弹确认，直接拒绝）
    service._stream_llm = ScriptedLLM([
        [{'type': 'delta', 'delta': 'planning...'},
         _tool_call('write_file', file_path, 'should not write')],
        [{'type': 'delta', 'delta': '(plan done)'}],
    ])
    parsed = _run_dialog(service, 'conv-1', '创建 tetris.html')

    types = [p.get('type') for p in parsed]
    assert 'requires_confirmation' not in types, 'plan 模式写工具被 deny，不应弹确认'
    ends = [p for p in parsed if p.get('type') == 'tool_call_end']
    assert ends, '应产出 tool_call_end（deny 结果）'
    assert ends[0]['toolResult']['success'] is False
    assert '禁止执行' in ends[0]['toolResult']['error']
    # 文件不应被创建
    assert not (env.project_path / 'new.txt').exists()


# ── 场景 3：plan → build 切换后重发 ──────────────────────────

def test_scenario3_switch_plan_to_build(scenario_env):
    """plan 模式受阻 → 用户切换到 build（改 agentConfig.preset）→ 重发 → 成功执行。"""
    env = scenario_env
    _new_conv(env, preset='plan')
    file_path = str(env.project_path / 'new.txt')
    service = env.make_service()
    # plan 模式下模型空转（无正文无工具）→ 收尾应解释只读；文件不被创建
    service._stream_llm = ScriptedLLM([[]])
    parsed = _run_dialog(service, 'conv-1', '创建 new.txt')
    done = parsed[-1]
    assert '计划模式' in done['content'], 'plan 空转收尾应解释只读（场景4 前置验证）'
    assert not (env.project_path / 'new.txt').exists()

    # 用户切换执行模式：更新 agentConfig.preset（模拟前端 PATCH）
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(env.store.update('conv-1', {'agentConfig': {
        'enabled': True, 'maxIterations': 5, 'preset': 'build',
    }}))
    loop.close()

    # 重发：模型现在调 write_file → 批准 → 成功
    service2 = env.make_service()
    service2._stream_llm = ScriptedLLM([
        [{'type': 'delta', 'delta': 'executing...'},
         _tool_call('write_file', file_path, 'after switch')],
        [{'type': 'delta', 'delta': '(done)'}],
    ])
    parsed2 = _run_dialog(
        service2, 'conv-1', '按计划创建 new.txt',
        confirm=lambda s, rid: _confirm(s, rid, approved=True),
    )
    assert (env.project_path / 'new.txt').read_text(encoding='utf-8') == 'after switch'


# ── 场景 4：plan 模式空转收尾解释（P0 验收）──────────────────

def test_scenario4_plan_empty_turn_explains_readonly(scenario_env):
    """plan 模式下模型既无正文也无工具调用（空转）→ 结束消息明确解释只读约束。"""
    env = scenario_env
    _new_conv(env, preset='plan')
    service = env.make_service()
    # 空转：只 yield usage，无 delta、无 tool_call
    service._stream_llm = ScriptedLLM([[{'type': 'delta', 'delta': ''}]])

    parsed = _run_dialog(service, 'conv-1', '执行')
    done = parsed[-1]
    assert done['type'] == 'done'
    assert '计划模式' in done['content']
    assert '切换到执行模式' in done['content']
    assert done['content'] != '(completed)', 'plan 模式不应再给无信息量的 (completed)'


# ── 场景 5：三态确认 scope=always 会话级持久化（N2-M3）──────

def test_scenario5_always_persists_session_scoped(scenario_env):
    """批准时选"始终允许" → 规则持久化为会话级，且不跨会话泄漏。"""
    env = scenario_env
    _new_conv(env, preset='build', conv_id='conv-A')
    _new_conv(env, preset='build', conv_id='conv-B')
    file_path = str(env.project_path / 'new.txt')
    service = env.make_service()
    service._stream_llm = ScriptedLLM([
        [_tool_call('write_file', file_path, 'content')],
        [{'type': 'delta', 'delta': '(done)'}],
    ])
    parsed = _run_dialog(
        service, 'conv-A', '创建文件',
        confirm=lambda s, rid: _confirm(s, rid, approved=True, scope='always'),
    )

    # 1) 规则已持久化到 tool_approval_rules（会话级，绑定 conv-A）
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    rules = loop.run_until_complete(env.store.list_approval_rules('conv-A'))
    loop.close()
    assert any(
        r['action'] == 'write_file' and r['effect'] == 'allow'
        and r['conversationId'] == 'conv-A' for r in rules
    ), 'always 批准应持久化为会话级 allow 规则'

    # 2) 会话 B 相同操作仍需确认（规则不跨会话）
    service_b = env.make_service()
    service_b._stream_llm = ScriptedLLM([
        [_tool_call('write_file', file_path, 'content B')],
        [{'type': 'delta', 'delta': '(done)'}],
    ])
    parsed_b = _run_dialog(
        service_b, 'conv-B', '创建文件',
        confirm=lambda s, rid: _confirm(s, rid, approved=True),
    )
    types_b = [p.get('type') for p in parsed_b]
    assert 'requires_confirmation' in types_b, '会话 B 不应继承会话 A 的 always 规则'


# ── 场景 6：拒绝并输入原因 → feedback 回喂模型 ──────────────

def test_scenario6_reject_with_feedback_feeds_model(scenario_env):
    """拒绝时输入原因 → tool result error 携带原因（模型下一轮可见）。"""
    env = scenario_env
    _new_conv(env, preset='build')
    file_path = str(env.project_path / 'new.txt')
    service = env.make_service()
    service._stream_llm = ScriptedLLM([
        [_tool_call('write_file', file_path, 'content')],
        [{'type': 'delta', 'delta': '(retry logic)'}],
    ])
    parsed = _run_dialog(
        service, 'conv-1', '创建文件',
        confirm=lambda s, rid: _confirm(s, rid, approved=False, feedback='这个路径不安全'),
    )
    reqs = [p for p in parsed if p.get('type') == 'requires_confirmation']
    assert reqs
    ends = [p for p in parsed if p.get('type') == 'tool_call_end']
    assert ends[0]['toolResult']['success'] is False
    assert ends[0]['toolResult']['error'] == '用户拒绝：这个路径不安全'
    assert not (env.project_path / 'new.txt').exists()


# ── 场景 7：tool_calls: null chunk 不崩溃（回归防御）─────────

def test_scenario7_null_tool_calls_chunk_does_not_crash(scenario_env):
    """Provider 流式 chunk 携带 tool_calls: null / delta: null 时对话不崩溃。"""
    env = scenario_env
    _new_conv(env, preset='build')
    file_path = str(env.project_path / 'new.txt')
    service = env.make_service()

    class NullChunkLLM(ScriptedLLM):
        async def __call__(self, provider, messages, tools, **kwargs):
            # 第一轮：正常正文 + 键存在值为 null 的 tool_calls + delta 整体 null
            for ev in [
                {'type': 'delta', 'delta': 'ok'},
                {'type': 'tool_call_part', 'tool_call': {'requestId': 'x', 'name': 'read_file',
                                                          'arguments': {}}},
                {'type': 'tool_call_part', 'tool_call': None},  # 脏 chunk
            ]:
                yield ev
            yield {'type': 'usage', 'prompt_tokens': 1, 'completion_tokens': 1}

    service._stream_llm = NullChunkLLM([[]])
    parsed = _run_dialog(service, 'conv-1', '读文件')
    # 不应出现 error 事件，流程正常收尾
    assert not any(p.get('type') == 'done' and 'error' in p.get('id', '') for p in parsed)
    assert parsed[-1]['type'] == 'done'
    assert parsed[-1]['done'] is True


# ── 场景 8：build 模式模型空转 → 重试兜底 ────────────────────

def test_scenario8a_build_empty_turn_retries_then_explains(scenario_env):
    """build 模式模型连续空转（无正文无工具）→ 重试一次，仍空则明确提示而非 (completed)。

    复现真实场景：用户切换执行模式后发送确认消息，模型空响应被包装成 (completed)。
    """
    env = scenario_env
    _new_conv(env, preset='build')
    service = env.make_service()
    # 连续两轮空转（仅 usage，无 delta 无 tool_call）
    service._stream_llm = ScriptedLLM([[], []])

    parsed = _run_dialog(service, 'conv-1', '新建 tetris.html，深色霓虹风')

    # 阶段 A5：空转重试提示迁移到 notice 事件（不再混流 delta）
    notices = [p for p in parsed if p.get('type') == 'notice']
    assert any('模型未生成有效响应' in n.get('message', '') for n in notices), '应触发一次空转重试'
    done = parsed[-1]
    assert done['content'] == '模型未生成有效响应，请重试。'
    assert done['content'] != '(completed)', '空响应不应被包装成 (completed)'
    # 阶段 A4：done 携带 quality=empty
    assert done['quality'] == 'empty'


def test_scenario8b_build_empty_turn_retries_then_recovers(scenario_env):
    """build 模式第一轮空转 → 重试后模型正常输出 → 正常收尾（重试可自愈）。"""
    env = scenario_env
    _new_conv(env, preset='build')
    service = env.make_service()
    # 第一轮空转，第二轮正常输出正文
    service._stream_llm = ScriptedLLM([
        [],
        [{'type': 'delta', 'delta': '好的，开始创建 tetris.html'}],
    ])

    parsed = _run_dialog(service, 'conv-1', '新建 tetris.html')

    notices = [p for p in parsed if p.get('type') == 'notice']
    assert any('模型未生成有效响应' in n.get('message', '') for n in notices)
    done = parsed[-1]
    assert '开始创建' in done['content'], '重试后模型正文应作为收尾内容'
    assert done['content'] != '模型未生成有效响应，请重试。'


# ── 场景 9：用户中途停止 → 落库收尾消息 ──────────────────────

def test_scenario9_stop_persists_closing_message(scenario_env):
    """用户点停止 → 落库收尾消息，对话不以 content=NULL 的工具轮消息结尾。

    回归修复：stop/loop/异常中断路径原先不落库最终 assistant 消息，
    前端重载后最后气泡渲染成空气泡（content=null）。
    """
    env = scenario_env
    _new_conv(env, preset='build')
    file_path = str(env.project_path / 'new.txt')
    service = env.make_service()

    class StopLLM(ScriptedLLM):
        async def __call__(self, provider, messages, tools, **kwargs):
            if self.calls == 0:
                yield _tool_call('write_file', file_path, 'content')
            else:
                # 第二轮开始前模拟用户点停止
                service.stop_event.set()
            yield {'type': 'usage', 'prompt_tokens': 1, 'completion_tokens': 1}

    service._stream_llm = StopLLM([[]])
    parsed = _run_dialog(
        service, 'conv-1', '创建文件',
        confirm=lambda s, rid: _confirm(s, rid, approved=True),
    )
    # done 事件为停止语义
    done = parsed[-1]
    assert done['type'] == 'done'
    # 对话最后一条落库消息应为收尾 assistant（content 非 NULL）
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    conv = loop.run_until_complete(env.store.get('conv-1'))
    loop.close()
    last = conv['messages'][-1]
    assert last['role'] == 'assistant'
    assert last.get('content'), '收尾消息 content 不应为 NULL（否则前端渲染空气泡）'


# ── 场景 9：用户中途停止 → 落库收尾消息 ──────────────────────

def test_scenario9_stop_persists_closing_message(scenario_env):
    """用户点停止 → 落库收尾消息，对话不以 content=NULL 的工具轮消息结尾。

    回归修复：stop/loop/异常中断路径原先不落库最终 assistant 消息，
    前端重载后最后气泡渲染成空气泡（content=null）。
    """
    env = scenario_env
    _new_conv(env, preset='build')
    file_path = str(env.project_path / 'new.txt')
    service = env.make_service()

    class StopLLM(ScriptedLLM):
        async def __call__(self, provider, messages, tools, **kwargs):
            if self.calls == 0:
                yield _tool_call('write_file', file_path, 'content')
            else:
                # 第二轮开始前模拟用户点停止
                service.stop_event.set()
            yield {'type': 'usage', 'prompt_tokens': 1, 'completion_tokens': 1}

    service._stream_llm = StopLLM([[]])
    parsed = _run_dialog(
        service, 'conv-1', '创建文件',
        confirm=lambda s, rid: _confirm(s, rid, approved=True),
    )
    # done 事件为停止语义
    done = parsed[-1]
    assert done['type'] == 'done'
    # 对话最后一条落库消息应为收尾 assistant（content 非 NULL）
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    conv = loop.run_until_complete(env.store.get('conv-1'))
    loop.close()
    last = conv['messages'][-1]
    assert last['role'] == 'assistant'
    assert last.get('content'), '收尾消息 content 不应为 NULL（否则前端渲染空气泡）'


# ── 场景 11：空转重试时网络错误 → 落库收尾消息 ───────────────

def test_scenario11_retry_network_error_persists_closing_message(scenario_env):
    """build 模式空转 → 重试时 LLM network error → 落库收尾消息。

    回归修复：except LLMError 分支原先不落库，前端重载后该消息消失，
    对话停留在 content=NULL 的工具轮消息（气泡为空）。
    """
    from agent_modules.agent_core.llm_stream import LLMError
    env = scenario_env
    _new_conv(env, preset='build')
    service = env.make_service()

    class NetworkErrLLM(ScriptedLLM):
        def __init__(self):
            self.calls = 0

        async def __call__(self, provider, messages, tools, **kwargs):
            if self.calls == 0:
                # 第一轮空转 → 触发系统重试
                self.calls += 1
                yield {'type': 'usage', 'prompt_tokens': 1, 'completion_tokens': 1}
            else:
                # 重试时网络错误
                raise LLMError('network', 0, 'connection dropped', retryable=True)

    service._stream_llm = NetworkErrLLM()
    parsed = _run_dialog(service, 'conv-1', '补全文件')

    # 阶段 A5/A3：空转重试提示走 notice；网络错误走结构化 error 事件
    notices = [p for p in parsed if p.get('type') == 'notice']
    assert any('模型未生成有效响应' in n.get('message', '') for n in notices), '应触发空转重试'
    errors = [p for p in parsed if p.get('type') == 'error']
    assert errors, '网络错误应发结构化 error 事件'
    assert errors[0]['code'] == 'internal'
    # 落库收尾消息存在（重载后气泡不空）
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    conv = loop.run_until_complete(env.store.get('conv-1'))
    loop.close()
    last = conv['messages'][-1]
    assert last['role'] == 'assistant'
    assert last.get('content'), '失败收尾消息 content 不应为 NULL'
    assert '请求失败' in last['content'], '收尾消息应含失败原因'

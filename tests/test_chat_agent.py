"""Stage 9: chat/agent 路由层单元测试。

覆盖：
- F01: /messages 端点过滤 tool/tool_calls 消息，避免 OpenAI 400
- F03: /agent-messages 并发防护（409 AGENT_BUSY）
- F07: /agent-messages 校验 agentConfig.enabled（未启用返回 400）
"""
import asyncio
import json

import pytest

pytestmark = pytest.mark.anyio


# ── httpx mock 辅助 ──────────────────────────────────────────

class _FakeHttpxStreamResponse:
    """模拟 httpx 流式响应。"""

    def __init__(self, body: bytes, status_code: int = 200):
        self._body = body
        self.status_code = status_code
        self.encoding = None

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self):
        for line in self._body.split(b'\n'):
            yield line.decode(self.encoding or 'utf-8')


class _FakeHttpxStreamCM:
    def __init__(self, response, captured_payload=None):
        self._response = response
        self._captured_payload = captured_payload

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        return False


class _CapturingHttpxClient:
    """捕获 stream() 调用参数的 httpx.AsyncClient mock。"""

    def __init__(self, response, **kwargs):
        self._response = response
        self.captured_json = None
        self.captured_url = None

    def stream(self, method, url, **kwargs):
        self.captured_json = kwargs.get('json')
        self.captured_url = url
        return _FakeHttpxStreamCM(self._response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _make_sse(content: str) -> bytes:
    payload = {'id': 'upstream-msg', 'choices': [{'delta': {'content': content}}]}
    return f'data: {json.dumps(payload, ensure_ascii=False)}'.encode('utf-8')


@pytest.fixture
async def chat_env(tmp_path, monkeypatch):
    """准备隔离的 SQLite conversation store 与 provider。"""
    from server_quart import app
    import routes.chat as chat
    from services.conversation_store import ConversationStore
    import server_quart

    monkeypatch.setattr(chat, 'PROVIDERS_FILE', str(tmp_path / 'providers.json'))
    monkeypatch.setattr(chat, 'CONFIG_FILE', str(tmp_path / 'chat_config.json'))
    monkeypatch.setattr(chat, 'PRESETS_FILE', str(tmp_path / 'chat_presets.json'))

    chat._write_json(chat.PROVIDERS_FILE, {
        'providers': [{
            'id': 'test-provider',
            'name': 'Test',
            'apiBase': 'http://1.1.1.1:9999',
            'apiKey': 'test-key',
            'models': [{'id': 'test-model'}],
        }]
    })

    store = ConversationStore(str(tmp_path / 'test.db'))
    await store.ensure_tables()
    await store.create({
        'id': 'conv-1',
        'title': 'Test',
        'providerId': 'test-provider',
        'modelId': 'test-model',
        'systemPrompt': '',
        'createdAt': '2024-01-01T00:00:00+00:00',
        'updatedAt': '2024-01-01T00:00:00+00:00',
        'agentConfig': {'enabled': True, 'maxIterations': 5},
    })
    monkeypatch.setattr(server_quart, 'get_conversation_store', lambda: store)
    return app, store


# ── F01: 过滤 tool/tool_calls 消息 ──────────────────────────

async def test_f01_filter_tool_messages_for_chat(chat_env, monkeypatch):
    """F01: /messages 端点应过滤 tool 结果和含 tool_calls 的 assistant 消息。"""
    app, store = chat_env
    import routes.chat as chat

    # 向对话注入 Agent 模式产生的 tool/tool_calls 消息
    await store.append_message('conv-1', {
        'id': 'msg-tool-1', 'role': 'tool',
        'tool_call_id': 'call_1', 'name': 'read_file',
        'content': '{"success": true}', 'timestamp': 1,
    })
    await store.append_message('conv-1', {
        'id': 'msg-asst-tc', 'role': 'assistant',
        'content': None, 'tool_calls': [{'id': 'call_1', 'type': 'function'}],
        'timestamp': 2,
    })

    body = b'\n'.join([_make_sse('ok'), b'data: [DONE]'])
    fake_resp = _FakeHttpxStreamResponse(body)

    captured_client_holder = {}

    def make_client(**kwargs):
        client = _CapturingHttpxClient(fake_resp, **kwargs)
        captured_client_holder['client'] = client
        return client

    monkeypatch.setattr(chat.httpx, 'AsyncClient', make_client)

    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/messages',
            json={'content': 'hi'},
        )
        assert resp.status_code == 200

    # 验证发送给 LLM 的 messages 不含 tool / tool_calls 消息
    captured = captured_client_holder.get('client')
    assert captured is not None, 'httpx.AsyncClient was not called'
    sent_messages = captured.captured_json.get('messages', [])
    roles = [m.get('role') for m in sent_messages]
    assert 'tool' not in roles, 'tool messages should be filtered out'
    assert not any(
        m.get('role') == 'assistant' and m.get('tool_calls')
        for m in sent_messages
    ), 'assistant messages with tool_calls should be filtered out'


# ── F07: agentConfig.enabled 校验 ───────────────────────────

async def test_f07_agent_disabled_returns_400(chat_env):
    """F07: 未启用 Agent 的对话调用 /agent-messages 应返回 400。"""
    app, store = chat_env

    # 创建一个未启用 agent 的对话
    await store.create({
        'id': 'conv-disabled',
        'title': 'No Agent',
        'providerId': 'test-provider',
        'modelId': 'test-model',
        'systemPrompt': '',
        'createdAt': '2024-01-01T00:00:00+00:00',
        'updatedAt': '2024-01-01T00:00:00+00:00',
        'agentConfig': {'enabled': False},
    })

    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-disabled/agent-messages',
            json={'content': 'do something'},
        )
        assert resp.status_code == 400
        data = await resp.get_json()
        assert 'not enabled' in data.get('error', '').lower()


async def test_f07_agent_enabled_passes_guard(chat_env, monkeypatch):
    """F07: 启用 Agent 的对话调用 /agent-messages 不应返回 400（应进入流式响应）。"""
    app, store = chat_env
    import routes.chat as chat

    # conv-1 已在 fixture 中启用 agent
    # Mock AgentService 避免真实 LLM 调用
    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def process_message(self, conv_id, content, files=None):
            yield 'data: {"id":"x","type":"done","done":true,"content":"ok"}\n\n'

        async def close(self):
            pass

    monkeypatch.setattr(chat, 'AgentService', _FakeAgent, raising=False)
    # 同时 patch lazy import 路径
    import agent_modules.agent_core as ac
    monkeypatch.setattr(ac, 'AgentService', _FakeAgent, raising=False)

    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do something'},
        )
        # 不应返回 400；应为 200 流式响应
        assert resp.status_code == 200
        assert 'text/event-stream' in resp.content_type


# ── D3: SSE 编码硬约束（charset=utf-8 + ensure_ascii=False，设计文档 §5 / 硬约束 21-22）──

async def test_agent_sse_response_has_charset_utf8(chat_env, monkeypatch):
    """D3: /agent-messages SSE 响应头必须含 charset=utf-8，且中文直传不转义。"""
    app, store = chat_env
    import routes.chat as chat

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def process_message(self, conv_id, content, files=None):
            # 含中文的 notice 事件：同时验证头 charset 与体中文不转义
            yield 'data: {"id":"system","type":"notice","code":"compacted","message":"已压缩早期对话"}\n\n'
            yield 'data: {"id":"x","type":"done","done":true,"content":"ok","quality":"success"}\n\n'

        async def close(self):
            pass

    monkeypatch.setattr(chat, 'AgentService', _FakeAgent, raising=False)
    import agent_modules.agent_core as ac
    monkeypatch.setattr(ac, 'AgentService', _FakeAgent, raising=False)

    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do something'},
        )
        assert resp.status_code == 200
        # 硬约束：Content-Type 必须带 charset=utf-8（客户端依赖此解码中文）
        assert 'text/event-stream' in resp.content_type
        assert 'charset=utf-8' in resp.content_type
        raw = await resp.get_data()
        text = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
        # 中文直传（ensure_ascii=False）：正文含中文原文，且 \uXXXX 转义序列不出现
        assert '已压缩早期对话' in text
        assert r'\u5df2' not in text  # ensure_ascii=True 时的转义形式


# ── F03: 并发防护（409 AGENT_BUSY） ──────────────────────────

async def test_f03_agent_busy_guard(chat_env, monkeypatch):
    """F03: 同一对话已有活跃 Agent 时，第二次请求应返回 409。"""
    app, store = chat_env
    import routes.chat as chat

    # 模拟已有活跃 Agent 注册（S13-P1-1: 经 store 接口）
    chat.active_agent_store.set('conv-1', object())
    chat.agent_stop_store.set('conv-1', asyncio.Event())

    try:
        async with app.test_client() as client:
            resp = await client.post(
                '/api/chat/conversations/conv-1/agent-messages',
                json={'content': 'second request'},
            )
            assert resp.status_code == 409
            data = await resp.get_json()
            assert data.get('code') == 'AGENT_BUSY'
    finally:
        chat.active_agent_store.pop('conv-1')
        chat.agent_stop_store.pop('conv-1')


# ── 输入类型校验：agentConfig / 字符串字段（防对话崩溃） ──────

@pytest.mark.parametrize('bad_config', ['abc', 123, [1, 2], True])
async def test_patch_rejects_non_dict_agent_config(chat_env, bad_config):
    """非 dict 的 agentConfig 应返回 400，而非 PATCH 自身 .pop AttributeError → 500。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.patch(
            '/api/chat/conversations/conv-1',
            json={'agentConfig': bad_config},
        )
        assert resp.status_code == 400
        data = await resp.get_json()
        assert 'agentConfig' in data.get('error', '')


@pytest.mark.parametrize('bad_value', [None, 123, {'x': 1}, [1, 2]])
async def test_patch_rejects_non_string_title(chat_env, bad_value):
    """非字符串 title（含 null）应返回 400，避免覆盖为 NULL。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.patch(
            '/api/chat/conversations/conv-1',
            json={'title': bad_value},
        )
        assert resp.status_code == 400
        assert 'title' in (await resp.get_json()).get('error', '')


async def test_patch_rejects_non_string_system_prompt(chat_env):
    """非字符串 systemPrompt 应返回 400，避免后续 str 拼接 TypeError。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.patch(
            '/api/chat/conversations/conv-1',
            json={'systemPrompt': {'oops': 1}},
        )
        assert resp.status_code == 400
        assert 'systemPrompt' in (await resp.get_json()).get('error', '')


async def test_patch_rejects_non_string_agent_config_system_prompt(chat_env):
    """agentConfig.systemPrompt 非字符串应返回 400（context_service body += str 会 TypeError）。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.patch(
            '/api/chat/conversations/conv-1',
            json={'agentConfig': {'systemPrompt': 123}},
        )
        assert resp.status_code == 400
        assert 'systemPrompt' in (await resp.get_json()).get('error', '')


async def test_patch_accepts_valid_agent_config(chat_env):
    """合法 dict agentConfig 正常更新，不被误拒。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.patch(
            '/api/chat/conversations/conv-1',
            json={'agentConfig': {'enabled': True, 'maxIterations': 7}},
        )
        assert resp.status_code == 200
        conv = (await resp.get_json()).get('conversation', {})
        assert conv['agentConfig']['maxIterations'] == 7


async def test_patch_accepts_null_agent_config_as_empty(chat_env):
    """agentConfig: null 兼容历史 `or {}` 行为，存为空对象。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.patch(
            '/api/chat/conversations/conv-1',
            json={'agentConfig': None},
        )
        assert resp.status_code == 200
        conv = (await resp.get_json()).get('conversation', {})
        assert conv['agentConfig'] == {}


@pytest.mark.parametrize('bad_config', ['abc', 123, [1, 2]])
async def test_post_rejects_non_dict_agent_config(chat_env, bad_config):
    """POST 创建对话时非 dict agentConfig 也应拒绝（否则存入后 agent_service 崩）。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations',
            json={'agentConfig': bad_config},
        )
        assert resp.status_code == 400
        assert 'agentConfig' in (await resp.get_json()).get('error', '')


async def test_post_rejects_non_string_title(chat_env):
    """POST 创建对话时非字符串 title 应拒绝。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations',
            json={'title': None},
        )
        assert resp.status_code == 400
        assert 'title' in (await resp.get_json()).get('error', '')


# ── maxTokens 链路：POST/PATCH 会话 + /agent-messages 落库 ──────

@pytest.mark.parametrize('bad', [True, 0, 1000001, 'abc', 1.5, None])
async def test_post_conversations_rejects_invalid_max_tokens(chat_env, bad):
    """POST /conversations 非法 maxTokens（bool/越界/非 int）应返回 400。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations',
            json={'maxTokens': bad},
        )
        assert resp.status_code == 400
        assert 'maxTokens' in (await resp.get_json()).get('error', '')


async def test_post_conversations_persists_max_tokens(chat_env):
    """POST /conversations 携带 maxTokens → 响应与 store 均含该值。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations',
            json={'maxTokens': 8192},
        )
        assert resp.status_code == 200
        conv = (await resp.get_json()).get('conversation', {})
        assert conv['maxTokens'] == 8192
        stored = await store.get(conv['id'])
        assert stored['maxTokens'] == 8192


async def test_post_conversations_defaults_max_tokens_to_global(chat_env):
    """POST /conversations 不带 maxTokens → 回退全局 config 值（chat_env 预写）。"""
    app, store = chat_env
    import routes.chat as chat
    chat._write_json(chat.CONFIG_FILE, {
        'defaultProviderId': '', 'defaultModelId': '',
        'temperature': 0.7, 'maxTokens': 6144, 'topP': 1.0,
        'systemPrompt': '',
    })
    async with app.test_client() as client:
        # 注：POST /conversations 空 dict {} 会被 `if not body` 判为 missing body（既有行为），
        # 故带一个无关字段触发正常创建流程
        resp = await client.post('/api/chat/conversations', json={'title': 'x'})
        assert resp.status_code == 200
        conv = (await resp.get_json()).get('conversation', {})
        assert conv['maxTokens'] == 6144


@pytest.mark.parametrize('bad', [True, 0, 1000001, 'abc', 1.5, None])
async def test_patch_conversations_rejects_invalid_max_tokens(chat_env, bad):
    """PATCH /conversations 非法 maxTokens 应返回 400。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.patch(
            '/api/chat/conversations/conv-1',
            json={'maxTokens': bad},
        )
        assert resp.status_code == 400
        assert 'maxTokens' in (await resp.get_json()).get('error', '')


async def test_patch_conversations_persists_max_tokens(chat_env):
    """PATCH /conversations 携带 maxTokens → 200 且持久化。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.patch(
            '/api/chat/conversations/conv-1',
            json={'maxTokens': 1024},
        )
        assert resp.status_code == 200
        conv = (await resp.get_json()).get('conversation', {})
        assert conv['maxTokens'] == 1024
        stored = await store.get('conv-1')
        assert stored['maxTokens'] == 1024


@pytest.mark.parametrize('bad', [True, 1, [], {}])
async def test_patch_conversations_rejects_invalid_project_path(chat_env, bad):
    """S14 (G2): agentConfig.projectPath 非字符串 → 400（写入侧类型校验）。
    null 与 systemPrompt 惯例一致视为"未设置"，由后端 or '' 兜底为多项目白名单。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.patch(
            '/api/chat/conversations/conv-1',
            json={'agentConfig': {'enabled': True, 'projectPath': bad}},
        )
        assert resp.status_code == 400
        assert 'projectPath' in (await resp.get_json()).get('error', '')
        # 会话未被污染
        stored = await store.get('conv-1')
        assert stored['agentConfig'].get('projectPath') is None


async def test_patch_conversations_accepts_string_project_path(chat_env):
    """S14: agentConfig.projectPath 字符串（含 '' 解绑）→ 200 且持久化。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.patch(
            '/api/chat/conversations/conv-1',
            json={'agentConfig': {'enabled': True, 'projectPath': 'D:/x/app'}},
        )
        assert resp.status_code == 200
        stored = await store.get('conv-1')
        assert stored['agentConfig']['projectPath'] == 'D:/x/app'
        # 解绑：空字符串合法
        resp2 = await client.patch(
            '/api/chat/conversations/conv-1',
            json={'agentConfig': {'enabled': True, 'projectPath': ''}},
        )
        assert resp2.status_code == 200
        stored2 = await store.get('conv-1')
        assert stored2['agentConfig']['projectPath'] == ''


@pytest.mark.parametrize('bad', [True, 0, 1000001, 'abc', 1.5, None])
async def test_agent_messages_rejects_invalid_max_tokens(chat_env, monkeypatch, bad):
    """POST /agent-messages 非法 maxTokens 应返回 400（在进入 Agent 前拦截）。"""
    app, store = chat_env
    import routes.chat as chat

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def process_message(self, conv_id, content, files=None):
            yield 'data: {"id":"x","type":"done","done":true,"content":"ok"}\n\n'

        async def close(self):
            pass

    monkeypatch.setattr(chat, 'AgentService', _FakeAgent, raising=False)
    import agent_modules.agent_core as ac
    monkeypatch.setattr(ac, 'AgentService', _FakeAgent, raising=False)

    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do something', 'maxTokens': bad},
        )
        assert resp.status_code == 400
        assert 'maxTokens' in (await resp.get_json()).get('error', '')


async def test_agent_messages_persists_max_tokens(chat_env, monkeypatch):
    """POST /agent-messages 携带 maxTokens → 落库到会话（AgentService 重读时生效）。"""
    app, store = chat_env
    import routes.chat as chat

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def process_message(self, conv_id, content, files=None):
            yield 'data: {"id":"x","type":"done","done":true,"content":"ok"}\n\n'

        async def close(self):
            pass

    monkeypatch.setattr(chat, 'AgentService', _FakeAgent, raising=False)
    import agent_modules.agent_core as ac
    monkeypatch.setattr(ac, 'AgentService', _FakeAgent, raising=False)

    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do something', 'maxTokens': 8192},
        )
        assert resp.status_code == 200
        stored = await store.get('conv-1')
        assert stored['maxTokens'] == 8192


async def test_agent_messages_without_max_tokens_keeps_conv_value(chat_env, monkeypatch):
    """POST /agent-messages 不带 maxTokens → 不覆盖会话既有值。"""
    app, store = chat_env
    import routes.chat as chat
    await store.update('conv-1', {'maxTokens': 2048})

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def process_message(self, conv_id, content, files=None):
            yield 'data: {"id":"x","type":"done","done":true,"content":"ok"}\n\n'

        async def close(self):
            pass

    monkeypatch.setattr(chat, 'AgentService', _FakeAgent, raising=False)
    import agent_modules.agent_core as ac
    monkeypatch.setattr(ac, 'AgentService', _FakeAgent, raising=False)

    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do something'},
        )
        assert resp.status_code == 200
        stored = await store.get('conv-1')
        assert stored['maxTokens'] == 2048


# ── S13-P0-2: maxIterations 链路：/agent-messages 校验 + 落库 ──

@pytest.mark.parametrize('bad', ['abc', True, 0, 101, 1.5, None])
async def test_agent_messages_rejects_invalid_max_iterations(chat_env, bad):
    """POST /agent-messages 非法 maxIterations（非 int/越界/bool）应返回 400。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do something', 'maxIterations': bad},
        )
        assert resp.status_code == 400
        assert 'maxIterations' in (await resp.get_json()).get('error', '')


async def test_agent_messages_persists_max_iterations(chat_env, monkeypatch):
    """POST /agent-messages 携带合法 maxIterations → 200 且落库到 agentConfig。"""
    app, store = chat_env
    import routes.chat as chat

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def process_message(self, conv_id, content, files=None):
            yield 'data: {"id":"x","type":"done","done":true,"content":"ok"}\n\n'

        async def close(self):
            pass

    monkeypatch.setattr(chat, 'AgentService', _FakeAgent, raising=False)
    import agent_modules.agent_core as ac
    monkeypatch.setattr(ac, 'AgentService', _FakeAgent, raising=False)

    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do something', 'maxIterations': 5},
        )
        assert resp.status_code == 200
    stored = await store.get('conv-1')
    assert stored['agentConfig']['maxIterations'] == 5


async def test_agent_messages_without_max_iterations_keeps_conv_value(chat_env, monkeypatch):
    """POST /agent-messages 不带 maxIterations → 不覆盖会话既有值（fixture 为 5）。"""
    app, store = chat_env
    import routes.chat as chat

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def process_message(self, conv_id, content, files=None):
            yield 'data: {"id":"x","type":"done","done":true,"content":"ok"}\n\n'

        async def close(self):
            pass

    monkeypatch.setattr(chat, 'AgentService', _FakeAgent, raising=False)
    import agent_modules.agent_core as ac
    monkeypatch.setattr(ac, 'AgentService', _FakeAgent, raising=False)

    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do something'},
        )
        assert resp.status_code == 200
    stored = await store.get('conv-1')
    assert stored['agentConfig']['maxIterations'] == 5


# ── S14-P0-2: /agent-messages files 引用校验（HTTP 400）──────────

async def test_agent_messages_files_rejects_non_list(chat_env):
    """files 非数组 → 400"""
    app, _ = chat_env
    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do', 'files': {'projectId': 'p1', 'path': 'a.py'}},
        )
        assert resp.status_code == 400
        assert 'array' in (await resp.get_json()).get('error', '')


async def test_agent_messages_files_rejects_invalid_shape(chat_env):
    """files 项缺 projectId/path 或类型错误 → 400"""
    app, _ = chat_env
    async with app.test_client() as client:
        for bad in (
            [{'path': 'a.py'}],
            [{'projectId': 'p1'}],
            [{'projectId': 1, 'path': 'a.py'}],
            [{'projectId': 'p1', 'path': 1}],
            ['not-a-dict'],
            [{'projectId': '', 'path': 'a.py'}],
        ):
            resp = await client.post(
                '/api/chat/conversations/conv-1/agent-messages',
                json={'content': 'do', 'files': bad},
            )
            assert resp.status_code == 400, bad


async def test_agent_messages_files_rejects_virtual_prefix(chat_env):
    """G1: projectId 以 virtual- 开头 → 400（防绕过）"""
    app, _ = chat_env
    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do', 'files': [{'projectId': 'virtual-room1', 'path': 'a.py'}]},
        )
        assert resp.status_code == 400
        assert 'virtual' in (await resp.get_json()).get('error', '')


async def test_agent_messages_files_passes_preflight_and_streams(chat_env, monkeypatch, tmp_path):
    """合法引用 → 预检通过 → 200 流式；process_message 收到 files"""
    app, _ = chat_env
    import routes.chat as chat
    from agent_modules.agent_core.agent_service import AgentService

    # 注册一个临时项目
    import routes.explorer as explorer
    project_path = str(tmp_path / 'proj')
    project_path_dir = tmp_path / 'proj'
    project_path_dir.mkdir()
    (project_path_dir / 'a.py').write_text('print(1)', encoding='utf-8')
    project = {'id': 'proj-valid', 'path': project_path}
    monkeypatch.setattr(explorer, 'read_projects', lambda: [project])
    # 隔离 .zaowu：归档检查读取项目目录 .zaowu，不存在即视为未归档
    monkeypatch.setattr(
        'routes.explorer.PROJECTS_FILE', str(tmp_path / 'projects.json'),
    )

    received = {}

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def _resolve_references(self, files, context_budget=4096):
            # 预检路径：放行（真实解析逻辑已由 agent_service 单测覆盖）
            return [], 0

        async def process_message(self, conv_id, content, files=None):
            received['files'] = files
            yield 'data: {"id":"x","type":"done","done":true,"content":"ok"}\n\n'

        async def close(self):
            pass

    monkeypatch.setattr(chat, 'AgentService', _FakeAgent, raising=False)
    import agent_modules.agent_core as ac
    monkeypatch.setattr(ac, 'AgentService', _FakeAgent, raising=False)

    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do', 'files': [{'projectId': 'proj-valid', 'path': 'a.py'}]},
        )
        assert resp.status_code == 200
        assert received['files'] == [{'projectId': 'proj-valid', 'path': 'a.py'}]


async def test_agent_messages_files_preflight_unknown_project_400(chat_env, monkeypatch):
    """G8: 预检项目不存在 → HTTP 400（进程内 error_v2 为竞态兜底）"""
    app, _ = chat_env
    import routes.chat as chat
    import routes.explorer as explorer
    monkeypatch.setattr(explorer, 'read_projects', lambda: [])

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def _resolve_references(self, files, context_budget=4096):
            raise ValueError('引用的项目不存在或已卸载，无法引用')

        async def process_message(self, conv_id, content, files=None):
            raise AssertionError('should not be called')

        async def close(self):
            pass

    monkeypatch.setattr(chat, 'AgentService', _FakeAgent, raising=False)
    import agent_modules.agent_core as ac
    monkeypatch.setattr(ac, 'AgentService', _FakeAgent, raising=False)

    async with app.test_client() as client:
        resp = await client.post(
            '/api/chat/conversations/conv-1/agent-messages',
            json={'content': 'do', 'files': [{'projectId': 'nope', 'path': 'a.py'}]},
        )
        assert resp.status_code == 400
        assert '不存在' in (await resp.get_json()).get('error', '')


# ── _pick_context_length 字段名兜底 + /config maxTokensAuto ──────

def test_pick_context_length_common_field_names():
    """不同 OpenAI 兼容服务的上下文窗口字段名应都能解析。"""
    import routes.chat as chat
    cases = [
        ({'context_length': 131072}, 131072),
        ({'contextLength': 128000}, 128000),
        ({'context_window': 65536}, 65536),
        ({'max_context_length': 32768}, 32768),
        ({'max_model_len': 8192}, 8192),
        # 字符串 "128K" / "131072" 也应解析
        ({'context_length': '128K'}, 128000),
        ({'context_length': '131072'}, 131072),
    ]
    for model, expected in cases:
        assert chat._pick_context_length(model) == expected


def test_pick_context_length_unknown_or_invalid():
    """未知字段名 / 不可解析值 → None（自动获取优雅降级）。"""
    import routes.chat as chat
    assert chat._pick_context_length({}) is None
    assert chat._pick_context_length({'context_length': 'very-long'}) is None
    assert chat._pick_context_length({'context_length': True}) is None


async def test_config_accepts_max_tokens_auto(chat_env):
    """POST /config 接受 maxTokensAuto 布尔并持久化。"""
    app, store = chat_env
    async with app.test_client() as client:
        resp = await client.post('/api/chat/config', json={'maxTokensAuto': False})
        assert resp.status_code == 200
        cfg = (await resp.get_json()).get('config', {})
        assert cfg['maxTokensAuto'] is False
        # 非法值拒绝
        resp2 = await client.post('/api/chat/config', json={'maxTokensAuto': 'yes'})
        assert resp2.status_code == 400
        assert 'maxTokensAuto' in (await resp2.get_json()).get('error', '')

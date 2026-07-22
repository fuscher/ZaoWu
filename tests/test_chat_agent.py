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
            'apiBase': 'http://localhost:9999',
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

        async def process_message(self, conv_id, content):
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


# ── F03: 并发防护（409 AGENT_BUSY） ──────────────────────────

async def test_f03_agent_busy_guard(chat_env, monkeypatch):
    """F03: 同一对话已有活跃 Agent 时，第二次请求应返回 409。"""
    app, store = chat_env
    import routes.chat as chat

    # 模拟已有活跃 Agent 注册
    chat.active_agents['conv-1'] = object()
    chat.agent_stop_events['conv-1'] = asyncio.Event()

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
        chat.active_agents.pop('conv-1', None)
        chat.agent_stop_events.pop('conv-1', None)

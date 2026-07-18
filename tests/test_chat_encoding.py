"""
对话模块中文乱码回归测试。

验证当上游 LLM Provider 返回 text/event-stream 但未声明 charset 时，
routes/chat.py 仍能正确以 UTF-8 解码中文内容，且 SSE 响应本身也声明 UTF-8。
"""
import json

import pytest

pytestmark = pytest.mark.anyio


class _FakeResponse:
    """模拟 requests 流式响应：Content-Type 中无 charset。"""

    status_code = 200
    headers = {'Content-Type': 'text/event-stream'}
    encoding = None

    def __init__(self, body: bytes):
        self._body = body

    def iter_lines(self, decode_unicode=False, chunk_size=1):
        for line in self._body.split(b'\n'):
            if decode_unicode:
                yield line.decode(self.encoding or 'utf-8')
            else:
                yield line

    @property
    def text(self):
        return self._body.decode('utf-8')


def _make_sse(content: str) -> bytes:
    """构造符合 OpenAI 流式格式的 SSE 数据行。"""
    payload = {'id': 'upstream-msg', 'choices': [{'delta': {'content': content}}]}
    return f'data: {json.dumps(payload, ensure_ascii=False)}'.encode('utf-8')


@pytest.fixture
def chat_env(tmp_path, monkeypatch):
    """准备隔离的 chat 数据文件与 provider/conversation。"""
    from server_quart import app
    import routes.chat as chat

    monkeypatch.setattr(chat, 'CONVERSATIONS_FILE', str(tmp_path / 'conversations.json'))
    monkeypatch.setattr(chat, 'PROVIDERS_FILE', str(tmp_path / 'providers.json'))
    monkeypatch.setattr(chat, 'CONFIG_FILE', str(tmp_path / 'chat_config.json'))
    monkeypatch.setattr(chat, 'PRESETS_FILE', str(tmp_path / 'chat_presets.json'))

    chat._write_json(
        chat.PROVIDERS_FILE,
        {
            'providers': [{
                'id': 'test-provider',
                'name': 'Test',
                'apiBase': 'http://localhost:9999',
                'apiKey': 'test-key',
                'models': [{'id': 'test-model'}],
            }]
        },
    )
    chat._write_json(
        chat.CONVERSATIONS_FILE,
        {
            'conversations': [{
                'id': 'conv-1',
                'title': 'Test',
                'providerId': 'test-provider',
                'modelId': 'test-model',
                'systemPrompt': '',
                'messages': [],
                'createdAt': '2024-01-01T00:00:00+00:00',
                'updatedAt': '2024-01-01T00:00:00+00:00',
            }]
        },
    )
    return app, chat


async def test_send_message_sse_decodes_chinese_utf8(chat_env, tmp_path, monkeypatch):
    app, chat = chat_env

    body = b'\n'.join([
        _make_sse('中'),
        _make_sse('文'),
        b'data: [DONE]',
    ])
    fake_resp = _FakeResponse(body)
    monkeypatch.setattr(chat.requests, 'post', lambda *args, **kwargs: fake_resp)

    async with app.test_client() as client:
        resp = await client.post('/api/chat/conversations/conv-1/messages', json={'content': 'hi'})
        assert resp.status_code == 200
        assert 'text/event-stream' in resp.content_type
        assert 'utf-8' in resp.content_type

        raw = await resp.get_data()
        if isinstance(raw, str):
            text = raw
        else:
            text = raw.decode('utf-8')
        assert '中文' in text
        # 确认没有使用 ensure_ascii=True 把中文转义成 \uXXXX
        assert r'\u4e2d' not in text

    # 持久化的 assistant 消息也必须是正确的中文
    data = json.loads((tmp_path / 'conversations.json').read_text(encoding='utf-8'))
    assistant_msgs = [m for m in data['conversations'][0]['messages'] if m['role'] == 'assistant']
    assert assistant_msgs
    assert assistant_msgs[-1]['content'] == '中文'

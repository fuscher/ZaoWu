"""4.1 Provider 错误分类 + 建连前重试 单元测试。

验收点：
- 429（首字节前）→ 3 次内重试成功，用户无感
- 500（首字节前）→ 重试耗尽后抛 LLMError(kind='server_error')
- 流式开始后断流 → 不重试，直接抛 LLMError（避免重复正文）
- 400 token 超限 → context_overflow（不重试）
- 401/403 → auth（不重试）
- 网络错误（建连前）→ 重试
- 日志中 apiKey 脱敏
"""
import json

import httpx
import pytest

pytestmark = pytest.mark.anyio

from agent_modules.agent_core import llm_stream as ls
from agent_modules.agent_core.llm_stream import LLMError, llm_stream


# ── httpx mock 辅助 ──────────────────────────────────────────

class _FakeResponse:
    """模拟 httpx 流式响应。"""

    def __init__(self, status_code=200, body=b'', sse_lines=None,
                 headers=None, aiter_error=None):
        self.status_code = status_code
        self._body = body
        self._sse_lines = sse_lines or []
        self.encoding = 'utf-8'
        self.headers = headers or {}
        # 若设置，aiter_lines 在产出若干行后抛该异常（模拟流中断流）
        self._aiter_error = aiter_error

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        for i, line in enumerate(self._sse_lines):
            yield line
        if self._aiter_error is not None:
            raise self._aiter_error


class _FakeStreamCM:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        return False


class _ScriptedClient:
    """脚本化 httpx.AsyncClient mock：按顺序执行预设动作。

    每个动作是一个 _FakeResponse（返回响应）或 Exception 实例（stream() 直接抛）。
    断言 stream() 调用次数符合预期。
    """

    def __init__(self, actions):
        self._actions = list(actions)
        self.call_count = 0

    def stream(self, method, url, **kwargs):
        self.call_count += 1
        if self.call_count > len(self._actions):
            raise AssertionError(f'unexpected stream call #{self.call_count}')
        action = self._actions[self.call_count - 1]
        if isinstance(action, BaseException):
            raise action
        return _FakeStreamCM(action)

    async def aclose(self):
        pass


def _sse(content: str) -> str:
    return f'data: {json.dumps({"choices": [{"delta": {"content": content}}]}, ensure_ascii=False)}'


def _sse_done() -> str:
    return 'data: [DONE]'


def _sse_usage() -> str:
    return f'data: {json.dumps({"usage": {"prompt_tokens": 10, "completion_tokens": 5}})}'


def _ok_response(content: str = 'hello'):
    """200 成功响应：一条 delta + usage + DONE。"""
    return _FakeResponse(status_code=200, sse_lines=[_sse(content), _sse_usage(), _sse_done()])


_PROVIDER = {'apiBase': 'http://test.local', 'apiKey': 'sk-secret-1234567890'}


@pytest.fixture
def fast_backoffs(monkeypatch):
    """把退避改为 0，避免测试真的 sleep。"""
    monkeypatch.setattr(ls, '_RETRY_BACKOFFS', [0.0, 0.0, 0.0])


async def _consume(gen):
    """收尽 llm_stream 产出的事件，返回 (deltas, usage, error)。"""
    deltas = []
    usage = None
    err = None
    try:
        async for event in gen:
            if event['type'] == 'delta':
                deltas.append(event['delta'])
            elif event['type'] == 'usage':
                usage = event
    except LLMError as e:
        err = e
    return deltas, usage, err


# ── 纯函数：错误归类 / 脱敏 ──────────────────────────────────

def test_classify_429_rate_limit_with_retry_after():
    err = ls._classify_http_error(429, b'rate limited', httpx.Headers({'retry-after': '5'}))
    assert err.kind == 'rate_limit'
    assert err.retryable is True
    assert err.retry_after == 5.0


def test_classify_500_server_error_retryable():
    err = ls._classify_http_error(503, b'unavailable', httpx.Headers({}))
    assert err.kind == 'server_error'
    assert err.retryable is True
    assert err.retry_after is None


def test_classify_400_context_overflow():
    body = b'{"error": "maximum context length exceeded"}'
    err = ls._classify_http_error(400, body, httpx.Headers({}))
    assert err.kind == 'context_overflow'
    assert err.retryable is False


def test_classify_400_generic_not_overflow():
    err = ls._classify_http_error(400, b'bad request: invalid model', httpx.Headers({}))
    assert err.kind == 'unknown'
    assert err.retryable is False


def test_classify_401_auth():
    err = ls._classify_http_error(401, b'unauthorized', httpx.Headers({}))
    assert err.kind == 'auth'
    assert err.retryable is False


def test_classify_408_timeout():
    """408 Request Timeout → kind='timeout'（对齐 timeout 恢复 CTA）。"""
    err = ls._classify_http_error(408, b'timeout', httpx.Headers({}))
    assert err.kind == 'timeout'
    assert err.retryable is True


def test_parse_retry_after_invalid():
    assert ls._parse_retry_after(None) is None
    assert ls._parse_retry_after('not-a-number') is None
    assert ls._parse_retry_after('2.5') == 2.5


def test_mask_key_redacts_middle():
    assert ls._mask_key('sk-secret-1234567890') == 'sk-****7890'
    assert ls._mask_key('short') == '****'
    assert ls._mask_key('') == '(empty)'


def test_backoff_delay_retry_after_takes_precedence():
    err = LLMError('rate_limit', 429, 'x', retryable=True, retry_after=8.0)
    # max(base=1.0, retry_after=8.0) = 8.0
    assert ls._backoff_delay(err, 0) == 8.0


def test_backoff_delay_uses_backoff_table():
    err = LLMError('server_error', 500, 'x', retryable=True)
    assert ls._backoff_delay(err, 0) == 1.0
    assert ls._backoff_delay(err, 1) == 2.0
    assert ls._backoff_delay(err, 2) == 4.0
    # 越界回退到末位
    assert ls._backoff_delay(err, 5) == 4.0


def test_llm_error_inherits_runtime_error():
    """I3：必须继承 RuntimeError，否则 agent_service 的 except RuntimeError 接不住。"""
    err = LLMError('network', 0, 'x', retryable=False)
    assert isinstance(err, RuntimeError)


# ── 重试环路 ────────────────────────────────────────────────

async def test_429_retries_then_succeeds(fast_backoffs):
    """429（首字节前）→ 重试 → 200，用户无感。"""
    client = _ScriptedClient([
        _FakeResponse(429, b'rate limited', headers={}),
        _ok_response('hi'),
    ])
    deltas, usage, err = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[],
        http_client=client,
    ))
    assert err is None
    assert deltas == ['hi']
    assert client.call_count == 2
    assert usage is not None


async def test_500_retries_exhausted_raises_server_error(fast_backoffs):
    """500（首字节前）→ 重试 3 次后抛 LLMError(kind='server_error')。

    attempt 0..3 共 4 次请求，3 次重试。
    """
    client = _ScriptedClient([_FakeResponse(500, b'err')] * 4)
    deltas, usage, err = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[],
        http_client=client,
    ))
    assert err is not None
    assert err.kind == 'server_error'
    assert err.retryable is True
    assert client.call_count == 4
    assert deltas == []


async def test_no_retry_after_stream_started(fast_backoffs):
    """流式开始后断流 → 不重试，直接抛 LLMError(kind='network')。

    验证 I2：一旦 yield 过 delta，后续错误不再重试（避免重复正文）。
    """
    mid_stream_err = httpx.ReadError('connection dropped mid-stream')
    resp = _FakeResponse(
        status_code=200,
        sse_lines=[_sse('partial')],  # 先产出一条 delta → yielded=True
        aiter_error=mid_stream_err,    # 然后断流
    )
    client = _ScriptedClient([resp])
    deltas, usage, err = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[],
        http_client=client,
    ))
    assert err is not None
    assert err.kind == 'network'
    # 只调用一次：流式已开始，不再重试
    assert client.call_count == 1
    # 用户已收到已产出的部分正文
    assert deltas == ['partial']


async def test_connect_error_kind_subdivided(fast_backoffs):
    """建连前 ConnectError → LLMError(kind='connect_error')（重试耗尽后）。

    回归：RequestError 统一 network 曾吞掉 ConnectError，导致 classify 走 internal
    兜底、连接失败语义丢失。修复后按 isinstance 细分 kind。
    """
    client = _ScriptedClient([httpx.ConnectError('refused')] * 4)
    deltas, usage, err = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[],
        http_client=client,
    ))
    assert err is not None
    assert err.kind == 'connect_error'
    assert client.call_count == 4  # 3 次重试后仍失败
    assert deltas == []


async def test_timeout_exception_kind_subdivided(fast_backoffs):
    """建连前 TimeoutException → LLMError(kind='timeout')（重试耗尽后）。

    回归：真实超时曾落入 network → internal 兜底，错误卡片显示"智能体运行异常"
    而非"请求超时"。修复后细分 kind='timeout' → classify 映射 code=timeout。
    """
    client = _ScriptedClient([httpx.TimeoutException('timed out')] * 4)
    deltas, usage, err = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[],
        http_client=client,
    ))
    assert err is not None
    assert err.kind == 'timeout'
    assert client.call_count == 4
    assert deltas == []


async def test_400_context_overflow_not_retried(fast_backoffs):
    """400 token 超限 → context_overflow，不可重试，仅调用一次。"""
    body = b'{"error": "context length exceeded"}'
    client = _ScriptedClient([_FakeResponse(400, body)])
    deltas, usage, err = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[],
        http_client=client,
    ))
    assert err is not None
    assert err.kind == 'context_overflow'
    assert err.retryable is False
    assert client.call_count == 1


async def test_401_auth_not_retried(fast_backoffs):
    """401 → auth，不可重试。"""
    client = _ScriptedClient([_FakeResponse(401, b'unauthorized')])
    deltas, usage, err = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[],
        http_client=client,
    ))
    assert err is not None
    assert err.kind == 'auth'
    assert client.call_count == 1


async def test_network_error_before_stream_retries(fast_backoffs):
    """建连前网络错误 → 重试 → 成功。"""
    client = _ScriptedClient([
        httpx.ConnectError('connection refused'),
        _ok_response('recovered'),
    ])
    deltas, usage, err = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[],
        http_client=client,
    ))
    assert err is None
    assert deltas == ['recovered']
    assert client.call_count == 2


async def test_network_error_exhausted_raises(fast_backoffs):
    """建连前网络错误 → 重试耗尽 → 抛 LLMError(kind='network')。

    ReadError 不是 Timeout/ConnectError 子类 → 保持 network kind。
    （ConnectError 细分见 test_connect_error_kind_subdivided）
    """
    client = _ScriptedClient([httpx.ReadError('connection dropped')] * 4)
    deltas, usage, err = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[],
        http_client=client,
    ))
    assert err is not None
    assert err.kind == 'network'
    assert client.call_count == 4


async def test_api_key_masked_in_logs(fast_backoffs, caplog):
    """失败日志中 apiKey 必须脱敏，明文不得出现。"""
    import logging
    caplog.set_level(logging.WARNING, logger='agent_modules.agent_core.llm_stream')
    client = _ScriptedClient([_FakeResponse(500, b'err')] * 4)
    _, _, _ = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[],
        http_client=client,
    ))
    log_text = caplog.text
    assert 'sk-secret-1234567890' not in log_text, '明文 apiKey 泄漏到日志'
    assert 'sk-****7890' in log_text, '脱敏形式应出现在日志'


async def test_stop_event_breaks_before_request(fast_backoffs):
    """stop_event 在请求前已置位 → 直接退出，不发请求。"""
    import asyncio
    stop = asyncio.Event()
    stop.set()
    client = _ScriptedClient([_ok_response()])
    deltas, usage, err = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[],
        stop_event=stop, http_client=client,
    ))
    assert err is None
    assert client.call_count == 0


# ── 回归：Provider 异常 chunk 防御（tool_calls: null / delta: null） ──

async def test_null_delta_and_tool_calls_do_not_crash(fast_backoffs):
    """Provider 流式 chunk 携带 null 值时不崩溃（回归修复）。

    旧代码 `if 'tool_calls' in delta: for tc in delta['tool_calls']`——
    delta 键存在但值为 null 时 for tc in None 抛
    'NoneType' object is not iterable，整轮对话中断（前端显示 error）。
    覆盖四个同族坑：tool_calls 为 null / delta 整体为 null /
    tool_calls 数组含 null 元素 / 正常 tool_call 仍可累积。
    """
    chunk = lambda d: f'data: {json.dumps({"choices": [{"delta": d}]})}'
    resp = _FakeResponse(status_code=200, sse_lines=[
        chunk({'content': 'ok'}),
        chunk({'content': None, 'tool_calls': None}),       # 键存在值为 null（回归主因）
        chunk(None),                                        # delta 整体为 null
        chunk({'tool_calls': [None]}),                      # 数组含 null 元素
        chunk({'tool_calls': [{'index': 0, 'id': 'call_1',
                               'function': {'name': 'f', 'arguments': '{}'}}]}),
        _sse_usage(),
        _sse_done(),
    ])
    client = _ScriptedClient([resp])
    deltas, usage, err = await _consume(llm_stream(
        provider=_PROVIDER, model_id='m', messages=[], http_client=client,
    ))
    assert err is None
    assert deltas == ['ok']   # 正常正文不受影响
    assert usage is not None  # 后续 chunk 正常消费
    assert client.call_count == 1


# ── apiBase 协议校验：工作流路径绕过路由层 validate_api_base 的兜底 ──

@pytest.mark.parametrize('api_base', ['', '   ', '/relative/path', 'ftp://x', 'not-a-url'])
async def test_invalid_api_base_raises_without_retry(fast_backoffs, api_base):
    """空/相对/非 http(s) apiBase 直接抛不可重试 LLMError，不进入重试循环。

    工作流路径（llm_node）直连 llm_stream，绕过路由层 validate_api_base。
    旧逻辑：httpx.RequestError → 建连前 3 次指数退避重试（~7s 白等）才报错。
    """
    client = _ScriptedClient([_ok_response()])
    provider = {'apiBase': api_base, 'apiKey': 'sk-secret-1234567890'}
    deltas, usage, err = await _consume(llm_stream(
        provider=provider, model_id='m', messages=[], http_client=client,
    ))
    assert err is not None
    assert err.kind == 'unknown'
    assert err.retryable is False
    # 关键：从未发起请求，没有浪费重试
    assert client.call_count == 0
    assert deltas == []


async def test_valid_http_api_base_passes_check(fast_backoffs):
    """合法 http:// apiBase 通过协议校验，正常发起请求。"""
    client = _ScriptedClient([_ok_response('hi')])
    provider = {'apiBase': 'http://valid.local', 'apiKey': 'sk-secret-1234567890'}
    deltas, usage, err = await _consume(llm_stream(
        provider=provider, model_id='m', messages=[], http_client=client,
    ))
    assert err is None
    assert deltas == ['hi']
    assert client.call_count == 1


async def test_null_function_name_and_arguments_do_not_crash(fast_backoffs):
    """tool_calls 分片里 function.name/arguments 为 null（或 function 整体 null）不崩溃。

    回归修复：llm_stream 累积 name/arguments 时 str += None 抛 TypeError——
    部分 Provider（DeepSeek/自定义源）分片 chunk 的 function 携带空值。
    """
    chunk = lambda d: f'data: {json.dumps({"choices": [{"delta": d}]})}'
    resp = _FakeResponse(status_code=200, sse_lines=[
        chunk({'tool_calls': [{'index': 0, 'id': 'call_1',
                               'function': {'name': None, 'arguments': None}}]}),
        chunk({'tool_calls': [{'index': 0, 'function': None}]}),
        chunk({'tool_calls': [{'index': 0,
                               'function': {'name': 'write_file', 'arguments': '{"path":'}}]}),
        chunk({'tool_calls': [{'index': 0, 'function': {'arguments': '"x"}'}}]}),
        _sse_usage(),
        _sse_done(),
    ])
    client = _ScriptedClient([resp])
    events = []
    err = None
    try:
        async for event in llm_stream(
            provider=_PROVIDER, model_id='m', messages=[], http_client=client,
        ):
            events.append(event)
    except LLMError as e:
        err = e
    assert err is None
    # 空值 chunk 被跳过，正常分片累积出完整工具调用
    tool_parts = [ev for ev in events if ev['type'] == 'tool_call_part']
    assert len(tool_parts) == 1
    tc = tool_parts[0]['tool_call']
    assert tc['name'] == 'write_file'
    assert tc['arguments'] == {'path': 'x'}

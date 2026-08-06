from __future__ import annotations

import asyncio
import json
import logging
import httpx
from typing import AsyncGenerator, Dict, List, Any, Optional

logger = logging.getLogger('agent_modules.agent_core.llm_stream')


class LLMError(RuntimeError):
    """LLM 调用错误，按 kind 分类。

    继承 RuntimeError：agent_service._stream_llm 的 `except RuntimeError`
    （agent_service.py:638）能接住，保持与原 raise RuntimeError 行为兼容。

    kind 取值：rate_limit | server_error | context_overflow | auth | network | unknown
    retryable=True 的错误在 llm_stream 内部建连前短重试（默认 3 次，上限 4s）；
    流式开始后（已向调用方 yield 过 delta）一律不重试，避免重复正文。
    """

    def __init__(self, kind: str, status: int, message: str,
                 retryable: bool, retry_after: Optional[float] = None):
        self.kind = kind
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after
        super().__init__(message)


# ── 错误归类 ──────────────────────────────────────────────────

_OVERFLOW_HINTS = ('context_length', 'context length', 'maximum context',
                   'too long', 'token limit', 'reduce the length')


def _classify_http_error(status: int, body: bytes, headers: httpx.Headers) -> LLMError:
    """把非 200 响应归类为 LLMError。"""
    text = body.decode(errors='replace')[:500]
    hint = f'HTTP {status}: {text[:200]}'

    if status == 429:
        retry_after = _parse_retry_after(headers.get('retry-after'))
        return LLMError('rate_limit', status, hint, retryable=True, retry_after=retry_after)
    if status in (500, 502, 503, 504):
        return LLMError('server_error', status, hint, retryable=True)
    if status in (401, 403):
        return LLMError('auth', status, hint, retryable=False)
    if status == 400:
        low = text.lower()
        if any(h in low for h in _OVERFLOW_HINTS):
            return LLMError('context_overflow', status, hint, retryable=False)
        return LLMError('unknown', status, hint, retryable=False)
    return LLMError('unknown', status, hint, retryable=False)


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mask_key(key: str) -> str:
    """apiKey 脱敏：仅保留末尾 4 位，避免密钥进日志。"""
    if not key:
        return '(empty)'
    if len(key) <= 8:
        return '****'
    return f'{key[:3]}****{key[-4:]}'


# 重试退避（秒）：建连前短重试，上限 4s
_RETRY_BACKOFFS = [1.0, 2.0, 4.0]
_MAX_RETRIES = len(_RETRY_BACKOFFS)


def _backoff_delay(err: Optional[LLMError], attempt: int) -> float:
    """第 attempt 次重试的退避秒数（attempt 从 0 起）。retry-after 优先。"""
    base = _RETRY_BACKOFFS[min(attempt, len(_RETRY_BACKOFFS) - 1)]
    if err is not None and err.retry_after is not None:
        return max(base, err.retry_after)
    return base


async def llm_stream(
    provider: dict,
    model_id: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    top_p: float = 1.0,
    tool_choice: str | None = None,
    stop_event=None,
    http_client: httpx.AsyncClient | None = None,
) -> AsyncGenerator[dict, None]:
    """工作流与 Agent 共享的 LLM 流式调用函数。

    错误处理：建连/首字节前的 429/5xx/网络错误按指数退避短重试；
    一旦向调用方 yield 过任何事件（流式已开始），后续错误不再重试（避免重复正文），
    直接抛 LLMError。context_overflow/auth 等不可重试错误立即抛出。
    """
    api_base = provider.get('apiBase', '').rstrip('/')
    api_key = provider.get('apiKey', '')

    # 协议校验：工作流路径（llm_node）直连 llm_stream，绕过路由层 validate_api_base。
    # 空/相对 apiBase 会触发 httpx.RequestError → 建连前 3 次指数退避重试（~7s 白等）
    # 才报错。此处前置校验，非法直接抛不可重试错误，不进入重试循环（与 agent 路径行为一致）。
    if not api_base or not api_base.startswith(('http://', 'https://')):
        raise LLMError(
            'unknown', 0,
            f'apiBase must start with http:// or https:// (got: {api_base!r})',
            retryable=False,
        )

    payload = {
        'model': model_id,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
        'top_p': top_p,
        'stream': True,
        'stream_options': {'include_usage': True},
    }
    if tools:
        payload['tools'] = tools
    if tool_choice:
        payload['tool_choice'] = tool_choice

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }

    accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}
    usage: Dict[str, Any] | None = None

    own_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(120.0))

    url = f'{api_base}/chat/completions'
    attempt = 0
    yielded = False  # 流式是否已开始（已向调用方 yield 过事件）→ 为 True 后不再重试
    last_err: Optional[LLMError] = None

    try:
        while True:
            if stop_event and stop_event.is_set():
                break
            try:
                async with client.stream(
                    'POST', url, json=payload, headers=headers,
                ) as response:
                    response.encoding = 'utf-8'
                    if response.status_code != 200:
                        body = await response.aread()
                        err = _classify_http_error(
                            response.status_code, body, response.headers
                        )
                        logger.warning(
                            'llm_stream non-200 kind=%s status=%s key=%s attempt=%s',
                            err.kind, err.status, _mask_key(api_key), attempt,
                        )
                        # 仅建连前、可重试、未开始流式时重试
                        if err.retryable and not yielded and attempt < _MAX_RETRIES:
                            await asyncio.sleep(_backoff_delay(err, attempt))
                            attempt += 1
                            last_err = err
                            continue  # 重新进入 async with 重试
                        raise err

                    # 200：消费流（从这里起不再重试）
                    async for line in response.aiter_lines():
                        if stop_event and stop_event.is_set():
                            break
                        if not line.startswith('data: '):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == '[DONE]':
                            break
                        try:
                            chunk = json.loads(data_str)
                            if chunk.get('usage'):
                                usage = chunk['usage']
                            choices = chunk.get('choices') or [{}]
                            choice = choices[0]
                            # delta 键存在但为 null 时 .get 返回 None，or {} 兜底防 'in' 迭代 None
                            delta = choice.get('delta', {}) or {}
                            if 'content' in delta and delta['content']:
                                yielded = True
                                yield {'type': 'delta', 'delta': delta['content']}
                            # 键存在但值为 null/空（部分 Provider 流式 chunk 会发 tool_calls: null）
                            # 必须判空，否则 for tc in None 抛 'NoneType' object is not iterable
                            if 'tool_calls' in delta and delta['tool_calls']:
                                for tc in delta['tool_calls']:
                                    if not tc:  # 数组内可能混入 null 元素
                                        continue
                                    idx = tc.get('index', 0)
                                    if idx not in accumulated_tool_calls:
                                        accumulated_tool_calls[idx] = {
                                            'id': tc.get('id', '') or f'tool_{idx}',
                                            'type': 'function',
                                            'function': {'name': '', 'arguments': ''},
                                        }
                                    acc = accumulated_tool_calls[idx]
                                    if 'id' in tc and tc['id']:
                                        acc['id'] = tc['id']
                                    func = tc.get('function', {}) or {}
                                    # function 本身可能为 null / name、arguments 可能为 null
                                    # （部分 Provider 分片 chunk 携带空值），必须判空拼接，
                                    # 否则 str += None 抛 TypeError
                                    name_part = func.get('name')
                                    if name_part:
                                        acc['function']['name'] += name_part
                                    args_part = func.get('arguments')
                                    if args_part:
                                        acc['function']['arguments'] += args_part
                        except json.JSONDecodeError:
                            continue
                    break  # 消费完成，退出重试循环
            except httpx.RequestError as e:
                # 建连/传输错误：仅未开始流式时重试
                logger.warning(
                    'llm_stream network error key=%s attempt=%s: %s',
                    _mask_key(api_key), attempt, e,
                )
                if not yielded and attempt < _MAX_RETRIES:
                    await asyncio.sleep(_backoff_delay(last_err, attempt))
                    attempt += 1
                    continue
                raise LLMError('network', 0, f'{type(e).__name__}: {e}', retryable=False)

        if accumulated_tool_calls:
            for tc in sorted(accumulated_tool_calls.values(), key=lambda x: x.get('id', '')):
                func = tc['function']
                try:
                    parsed_args = json.loads(func['arguments']) if func['arguments'] else {}
                except json.JSONDecodeError:
                    parsed_args = {}
                yield {
                    'type': 'tool_call_part',
                    'tool_call': {
                        'requestId': tc['id'],
                        'name': func['name'],
                        'arguments': parsed_args,
                    },
                }

        yield {
            'type': 'usage',
            'tokens_in': (usage or {}).get('prompt_tokens', 0),
            'tokens_out': (usage or {}).get('completion_tokens', 0),
        }
    finally:
        if own_client:
            await client.aclose()

from __future__ import annotations

import json
import httpx
from typing import AsyncGenerator, Dict, List, Any


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
    """工作流与 Agent 共享的 LLM 流式调用函数。"""
    api_base = provider.get('apiBase', '').rstrip('/')
    api_key = provider.get('apiKey', '')

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
    try:
        async with client.stream(
            'POST',
            f'{api_base}/chat/completions',
            json=payload,
            headers=headers,
        ) as response:
            response.encoding = 'utf-8'

            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f'API 请求失败 (HTTP {response.status_code}): '
                    f'{body.decode(errors="replace")[:200]}'
                )

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
                    delta = choice.get('delta', {})
                    if 'content' in delta and delta['content']:
                        yield {'type': 'delta', 'delta': delta['content']}
                    if 'tool_calls' in delta:
                        for tc in delta['tool_calls']:
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
                            func = tc.get('function', {})
                            if 'name' in func:
                                acc['function']['name'] += func['name']
                            if 'arguments' in func:
                                acc['function']['arguments'] += func['arguments']
                except json.JSONDecodeError:
                    continue

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
                    }
                }

        yield {
            'type': 'usage',
            'tokens_in': (usage or {}).get('prompt_tokens', 0),
            'tokens_out': (usage or {}).get('completion_tokens', 0),
        }
    finally:
        if own_client:
            await client.aclose()

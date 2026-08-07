"""异常分类（阶段 A2）— 把智能体运行中的异常映射为结构化错误事件载荷。

设计文档 §3.3.5：替代笼统的 ``(error: {str(e)})`` 收尾，按异常类型给出
``code`` + 用户可读 ``message`` + 恢复动作 ``recovery``（CTA 由前端映射）。
纯函数模块，无 IO 副作用，便于单测。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

import httpx

from agent_modules.agent_core.llm_stream import LLMError

logger = logging.getLogger('agent_modules.agent_core.error_classifier')

# 恢复动作注册表常量（前端 recoveryActions.ts 同步维护 handler 映射）
RECOVERY_RETRY = 'retry'
RECOVERY_OPEN_PROVIDERS = 'open:settings:providers'
RECOVERY_OPEN_MODEL_SWITCHER = 'open:model_switcher'
RECOVERY_CLEAR_MESSAGES = 'clear_messages'


def classify(exc: Exception) -> Dict[str, object]:
    """把异常映射为 ``{code, message, kind, recovery}`` 载荷。

    映射表（§3.3.5）：
    - ``LLMError(kind='auth')`` → llm_auth
    - ``LLMError(kind='rate_limit')`` → llm_rate_limit
    - ``LLMError(kind='context_overflow')`` 且压缩后仍失败 → context_too_long
    - ``LLMError(kind='timeout')`` → timeout（_stream_llm 已把 httpx.TimeoutException 包装为此 kind）
    - ``LLMError(kind='connect_error')`` → connect_failed（同上，httpx.ConnectError 包装）
    - ``httpx.TimeoutException`` / ``httpx.ConnectError``（裸异常防御，当前主流程不可达）
    - 其他 Exception → internal（附 traceId 供排查）
    """
    if isinstance(exc, LLMError):
        if exc.kind == 'auth':
            return {
                'code': 'llm_auth',
                'kind': 'auth',
                'message': 'API 鉴权失败，请检查 Provider 配置',
                'recovery': [
                    {'label': '前往 Provider 设置', 'action': RECOVERY_OPEN_PROVIDERS},
                ],
            }
        if exc.kind == 'rate_limit':
            return {
                'code': 'llm_rate_limit',
                'kind': 'rate_limit',
                'message': '请求频率超限，请稍后重试',
                'recovery': [
                    {'label': '稍后重试', 'action': RECOVERY_RETRY},
                ],
            }
        if exc.kind == 'context_overflow':
            # 上下文超限且压缩后仍失败：需要用户侧动作（清早期对话/换大模型）
            return {
                'code': 'context_too_long',
                'kind': 'context_overflow',
                'message': '上下文过长，压缩后仍超出模型限制',
                'recovery': [
                    {'label': '清空早期对话', 'action': RECOVERY_CLEAR_MESSAGES},
                    {'label': '切换更大上下文模型', 'action': RECOVERY_OPEN_MODEL_SWITCHER},
                ],
            }
        if exc.kind == 'timeout':
            # _stream_llm 把 httpx.TimeoutException 包装为 LLMError('timeout')
            return {
                'code': 'timeout',
                'kind': 'timeout',
                'message': '请求超时，请检查网络后重试',
                'recovery': [
                    {'label': '重试', 'action': RECOVERY_RETRY},
                    {'label': '检查网络', 'action': RECOVERY_OPEN_PROVIDERS},
                ],
            }
        if exc.kind == 'connect_error':
            # _stream_llm 把 httpx.ConnectError 包装为 LLMError('connect_error')
            return {
                'code': 'connect_failed',
                'kind': 'connect_error',
                'message': '无法连接到 API 服务器，请检查 apiBase 配置',
                'recovery': [
                    {'label': '检查 apiBase', 'action': RECOVERY_OPEN_PROVIDERS},
                ],
            }
        # server_error / network / unknown 等 LLM 侧可恢复错误 → internal 级重试
        return {
            'code': 'internal',
            'kind': exc.kind,
            'message': f'请求失败: {exc.kind}',
            'recovery': [
                {'label': '重试', 'action': RECOVERY_RETRY},
            ],
        }
    if isinstance(exc, httpx.TimeoutException):
        return {
            'code': 'timeout',
            'kind': 'timeout',
            'message': '请求超时，请检查网络后重试',
            'recovery': [
                {'label': '重试', 'action': RECOVERY_RETRY},
                {'label': '检查网络', 'action': RECOVERY_OPEN_PROVIDERS},
            ],
        }
    if isinstance(exc, httpx.ConnectError):
        return {
            'code': 'connect_failed',
            'kind': 'connect_error',
            'message': '无法连接到 API 服务器，请检查 apiBase 配置',
            'recovery': [
                {'label': '检查 apiBase', 'action': RECOVERY_OPEN_PROVIDERS},
            ],
        }
    # 其他 Exception：internal + traceId 供排查
    return {
        'code': 'internal',
        'kind': type(exc).__name__,
        'message': f'智能体运行异常: {exc}',
        'recovery': [
            {'label': '重试', 'action': RECOVERY_RETRY},
        ],
    }


def new_trace_id() -> str:
    """生成错误追踪 ID（错误卡片展示用，对齐消息 ID 命名风格）。"""
    return f'agent-error-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{uuid.uuid4().hex[:6]}'

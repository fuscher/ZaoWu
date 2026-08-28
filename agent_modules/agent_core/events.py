"""SSE 事件类型与序列化收敛（S13-P1-3）。

目标：可测性提升，SSE 输出与既有 ``AgentService._*_event`` **逐字节一致**
（现有 ``test_agent_service.py`` 的事件格式断言即格式护栏，本模块不得改变输出）。

设计约束（如无必要勿增实体）：
- 不做 dataclass 化、不做可替换接口、不下沉到路由层；
- 仅收敛序列化：``serialize_event(type, **fields)`` 按事件类型构造固定字段
  顺序的 payload，产出 ``data: {json}\\n\\n``。

事件枚举（9 类，与前端 ``ai.ts:235-286`` 分支一一对应）：
``delta`` / ``done`` / ``tool_call_start`` / ``tool_call_end`` /
``requires_confirmation`` / ``phase`` / ``tool_part`` / ``notice`` / ``error``。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class EventType(str, Enum):
    """SSE 事件类型枚举（9 类）。"""

    DELTA = 'delta'
    DONE = 'done'
    TOOL_CALL_START = 'tool_call_start'
    TOOL_CALL_END = 'tool_call_end'
    REQUIRES_CONFIRMATION = 'requires_confirmation'
    PHASE = 'phase'
    TOOL_PART = 'tool_part'
    NOTICE = 'notice'
    ERROR = 'error'


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def serialize_event(event_type: str, **fields: Any) -> str:
    """构造 SSE data 行（``data: {json}\\n\\n``）。

    字段顺序与既有辅助函数逐一对应（可选字段为 None 时不输出）：
    - delta: id, type, delta, done=False
    - tool_call_start: id, type, toolCall
    - requires_confirmation: id, type, toolCall
    - tool_call_end: id, type, toolResult（已含 requestId）
    - done: id, type, content, done=True, quality, [summary], [phase_history], [recovery]
    - phase: id, type, phase, ts, [detail]
    - tool_part: id, type, requestId, part, ts, [reason]
    - notice: id='system', type, level, code, message, ts, [recoverable]
    - error: id, type, code, message, ts, [kind], [recovery], [traceId]
    """
    payload: Dict[str, Any]
    if event_type == EventType.DELTA:
        payload = {
            'id': fields['id'], 'type': 'delta',
            'delta': fields['delta'], 'done': False,
        }
    elif event_type == EventType.TOOL_CALL_START:
        payload = {
            'id': fields['id'], 'type': 'tool_call_start',
            'toolCall': fields['tool_call'],
        }
    elif event_type == EventType.REQUIRES_CONFIRMATION:
        payload = {
            'id': fields['id'], 'type': 'requires_confirmation',
            'toolCall': fields['tool_call'],
        }
    elif event_type == EventType.TOOL_CALL_END:
        payload = {
            'id': fields['id'], 'type': 'tool_call_end',
            'toolResult': fields['tool_result'],
        }
    elif event_type == EventType.DONE:
        payload = {
            'id': fields['id'], 'type': 'done',
            'content': fields['content'], 'done': True,
            'quality': fields['quality'],
        }
        if fields.get('summary') is not None:
            payload['summary'] = fields['summary']
        if fields.get('phase_history'):
            payload['phase_history'] = fields['phase_history']
        if fields.get('recovery') is not None:
            payload['recovery'] = fields['recovery']
    elif event_type == EventType.PHASE:
        payload = {
            'id': fields['id'], 'type': 'phase',
            'phase': fields['phase'], 'ts': fields.get('ts', _now_ts()),
        }
        if fields.get('detail') is not None:
            payload['detail'] = fields['detail']
    elif event_type == EventType.TOOL_PART:
        payload = {
            'id': fields['id'], 'type': 'tool_part',
            'requestId': fields['request_id'], 'part': fields['part'],
            'ts': fields.get('ts', _now_ts()),
        }
        if fields.get('reason') is not None:
            payload['reason'] = fields['reason']
    elif event_type == EventType.NOTICE:
        payload = {
            'id': 'system', 'type': 'notice',
            'level': fields['level'], 'code': fields['code'],
            'message': fields['message'], 'ts': fields.get('ts', _now_ts()),
        }
        if fields.get('recoverable') is not None:
            payload['recoverable'] = fields['recoverable']
    elif event_type == EventType.ERROR:
        payload = {
            'id': fields['id'], 'type': 'error',
            'code': fields['code'], 'message': fields['message'],
            'ts': fields.get('ts', _now_ts()),
        }
        if fields.get('kind') is not None:
            payload['kind'] = fields['kind']
        if fields.get('recovery') is not None:
            payload['recovery'] = fields['recovery']
        if fields.get('trace_id') is not None:
            payload['traceId'] = fields['trace_id']
    else:
        raise ValueError(f'unknown event type: {event_type!r}')
    return f'data: {json.dumps(payload, ensure_ascii=False)}\n\n'

"""S13-P1-3: SSE 事件序列化单测（输出格式快照断言）。

现有 ``test_agent_service.py`` 的 *_event_format 用例是逐字节格式护栏，
本模块额外覆盖：字段顺序、可选字段省略、中文不转义、未知类型报错。
"""
import json

import pytest

from agent_modules.agent_core.events import EventType, serialize_event


def _parse(sse: str) -> dict:
    assert sse.startswith('data: '), f'missing data: prefix: {sse!r}'
    assert sse.endswith('\n\n'), f'missing trailing newlines: {sse!r}'
    return json.loads(sse[6:-2])


# ── delta ───────────────────────────────────────────────────

def test_delta_format_byte_exact():
    out = serialize_event(EventType.DELTA, id='m1', delta='你好')
    assert out == 'data: {"id": "m1", "type": "delta", "delta": "你好", "done": false}\n\n'


# ── tool_call_start / requires_confirmation ─────────────────

def test_tool_call_start_format_byte_exact():
    tc = {'requestId': 'r1', 'name': 'read_file', 'arguments': {'path': 'a.py'}}
    out = serialize_event(EventType.TOOL_CALL_START, id='m1', tool_call=tc)
    assert out == (
        'data: {"id": "m1", "type": "tool_call_start", '
        '"toolCall": {"requestId": "r1", "name": "read_file", '
        '"arguments": {"path": "a.py"}}}\n\n'
    )


def test_requires_confirmation_format_byte_exact():
    tc = {'requestId': 'r1', 'name': 'write_file', 'arguments': {}}
    out = serialize_event(EventType.REQUIRES_CONFIRMATION, id='m1', tool_call=tc)
    assert out == (
        'data: {"id": "m1", "type": "requires_confirmation", '
        '"toolCall": {"requestId": "r1", "name": "write_file", "arguments": {}}}\n\n'
    )


# ── tool_call_end ────────────────────────────────────────────

def test_tool_call_end_format_byte_exact():
    result = {'success': True, 'content': 'ok'}
    out = serialize_event(
        EventType.TOOL_CALL_END, id='m1',
        tool_result={**result, 'requestId': 'r1'},
    )
    assert out == (
        'data: {"id": "m1", "type": "tool_call_end", '
        '"toolResult": {"success": true, "content": "ok", "requestId": "r1"}}\n\n'
    )


# ── done ─────────────────────────────────────────────────────

def test_done_format_minimal():
    out = serialize_event(
        EventType.DONE, id='m1', content='完成', quality='success',
    )
    assert out == 'data: {"id": "m1", "type": "done", "content": "完成", "done": true, "quality": "success"}\n\n'


def test_done_format_with_optional_fields():
    out = serialize_event(
        EventType.DONE, id='m1', content='c', quality='constrained',
        summary='计划模式', phase_history=['thinking', 'tool', 'done'],
        recovery=[{'label': '切换', 'action': 'switch_preset:build'}],
    )
    payload = _parse(out)
    assert payload['summary'] == '计划模式'
    assert payload['phase_history'] == ['thinking', 'tool', 'done']
    assert payload['recovery'] == [{'label': '切换', 'action': 'switch_preset:build'}]
    # 字段顺序：content/done/quality 在前，可选字段在后
    keys = list(json.loads(out[6:-2]).keys())
    assert keys == ['id', 'type', 'content', 'done', 'quality',
                    'summary', 'phase_history', 'recovery']


def test_done_omits_none_optional_fields():
    out = serialize_event(EventType.DONE, id='m1', content='c', quality='empty')
    assert 'summary' not in out
    assert 'phase_history' not in out
    assert 'recovery' not in out


# ── phase（含动态 ts）────────────────────────────────────────

def test_phase_format():
    payload = _parse(serialize_event(EventType.PHASE, id='m1', phase='tool'))
    assert payload['id'] == 'm1'
    assert payload['type'] == 'phase'
    assert payload['phase'] == 'tool'
    assert isinstance(payload['ts'], int)
    assert 'detail' not in payload


def test_phase_format_with_detail():
    payload = _parse(serialize_event(
        EventType.PHASE, id='m1', phase='compacting', detail='预算触发主动压缩',
    ))
    assert payload['detail'] == '预算触发主动压缩'


# ── tool_part（含动态 ts）────────────────────────────────────

def test_tool_part_format():
    payload = _parse(serialize_event(
        EventType.TOOL_PART, id='m1', request_id='r1', part='running',
    ))
    assert payload == {'id': 'm1', 'type': 'tool_part', 'requestId': 'r1',
                       'part': 'running', 'ts': payload['ts']}
    assert isinstance(payload['ts'], int)
    assert 'reason' not in payload


def test_tool_part_format_with_reason():
    payload = _parse(serialize_event(
        EventType.TOOL_PART, id='m1', request_id='r1', part='denied',
        reason='plan_mode_readonly',
    ))
    assert payload['reason'] == 'plan_mode_readonly'


# ── notice（含动态 ts）───────────────────────────────────────

def test_notice_format():
    payload = _parse(serialize_event(
        EventType.NOTICE, level='warn', code='compacted',
        message='已自动压缩早期对话',
    ))
    assert payload['id'] == 'system'
    assert payload['type'] == 'notice'
    assert payload['level'] == 'warn'
    assert payload['code'] == 'compacted'
    assert payload['message'] == '已自动压缩早期对话'
    assert isinstance(payload['ts'], int)
    assert 'recoverable' not in payload


def test_notice_format_with_recoverable():
    payload = _parse(serialize_event(
        EventType.NOTICE, level='warn', code='user_stopped',
        message='生成已被用户终止', recoverable=True,
    ))
    assert payload['recoverable'] is True


# ── error（含动态 ts）────────────────────────────────────────

def test_error_format_minimal():
    payload = _parse(serialize_event(
        EventType.ERROR, id='err1', code='internal', message='运行异常',
    ))
    assert payload == {'id': 'err1', 'type': 'error', 'code': 'internal',
                       'message': '运行异常', 'ts': payload['ts']}


def test_error_format_with_optional_fields():
    payload = _parse(serialize_event(
        EventType.ERROR, id='err1', code='llm_auth', message='鉴权失败',
        kind='provider', recovery=[{'label': '重试', 'action': 'retry'}],
        trace_id='trace-1',
    ))
    assert payload['kind'] == 'provider'
    assert payload['recovery'] == [{'label': '重试', 'action': 'retry'}]
    assert payload['traceId'] == 'trace-1'
    keys = list(payload.keys())
    assert keys == ['id', 'type', 'code', 'message', 'ts', 'kind', 'recovery', 'traceId']


# ── 未知类型 ─────────────────────────────────────────────────

def test_unknown_event_type_raises():
    with pytest.raises(ValueError):
        serialize_event('bogus', id='m1')

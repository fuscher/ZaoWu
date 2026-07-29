import asyncio
import json
import os
import random
import string
import tempfile

import pytest

pytestmark = pytest.mark.anyio

from workflow_engine.schema import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, NodeType, EdgeType,
)
from workflow_engine.executor import execute_workflow
from workflow_engine.node_registry import NodeRegistry
from workflow_engine.nodes.base import BaseNode
from workflow_engine.nodes.tool_node import ToolNode


def _make_def(nodes, edges, name='Test'):
    return WorkflowDefinition(
        id='wf-test',
        name=name,
        nodes=nodes,
        edges=edges,
    )


async def _collect(definition, initial_input=''):
    stop = asyncio.Event()
    events = []
    async for e in execute_workflow(definition, stop,
                                     confirm_callback=lambda nid, tc: True,
                                     initial_input=initial_input):
        events.append(e)
    return events


async def test_condition_expression_with_str_methods():
    """Condition expression 支持 str 方法：.upper() / .startswith() 等。"""
    nodes = [
        WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
        WorkflowNode(id='cond', type=NodeType.CONDITION, position={'x': 0, 'y': 0}, label='Cond',
                     config={'conditionConfig': {
                         'mode': 'expression',
                         'expression': 'input.upper().startswith("HELLO")',
                     }}),
        WorkflowNode(id='t_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='True'),
        WorkflowNode(id='f_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='False'),
    ]
    edges = [
        WorkflowEdge(id='e1', source='start', source_port='default', target='cond', target_port='default'),
        WorkflowEdge(id='e2', source='cond', source_port='true', target='t_end', target_port='default', edge_type=EdgeType.CONDITION),
        WorkflowEdge(id='e3', source='cond', source_port='false', target='f_end', target_port='default', edge_type=EdgeType.CONDITION),
    ]
    events = await _collect(_make_def(nodes, edges), 'hello world')
    assert events[-1]['type'] == 'wf_completed'
    assert any(e['type'] == 'node_ended' and e['nodeId'] == 't_end' for e in events)


async def test_end_log_mode_custom_name():
    """End 节点 log 模式指定自定义文件名。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nodes = [
            WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
            WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End',
                         config={'endMode': 'log', 'logFormat': 'txt', 'logDir': tmpdir, 'logName': 'my-report'}),
        ]
        edges = [
            WorkflowEdge(id='e1', source='start', source_port='default', target='end', target_port='default'),
        ]
        events = await _collect(_make_def(nodes, edges), 'test content')
        assert events[-1]['type'] == 'wf_completed'

        report_path = os.path.join(tmpdir, 'my-report.txt')
        assert os.path.exists(report_path)
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'test content' in content


async def test_end_log_mode_auto_name():
    """End 节点 log 模式自动生成文件名。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nodes = [
            WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
            WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End',
                         config={'endMode': 'log', 'logFormat': 'txt', 'logDir': tmpdir}),
        ]
        edges = [
            WorkflowEdge(id='e1', source='start', source_port='default', target='end', target_port='default'),
        ]
        events = await _collect(_make_def(nodes, edges, 'MyTestWF'), 'auto-name')
        assert events[-1]['type'] == 'wf_completed'

        files = [f for f in os.listdir(tmpdir) if f.endswith('.txt')]
        assert len(files) == 1
        # 自动生成的文件名应包含工作流名
        assert 'MyTestWF' in files[0]


async def test_condition_fallback_on_error():
    """Condition 表达式出错时使用 fallbackBranch。"""
    nodes = [
        WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
        WorkflowNode(id='cond', type=NodeType.CONDITION, position={'x': 0, 'y': 0}, label='Cond',
                     config={'conditionConfig': {
                         'mode': 'expression',
                         'expression': 'undefined_var > 0',
                         'fallbackBranch': 'true',
                     }}),
        WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
    ]
    edges = [
        WorkflowEdge(id='e1', source='start', source_port='default', target='cond', target_port='default'),
        WorkflowEdge(id='e2', source='cond', source_port='true', target='end', target_port='default', edge_type=EdgeType.CONDITION),
    ]
    events = await _collect(_make_def(nodes, edges), 'anything')
    assert events[-1]['type'] == 'wf_completed'
    assert any(e['type'] == 'node_ended' and e['nodeId'] == 'end' for e in events)


async def test_condition_simple_with_regex():
    """Condition simple 模式 regex 操作符。"""
    nodes = [
        WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
        WorkflowNode(id='cond', type=NodeType.CONDITION, position={'x': 0, 'y': 0}, label='Cond',
                     config={'conditionConfig': {'mode': 'simple', 'rules': [
                         {'operator': 'regex', 'value': '\d{3,}', 'branch': 'true'},
                     ]}}),
        WorkflowNode(id='t_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='True'),
        WorkflowNode(id='f_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='False'),
    ]
    edges = [
        WorkflowEdge(id='e1', source='start', source_port='default', target='cond', target_port='default'),
        WorkflowEdge(id='e2', source='cond', source_port='true', target='t_end', target_port='default', edge_type=EdgeType.CONDITION),
        WorkflowEdge(id='e3', source='cond', source_port='false', target='f_end', target_port='default', edge_type=EdgeType.CONDITION),
    ]
    events = await _collect(_make_def(nodes, edges), 'abc 12345 xyz')
    assert events[-1]['type'] == 'wf_completed'
    assert any(e['type'] == 'node_ended' and e['nodeId'] == 't_end' for e in events)


async def test_multi_tool_execution():
    """同一工作流中顺序执行两个 Tool 节点。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nodes = [
            WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
            WorkflowNode(id='tool1', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='List',
                         config={'toolName': 'list_files', 'toolArgs': {'path': tmpdir}}),
            WorkflowNode(id='tool2', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='Search',
                         config={'toolName': 'web_search', 'toolArgs': {'query': 'test'}}),
            WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
        ]
        edges = [
            WorkflowEdge(id='e1', source='start', source_port='default', target='tool1', target_port='default'),
            WorkflowEdge(id='e2', source='tool1', source_port='default', target='tool2', target_port='default'),
            WorkflowEdge(id='e3', source='tool2', source_port='default', target='end', target_port='default'),
        ]
        events = await _collect(_make_def(nodes, edges))
        assert events[-1]['type'] == 'wf_completed'
        ended = [e for e in events if e['type'] == 'node_ended']
        assert len(ended) >= 2


async def test_loop_control_break_signal():
    """Loop 体内节点输出 __control__: 'break' 应提前终止循环。

    用 stub 节点替换 TOOL handler，使其首轮即输出 {'__control__': 'break'}，
    验证循环不会跑满 maxIterations=100，而是只执行 1 轮。
    """
    class _BreakStubNode(BaseNode):
        node_type = 'tool'

        async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
            # 首轮即发出 break 控制信号
            ctx_node.outputs = {'default': 'done', '__control__': 'break'}
            yield {'type': 'node_started', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}

    original = NodeRegistry.get_handlers().get('tool')
    NodeRegistry.register('tool', _BreakStubNode)
    try:
        nodes = [
            WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
            WorkflowNode(id='loop', type=NodeType.LOOP, position={'x': 0, 'y': 0}, label='Loop',
                         config={'loopConfig': {
                             'mode': 'canvas',
                             'maxIterations': 100,
                             'bodyNodeIds': ['body_tool'],
                             'bodyEdges': [],
                         }}),
            WorkflowNode(id='body_tool', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='BodyTool',
                         config={'toolName': 'list_files', 'toolArgs': {'path': '.'}}),
            WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
        ]
        edges = [
            WorkflowEdge(id='e1', source='start', source_port='default', target='loop', target_port='in'),
            WorkflowEdge(id='e2', source='loop', source_port='out_end', target='end', target_port='default'),
        ]
        definition = _make_def(nodes, edges)
        events = await _collect(definition, 'go')

        assert events[-1]['type'] == 'wf_completed'
        # break 生效：Loop 节点每轮会 yield 一个 node_progress（delta 含 iteration），
        # break 后立即退出，故只应有 1 个 progress 事件（iteration=0），而非 100 个
        loop_progress = [e for e in events
                         if e.get('type') == 'node_progress' and e.get('nodeId') == 'loop']
        assert len(loop_progress) == 1, (
            f'break 信号未生效，循环执行了 {len(loop_progress)} 轮（预期 1 轮）'
        )
        # End 节点被激活
        assert any(e['type'] == 'node_ended' and e['nodeId'] == 'end' for e in events)
    finally:
        NodeRegistry.register('tool', original or ToolNode)


async def test_condition_expression_numeric_comparison():
    """Condition expression 数值比较不应因字符串类型而静默 fallback。"""
    nodes = [
        WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
        WorkflowNode(id='cond', type=NodeType.CONDITION, position={'x': 0, 'y': 0}, label='Cond',
                     config={'conditionConfig': {
                         'mode': 'expression',
                         'expression': 'input > 10',
                     }}),
        WorkflowNode(id='t_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='True'),
        WorkflowNode(id='f_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='False'),
    ]
    edges = [
        WorkflowEdge(id='e1', source='start', source_port='default', target='cond', target_port='default'),
        WorkflowEdge(id='e2', source='cond', source_port='true', target='t_end', target_port='default', edge_type=EdgeType.CONDITION),
        WorkflowEdge(id='e3', source='cond', source_port='false', target='f_end', target_port='default', edge_type=EdgeType.CONDITION),
    ]
    events = await _collect(_make_def(nodes, edges), '42')
    assert events[-1]['type'] == 'wf_completed'
    assert any(e['type'] == 'node_ended' and e['nodeId'] == 't_end' for e in events)


async def test_condition_expression_string_equality_preserved():
    """Condition expression 字符串相等语义应保留，数字串比较也成立。"""
    nodes = [
        WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
        WorkflowNode(id='cond', type=NodeType.CONDITION, position={'x': 0, 'y': 0}, label='Cond',
                     config={'conditionConfig': {
                         'mode': 'expression',
                         'expression': 'input == "hello"',
                     }}),
        WorkflowNode(id='t_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='True'),
        WorkflowNode(id='f_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='False'),
    ]
    edges = [
        WorkflowEdge(id='e1', source='start', source_port='default', target='cond', target_port='default'),
        WorkflowEdge(id='e2', source='cond', source_port='true', target='t_end', target_port='default', edge_type=EdgeType.CONDITION),
        WorkflowEdge(id='e3', source='cond', source_port='false', target='f_end', target_port='default', edge_type=EdgeType.CONDITION),
    ]
    events = await _collect(_make_def(nodes, edges), 'hello')
    assert events[-1]['type'] == 'wf_completed'
    assert any(e['type'] == 'node_ended' and e['nodeId'] == 't_end' for e in events)


async def test_loop_multi_node_body_data_flow():
    """Loop 体内多节点时，下游节点应能拿到上游 body 节点的输出。"""
    class _PassThroughNode(BaseNode):
        node_type = 'tool'

        async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
            inp = ctx.resolve('{{input}}', ctx_node.inputs)
            ctx_node.outputs = {'default': f'processed({inp})'}
            yield {'type': 'node_started', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}
            yield {'type': 'node_ended', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}

    original = NodeRegistry.get_handlers().get('tool')
    NodeRegistry.register('tool', _PassThroughNode)
    try:
        nodes = [
            WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
            WorkflowNode(id='loop', type=NodeType.LOOP, position={'x': 0, 'y': 0}, label='Loop',
                         config={'loopConfig': {
                             'mode': 'canvas',
                             'maxIterations': 2,
                             'bodyNodeIds': ['body_1', 'body_2'],
                             'bodyEdges': [
                                 {'id': 'be1', 'source': 'body_1', 'sourcePort': 'default',
                                  'target': 'body_2', 'targetPort': 'default'},
                             ],
                         }}),
            WorkflowNode(id='body_1', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='Body1'),
            WorkflowNode(id='body_2', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='Body2'),
            WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
        ]
        edges = [
            WorkflowEdge(id='e1', source='start', source_port='default', target='loop', target_port='in'),
            WorkflowEdge(id='e2', source='loop', source_port='out_end', target='end', target_port='default'),
        ]
        events = await _collect(_make_def(nodes, edges), 'go')
        assert events[-1]['type'] == 'wf_completed'
        # 第二轮输入来自 body_2 的输出；body_2 的输入又来自 body_1 的输出
        # 因此循环应能正确运行 2 轮而不是因 feedback 为空而提前退出
        loop_progress = [e for e in events
                         if e.get('type') == 'node_progress' and e.get('nodeId') == 'loop']
        assert len(loop_progress) == 2, (
            f'多节点 body 数据流异常，循环执行了 {len(loop_progress)} 轮（预期 2 轮）'
        )
    finally:
        NodeRegistry.register('tool', original or ToolNode)

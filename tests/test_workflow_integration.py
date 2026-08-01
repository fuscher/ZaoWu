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
    WorkflowExecutionConfig,
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


async def test_loop_body_end_terminates_workflow():
    """循环体内接 End 节点时，应强制结束整个工作流且不执行 loop.out 下游。"""
    class _BodyToolStub(BaseNode):
        node_type = 'tool'

        async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
            ctx_node.outputs = {'default': 'body-output'}
            yield {'type': 'node_started', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}
            yield {'type': 'node_ended', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}

    original = NodeRegistry.get_handlers().get('tool')
    NodeRegistry.register('tool', _BodyToolStub)
    try:
        nodes = [
            WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
            WorkflowNode(id='loop', type=NodeType.LOOP, position={'x': 0, 'y': 0}, label='Loop',
                         config={'loopConfig': {'maxIterations': 100}}),
            WorkflowNode(id='body_tool', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='BodyTool'),
            WorkflowNode(id='body_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='BodyEnd',
                         config={'endMode': 'log', 'logFormat': 'txt', 'logDir': './workflow_logs'}),
            WorkflowNode(id='out_tool', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='OutTool'),
            WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
        ]
        edges = [
            WorkflowEdge(id='e1', source='start', source_port='default', target='loop', target_port='in'),
            WorkflowEdge(id='e2', source='loop', source_port='body', target='body_tool', target_port='default'),
            WorkflowEdge(id='e3', source='body_tool', source_port='default', target='body_end', target_port='default'),
            WorkflowEdge(id='e4', source='loop', source_port='out', target='out_tool', target_port='default'),
            WorkflowEdge(id='e5', source='out_tool', source_port='default', target='end', target_port='default'),
        ]
        definition = _make_def(nodes, edges)
        events = await _collect(definition, 'go')

        assert events[-1]['type'] == 'wf_completed'
        # End 触发后只执行 1 轮
        loop_progress = [e for e in events
                         if e.get('type') == 'node_progress' and e.get('nodeId') == 'loop']
        assert len(loop_progress) == 1, (
            f'End 未提前终止，循环执行了 {len(loop_progress)} 轮（预期 1 轮）'
        )
        # body 内 End 执行了，但 loop.out 下游没有执行
        assert any(e['type'] == 'node_ended' and e['nodeId'] == 'body_end' for e in events)
        assert not any(e['type'] == 'node_ended' and e['nodeId'] == 'out_tool' for e in events)
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
    """Loop 体内多节点通过真实画布边连接时，下游节点应能拿到上游输出。"""
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
                         config={'loopConfig': {'maxIterations': 2}}),
            WorkflowNode(id='body_1', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='Body1'),
            WorkflowNode(id='body_2', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='Body2'),
            WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
        ]
        edges = [
            WorkflowEdge(id='e1', source='start', source_port='default', target='loop', target_port='in'),
            WorkflowEdge(id='e2', source='loop', source_port='body', target='body_1', target_port='default'),
            WorkflowEdge(id='e3', source='body_1', source_port='default', target='body_2', target_port='default'),
            WorkflowEdge(id='e4', source='loop', source_port='out', target='end', target_port='default'),
        ]
        events = await _collect(_make_def(nodes, edges), 'go')
        assert events[-1]['type'] == 'wf_completed'
        # 第二轮输入来自 body_2 的输出；body_2 的输入又来自 body_1 的输出
        loop_progress = [e for e in events
                         if e.get('type') == 'node_progress' and e.get('nodeId') == 'loop']
        assert len(loop_progress) == 2, (
            f'多节点 body 数据流异常，循环执行了 {len(loop_progress)} 轮（预期 2 轮）'
        )
    finally:
        NodeRegistry.register('tool', original or ToolNode)


async def test_loop_body_empty_runs_max_iterations():
    """body 不连任何节点时应跑满 maxIterations 次。"""
    nodes = [
        WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
        WorkflowNode(id='loop', type=NodeType.LOOP, position={'x': 0, 'y': 0}, label='Loop',
                     config={'loopConfig': {'maxIterations': 3}}),
        WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
    ]
    edges = [
        WorkflowEdge(id='e1', source='start', source_port='default', target='loop', target_port='in'),
        WorkflowEdge(id='e2', source='loop', source_port='out', target='end', target_port='default'),
    ]
    events = await _collect(_make_def(nodes, edges), 'go')
    assert events[-1]['type'] == 'wf_completed'
    loop_progress = [e for e in events
                     if e.get('type') == 'node_progress' and e.get('nodeId') == 'loop']
    assert len(loop_progress) == 3


async def test_loop_body_not_executed_by_main_executor():
    """循环体节点应仅由 Loop 内部驱动，主执行器不再重复执行。"""
    class _OnceNode(BaseNode):
        node_type = 'tool'

        async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
            ctx_node.outputs = {'default': 'x'}
            yield {'type': 'node_started', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}
            yield {'type': 'node_ended', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}

    original = NodeRegistry.get_handlers().get('tool')
    NodeRegistry.register('tool', _OnceNode)
    try:
        nodes = [
            WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
            WorkflowNode(id='loop', type=NodeType.LOOP, position={'x': 0, 'y': 0}, label='Loop',
                         config={'loopConfig': {'maxIterations': 3}}),
            WorkflowNode(id='body', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='Body'),
            WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
        ]
        edges = [
            WorkflowEdge(id='e1', source='start', source_port='default', target='loop', target_port='in'),
            WorkflowEdge(id='e2', source='loop', source_port='body', target='body', target_port='default'),
            WorkflowEdge(id='e3', source='loop', source_port='out', target='end', target_port='default'),
        ]
        events = await _collect(_make_def(nodes, edges), 'go')
        assert events[-1]['type'] == 'wf_completed'
        body_ended = [e for e in events if e['type'] == 'node_ended' and e['nodeId'] == 'body']
        assert len(body_ended) == 3, f'循环体节点应执行 3 次（每轮 1 次），实际 {len(body_ended)} 次'
    finally:
        NodeRegistry.register('tool', original or ToolNode)


async def test_loop_condition_branch_gate_resets_each_iteration():
    """Condition 分支门控每轮重置，第二轮条件翻转后未选中分支可恢复执行。"""
    class _ValueNode(BaseNode):
        node_type = 'tool'

        async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
            default_input = ctx_node.inputs.get('default', [''])[0]
            value = self.config.get('outputValue', default_input)
            ctx_node.outputs = {'default': value}
            yield {'type': 'node_started', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}
            yield {'type': 'node_ended', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}

    original = NodeRegistry.get_handlers().get('tool')
    NodeRegistry.register('tool', _ValueNode)
    try:
        nodes = [
            WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
            WorkflowNode(id='loop', type=NodeType.LOOP, position={'x': 0, 'y': 0}, label='Loop',
                         config={'loopConfig': {'maxIterations': 2}}),
            WorkflowNode(id='cond', type=NodeType.CONDITION, position={'x': 0, 'y': 0}, label='Cond',
                         config={'conditionConfig': {
                             'mode': 'expression',
                             'expression': 'input == "0"',
                         }}),
            # T 分支输出 1，F 分支输出 0；下一轮输入翻转，验证未选中分支第二轮能执行
            WorkflowNode(id='t_node', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='TrueNode',
                         config={'outputValue': '1'}),
            WorkflowNode(id='f_node', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='FalseNode',
                         config={'outputValue': '0'}),
            WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
        ]
        edges = [
            WorkflowEdge(id='e1', source='start', source_port='default', target='loop', target_port='in'),
            WorkflowEdge(id='e2', source='loop', source_port='body', target='cond', target_port='default'),
            WorkflowEdge(id='e3', source='cond', source_port='true', target='t_node', target_port='default',
                         edge_type=EdgeType.CONDITION),
            WorkflowEdge(id='e4', source='cond', source_port='false', target='f_node', target_port='default',
                         edge_type=EdgeType.CONDITION),
            WorkflowEdge(id='e5', source='loop', source_port='out', target='end', target_port='default'),
        ]
        events = await _collect(_make_def(nodes, edges), '0')
        assert events[-1]['type'] == 'wf_completed'
        # 第一轮输入 0 -> T；T 输出 1 -> 第二轮输入 1 -> F
        t_ended = [e for e in events if e['type'] == 'node_ended' and e['nodeId'] == 't_node']
        f_ended = [e for e in events if e['type'] == 'node_ended' and e['nodeId'] == 'f_node']
        assert len(t_ended) == 1, f'T 分支应执行 1 次，实际 {len(t_ended)} 次'
        assert len(f_ended) == 1, f'F 分支应执行 1 次，实际 {len(f_ended)} 次'
    finally:
        NodeRegistry.register('tool', original or ToolNode)


async def test_loop_global_max_iterations_cap():
    """Loop 自身 maxIterations 受 execution_config.max_iterations 限制。"""
    class _OnceNode(BaseNode):
        node_type = 'tool'

        async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
            ctx_node.outputs = {'default': 'x'}
            yield {'type': 'node_started', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}
            yield {'type': 'node_ended', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}

    original = NodeRegistry.get_handlers().get('tool')
    NodeRegistry.register('tool', _OnceNode)
    try:
        nodes = [
            WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
            WorkflowNode(id='loop', type=NodeType.LOOP, position={'x': 0, 'y': 0}, label='Loop',
                         config={'loopConfig': {'maxIterations': 100}}),
            WorkflowNode(id='body', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='Body'),
            WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
        ]
        edges = [
            WorkflowEdge(id='e1', source='start', source_port='default', target='loop', target_port='in'),
            WorkflowEdge(id='e2', source='loop', source_port='body', target='body', target_port='default'),
            WorkflowEdge(id='e3', source='loop', source_port='out', target='end', target_port='default'),
        ]
        definition = _make_def(nodes, edges)
        definition.execution_config = WorkflowExecutionConfig(max_iterations=3)
        events = await _collect(definition, 'go')
        assert events[-1]['type'] == 'wf_completed'
        loop_progress = [e for e in events
                         if e.get('type') == 'node_progress' and e.get('nodeId') == 'loop']
        assert len(loop_progress) == 3
    finally:
        NodeRegistry.register('tool', original or ToolNode)


async def test_loop_body_multiple_exit_aggregation():
    """循环体多出口节点的输出应聚合为列表作为下一轮输入。"""
    class _MultiExitNode(BaseNode):
        """入口节点输出输入的 raw；带 outputValue 的节点输出该值。"""
        node_type = 'tool'

        async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
            value = self.config.get('outputValue')
            if value is not None:
                ctx_node.outputs = {'default': value}
            else:
                raw = ctx_node.inputs.get('default', [])
                ctx_node.outputs = {'default': f'entry_raw={raw!r}'}
            yield {'type': 'node_started', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}
            yield {'type': 'node_ended', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id,
                   'output': ctx_node.outputs}

    original = NodeRegistry.get_handlers().get('tool')
    NodeRegistry.register('tool', _MultiExitNode)
    try:
        nodes = [
            WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
            WorkflowNode(id='loop', type=NodeType.LOOP, position={'x': 0, 'y': 0}, label='Loop',
                         config={'loopConfig': {'maxIterations': 2}}),
            WorkflowNode(id='entry', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='Entry'),
            WorkflowNode(id='branch_a', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='BranchA',
                         config={'outputValue': 'A'}),
            WorkflowNode(id='branch_b', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='BranchB',
                         config={'outputValue': 'B'}),
            WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
        ]
        edges = [
            WorkflowEdge(id='e1', source='start', source_port='default', target='loop', target_port='in'),
            WorkflowEdge(id='e2', source='loop', source_port='body', target='entry', target_port='default'),
            WorkflowEdge(id='e3', source='entry', source_port='default', target='branch_a', target_port='default'),
            WorkflowEdge(id='e4', source='entry', source_port='default', target='branch_b', target_port='default'),
            WorkflowEdge(id='e5', source='loop', source_port='out', target='end', target_port='default'),
        ]
        events = await _collect(_make_def(nodes, edges), 'go')
        assert events[-1]['type'] == 'wf_completed'

        entry_outputs = [e for e in events
                         if e['type'] == 'node_ended' and e.get('nodeId') == 'entry']
        assert len(entry_outputs) == 2, f'入口节点应执行 2 次，实际 {len(entry_outputs)} 次'
        # 第一轮入口收到初始标量（被包装为 list）
        assert "entry_raw=['go']" in entry_outputs[0]['output'].get('default', '')
        # 第二轮入口收到多出口聚合列表 ['A', 'B']
        assert "entry_raw=['A', 'B']" in entry_outputs[1]['output'].get('default', '')
    finally:
        NodeRegistry.register('tool', original or ToolNode)


async def test_loop_body_does_not_swallow_shared_downstream():
    """body 末节点连到 loop.out 下游的共享 End 时，End 不应被吞进循环体。"""
    class _OnceNode(BaseNode):
        node_type = 'tool'

        async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
            ctx_node.outputs = {'default': 'x'}
            yield {'type': 'node_started', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}
            yield {'type': 'node_ended', 'workflowId': ctx.workflow_id,
                   'runId': ctx.run_id, 'nodeId': ctx_node.node_id}

    original = NodeRegistry.get_handlers().get('tool')
    NodeRegistry.register('tool', _OnceNode)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            nodes = [
                WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
                WorkflowNode(id='loop', type=NodeType.LOOP, position={'x': 0, 'y': 0}, label='Loop',
                             config={'loopConfig': {'maxIterations': 2}}),
                WorkflowNode(id='body', type=NodeType.TOOL, position={'x': 0, 'y': 0}, label='Body'),
                WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End',
                             config={'endMode': 'log', 'logFormat': 'txt', 'logDir': tmpdir}),
            ]
            edges = [
                WorkflowEdge(id='e1', source='start', source_port='default', target='loop', target_port='in'),
                WorkflowEdge(id='e2', source='loop', source_port='body', target='body', target_port='default'),
                WorkflowEdge(id='e3', source='loop', source_port='out', target='end', target_port='default'),
                WorkflowEdge(id='e4', source='body', source_port='default', target='end', target_port='default'),
            ]
            events = await _collect(_make_def(nodes, edges), 'go')
            assert events[-1]['type'] == 'wf_completed'

            # End 不在循环体内，因此 loop 应跑满 2 轮，且 End 在 loop.out 后执行一次
            body_ended = [e for e in events if e['type'] == 'node_ended' and e['nodeId'] == 'body']
            assert len(body_ended) == 2, f'Body 应执行 2 次，实际 {len(body_ended)} 次'
            end_ended = [e for e in events if e['type'] == 'node_ended' and e['nodeId'] == 'end']
            assert len(end_ended) == 1, f'共享 End 应只执行 1 次，实际 {len(end_ended)} 次'

            # End 日志应能正常生成
            files = [f for f in os.listdir(tmpdir) if f.endswith('.txt')]
            assert len(files) == 1
    finally:
        NodeRegistry.register('tool', original or ToolNode)

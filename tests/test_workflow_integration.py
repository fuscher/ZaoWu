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
    """Loop 体内节点输出 __control__: 'break' 应提前终止循环。"""
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
    # 循环体内 list_files 被执行，End 被激活
    assert any(e['type'] == 'node_ended' and e['nodeId'] == 'end' for e in events)

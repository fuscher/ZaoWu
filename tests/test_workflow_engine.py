import asyncio
import pytest

pytestmark = pytest.mark.anyio

from workflow_engine.schema import WorkflowDefinition, WorkflowNode, WorkflowEdge, NodeType, EdgeType
from workflow_engine.executor import WorkflowExecutor, execute_workflow


def _make_definition(nodes, edges):
    return WorkflowDefinition(
        id='wf-test',
        name='Test',
        nodes=nodes,
        edges=edges,
    )


def test_topological_sort():
    nodes = [
        WorkflowNode(id='a', type=NodeType.START, position={'x': 0, 'y': 0}, label='A'),
        WorkflowNode(id='b', type=NodeType.LLM, position={'x': 0, 'y': 0}, label='B'),
        WorkflowNode(id='c', type=NodeType.END, position={'x': 0, 'y': 0}, label='C'),
    ]
    edges = [
        WorkflowEdge(id='e1', source='a', source_port='default', target='b', target_port='default'),
        WorkflowEdge(id='e2', source='b', source_port='default', target='c', target_port='default'),
    ]
    executor = WorkflowExecutor(_make_definition(nodes, edges))
    order = executor._topological_sort()
    assert order.index('a') < order.index('b') < order.index('c')


def test_cycle_detection():
    nodes = [
        WorkflowNode(id='a', type=NodeType.START, position={'x': 0, 'y': 0}, label='A'),
        WorkflowNode(id='b', type=NodeType.LLM, position={'x': 0, 'y': 0}, label='B'),
    ]
    edges = [
        WorkflowEdge(id='e1', source='a', source_port='default', target='b', target_port='default'),
        WorkflowEdge(id='e2', source='b', source_port='default', target='a', target_port='default'),
    ]
    executor = WorkflowExecutor(_make_definition(nodes, edges))
    with pytest.raises(ValueError):
        executor._topological_sort()


def test_validate_requires_start_and_end():
    nodes = [WorkflowNode(id='a', type=NodeType.LLM, position={'x': 0, 'y': 0}, label='A')]
    edges = []
    errors = WorkflowExecutor(_make_definition(nodes, edges)).validate()
    assert any('开始节点' in e for e in errors)
    assert any('结束节点' in e for e in errors)


async def test_minimal_workflow_without_llm():
    """Start -> End 的最小工作流，验证执行器终态事件。"""
    nodes = [
        WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
        WorkflowNode(id='end', type=NodeType.END, position={'x': 0, 'y': 0}, label='End'),
    ]
    edges = [
        WorkflowEdge(id='e1', source='start', source_port='default', target='end', target_port='default'),
    ]
    definition = _make_definition(nodes, edges)
    stop_event = asyncio.Event()

    events = []
    async for event in execute_workflow(
        definition,
        stop_event,
        confirm_callback=lambda node_id, tc: True,
        initial_input='hello',
    ):
        events.append(event)

    assert events[0]['type'] == 'wf_started'
    assert events[-1]['type'] == 'wf_completed'
    assert any(e['type'] == 'node_ended' and e['nodeId'] == 'end' for e in events)


async def test_condition_branch_code_mode():
    nodes = [
        WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
        WorkflowNode(id='cond', type=NodeType.CONDITION, position={'x': 0, 'y': 0}, label='Cond',
                     config={'conditionConfig': {'mode': 'code', 'expression': 'input == "yes"'}}),
        WorkflowNode(id='true_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='True'),
        WorkflowNode(id='false_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='False'),
    ]
    edges = [
        WorkflowEdge(id='e1', source='start', source_port='default', target='cond', target_port='default'),
        WorkflowEdge(id='e2', source='cond', source_port='true', target='true_end', target_port='default',
                     edge_type=EdgeType.CONDITION),
        WorkflowEdge(id='e3', source='cond', source_port='false', target='false_end', target_port='default',
                     edge_type=EdgeType.CONDITION),
    ]
    definition = _make_definition(nodes, edges)
    stop_event = asyncio.Event()

    events = []
    async for event in execute_workflow(
        definition,
        stop_event,
        confirm_callback=lambda node_id, tc: True,
        initial_input='yes',
    ):
        events.append(event)

    assert events[-1]['type'] == 'wf_completed'
    assert any(e['type'] == 'node_ended' and e['nodeId'] == 'true_end' for e in events)
    assert not any(e['type'] == 'node_ended' and e['nodeId'] == 'false_end' for e in events)


async def test_condition_dead_branch_downstream_not_executed():
    """条件选中某一分支后，未选中分支的下游节点不应被误触发。

    回归场景（工作流 A v6）：条件选 false，false 分支直接接 End；true 分支为
    LLM→工具→LLM→End。条件只会 deactivate true 的直连边，但 true 分支内部边
    仍 active，导致 true 分支下游节点在其上游从未执行时被误触发。
    这里用 endMode='none' 的 End 节点模拟无副作用的下游节点。
    """
    nodes = [
        WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
        WorkflowNode(id='cond', type=NodeType.CONDITION, position={'x': 0, 'y': 0}, label='Cond',
                     config={'conditionConfig': {'mode': 'expression', 'expression': 'input == "yes"'}}),
        # true 分支（死分支）：dead_a → dead_b
        WorkflowNode(id='dead_a', type=NodeType.END, position={'x': 0, 'y': 0}, label='DeadA',
                     config={'endMode': 'none'}),
        WorkflowNode(id='dead_b', type=NodeType.END, position={'x': 0, 'y': 0}, label='DeadB',
                     config={'endMode': 'none'}),
        # false 分支（选中）：直接接 End
        WorkflowNode(id='good_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='GoodEnd',
                     config={'endMode': 'none'}),
    ]
    edges = [
        WorkflowEdge(id='e1', source='start', source_port='default', target='cond', target_port='default'),
        WorkflowEdge(id='e2', source='cond', source_port='true', target='dead_a', target_port='default',
                     edge_type=EdgeType.CONDITION),
        WorkflowEdge(id='e3', source='dead_a', source_port='default', target='dead_b', target_port='default'),
        WorkflowEdge(id='e4', source='cond', source_port='false', target='good_end', target_port='default',
                     edge_type=EdgeType.CONDITION),
    ]
    definition = _make_definition(nodes, edges)
    stop_event = asyncio.Event()

    events = []
    async for event in execute_workflow(
        definition,
        stop_event,
        confirm_callback=lambda node_id, tc: True,
        initial_input='no',
    ):
        events.append(event)

    assert events[-1]['type'] == 'wf_completed'
    # 选中分支的 End 应执行
    assert any(e['type'] == 'node_ended' and e['nodeId'] == 'good_end' for e in events)
    # 死分支的下游节点不应被误触发（关键回归断言）
    assert not any(e['type'] == 'node_ended' and e['nodeId'] == 'dead_a' for e in events)
    assert not any(e['type'] == 'node_ended' and e['nodeId'] == 'dead_b' for e in events)


async def _run_cond_events(expression: str, initial_input: str) -> set[str]:
    """跑一个 Start→Cond→{true_end, false_end} 的工作流，返回已执行节点 id 集合。"""
    nodes = [
        WorkflowNode(id='start', type=NodeType.START, position={'x': 0, 'y': 0}, label='Start'),
        WorkflowNode(id='cond', type=NodeType.CONDITION, position={'x': 0, 'y': 0}, label='Cond',
                     config={'conditionConfig': {'mode': 'expression', 'expression': expression}}),
        WorkflowNode(id='true_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='True',
                     config={'endMode': 'none'}),
        WorkflowNode(id='false_end', type=NodeType.END, position={'x': 0, 'y': 0}, label='False',
                     config={'endMode': 'none'}),
    ]
    edges = [
        WorkflowEdge(id='e1', source='start', source_port='default', target='cond', target_port='default'),
        WorkflowEdge(id='e2', source='cond', source_port='true', target='true_end', target_port='default',
                     edge_type=EdgeType.CONDITION),
        WorkflowEdge(id='e3', source='cond', source_port='false', target='false_end', target_port='default',
                     edge_type=EdgeType.CONDITION),
    ]
    definition = _make_definition(nodes, edges)
    stop_event = asyncio.Event()
    events = []
    async for event in execute_workflow(
        definition, stop_event,
        confirm_callback=lambda node_id, tc: True,
        initial_input=initial_input,
    ):
        events.append(event)
    return {e['nodeId'] for e in events if e['type'] == 'node_ended'}


@pytest.mark.parametrize('expression, initial_input, expected', [
    # {{input}} 模板写法应等价于变量 input
    ("{{input}} == 'yes'", 'yes', 'true_end'),
    ("{{input}} == 'yes'", 'no', 'false_end'),
    # 默认表达式模式：input == 'true'
    ("input == 'true'", 'true', 'true_end'),
    ("input == 'true'", 'false', 'false_end'),
    # JS 风格布尔别名：小写 true/false 不应抛 NameError
    ('true', 'anything', 'true_end'),
    ('false', 'anything', 'false_end'),
])
async def test_condition_expression_compat(expression, initial_input, expected):
    """条件表达式兼容性：{{input}} 模板别名、JS 风格布尔常量、字符串比较默认模式。"""
    ended = await _run_cond_events(expression, initial_input)
    assert expected in ended
    other = 'false_end' if expected == 'true_end' else 'true_end'
    assert other not in ended

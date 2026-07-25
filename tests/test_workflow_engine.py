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

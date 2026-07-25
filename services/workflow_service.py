from __future__ import annotations

import os
import json
import asyncio
from zaowu_paths import get_project_root
from workflow_engine.schema import (
    WorkflowDefinition, WorkflowNode, NodeType, WorkflowEdge, EdgeType,
    WorkflowExecutionConfig,
)
from workflow_engine.sse_helpers import _now_ms

_workflow_lock = asyncio.Lock()
BASE_DIR = get_project_root()
WORKFLOWS_FILE = os.path.join(BASE_DIR, 'workflows.json')


def _read_workflows_unlocked() -> dict:
    if not os.path.exists(WORKFLOWS_FILE):
        return {'workflows': []}
    with open(WORKFLOWS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def _write_workflows_unlocked(data: dict) -> None:
    tmp = WORKFLOWS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, WORKFLOWS_FILE)


def _dict_to_definition(item: dict) -> WorkflowDefinition:
    item = dict(item)
    ec = item.get('executionConfig') or item.get('execution_config') or {}
    execution_config = WorkflowExecutionConfig(
        auto_approve_writes=ec.get('autoApproveWrites', False),
        max_iterations=ec.get('maxIterations'),
        timeout_seconds=ec.get('timeoutSeconds'),
    )
    nodes = []
    for n in item.get('nodes', []):
        n = dict(n)
        nodes.append(WorkflowNode(
            id=n['id'],
            type=NodeType(n['type']),
            position=n.get('position', {'x': 0, 'y': 0}),
            label=n.get('label', ''),
            config=n.get('config', {}),
            retry_config=n.get('retryConfig') or n.get('retry_config'),
            input_mapping=n.get('inputMapping') or n.get('input_mapping', []),
            output_expose=n.get('outputExpose') or n.get('output_expose', []),
        ))
    edges = []
    for e in item.get('edges', []):
        e = dict(e)
        edges.append(WorkflowEdge(
            id=e['id'],
            source=e['source'],
            source_port=e.get('sourcePort') or e.get('source_port', 'default'),
            target=e['target'],
            target_port=e.get('targetPort') or e.get('target_port', 'default'),
            type=e.get('type', 'smoothstep'),
            edge_type=EdgeType(e.get('edgeType') or e.get('edge_type', 'data')),
            condition=e.get('condition'),
            data_contract=e.get('dataContract') or e.get('data_contract'),
            label=e.get('label'),
        ))
    return WorkflowDefinition(
        id=item['id'],
        name=item.get('name', ''),
        nodes=nodes,
        edges=edges,
        execution_config=execution_config,
        variables=item.get('variables', []),
        version=item.get('version', 1),
        description=item.get('description', ''),
        created_at=item.get('createdAt') or item.get('created_at', 0),
        updated_at=item.get('updatedAt') or item.get('updated_at', 0),
        last_run_at=item.get('lastRunAt') or item.get('last_run_at'),
        run_count=item.get('runCount') or item.get('run_count', 0),
    )


def _definition_to_dict(definition: WorkflowDefinition) -> dict:
    return {
        'id': definition.id,
        'name': definition.name,
        'description': definition.description,
        'version': definition.version,
        'nodes': [
            {
                'id': n.id,
                'type': n.type.value,
                'position': n.position,
                'label': n.label,
                'config': n.config,
                'retryConfig': n.retry_config,
                'inputMapping': n.input_mapping,
                'outputExpose': n.output_expose,
            }
            for n in definition.nodes
        ],
        'edges': [
            {
                'id': e.id,
                'source': e.source,
                'sourcePort': e.source_port,
                'target': e.target,
                'targetPort': e.target_port,
                'type': e.type,
                'edgeType': e.edge_type.value,
                'condition': e.condition,
                'dataContract': e.data_contract,
                'label': e.label,
            }
            for e in definition.edges
        ],
        'variables': definition.variables,
        'executionConfig': {
            'autoApproveWrites': definition.execution_config.auto_approve_writes,
            'maxIterations': definition.execution_config.max_iterations,
            'timeoutSeconds': definition.execution_config.timeout_seconds,
        },
        'createdAt': definition.created_at,
        'updatedAt': definition.updated_at,
        'lastRunAt': definition.last_run_at,
        'runCount': definition.run_count,
    }


async def load(workflow_id: str) -> WorkflowDefinition | None:
    async with _workflow_lock:
        data = await asyncio.to_thread(_read_workflows_unlocked)
    item = next((w for w in data['workflows'] if w['id'] == workflow_id), None)
    return _dict_to_definition(item) if item else None


async def save(definition: WorkflowDefinition) -> WorkflowDefinition:
    async with _workflow_lock:
        data = await asyncio.to_thread(_read_workflows_unlocked)
        existing = next((w for w in data['workflows'] if w['id'] == definition.id), None)
        definition.version = (existing.get('version', 0) + 1) if existing else 1
        definition.updated_at = _now_ms()
        if not existing:
            definition.created_at = definition.updated_at
        if existing:
            data['workflows'] = [w for w in data['workflows'] if w['id'] != definition.id]
        data['workflows'].append(_definition_to_dict(definition))
        await asyncio.to_thread(_write_workflows_unlocked, data)
    return definition


async def list_all() -> list[dict]:
    async with _workflow_lock:
        data = await asyncio.to_thread(_read_workflows_unlocked)
    return [
        {
            'id': w.get('id'),
            'name': w.get('name'),
            'updatedAt': w.get('updatedAt'),
            'version': w.get('version', 1),
        }
        for w in data.get('workflows', [])
    ]


async def delete(workflow_id: str) -> bool:
    async with _workflow_lock:
        data = await asyncio.to_thread(_read_workflows_unlocked)
        before = len(data['workflows'])
        data['workflows'] = [w for w in data['workflows'] if w['id'] != workflow_id]
        if len(data['workflows']) == before:
            return False
        await asyncio.to_thread(_write_workflows_unlocked, data)
    return True


async def list_runs(workflow_id: str) -> list[dict]:
    return []

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

_workflow_lock: asyncio.Lock | None = None
BASE_DIR = get_project_root()
WORKFLOWS_FILE = os.path.join(BASE_DIR, 'workflows.json')


def _get_workflow_lock() -> asyncio.Lock:
    global _workflow_lock
    if _workflow_lock is None:
        _workflow_lock = asyncio.Lock()
    return _workflow_lock


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


def _migrate_definition(raw: dict) -> dict:
    """迁移旧版本工作流定义到当前格式。在 _dict_to_definition 反序列化之前调用。"""
    raw = dict(raw)
    migration_log: list[dict] = []

    for node in raw.get('nodes', []):
        node = dict(node)
        config = dict(node.get('config', {}))
        node_type = node.get('type', '')

        # ── ConditionConfig 迁移 ──
        cc = config.get('conditionConfig')
        if isinstance(cc, dict):
            cc = dict(cc)
            old_mode = cc.get('mode', '')
            if old_mode == 'code':
                cc['mode'] = 'expression'
                migration_log.append({'type': 'condition_code_to_expression', 'nodeId': node['id']})
            elif old_mode == 'llm':
                cc['mode'] = 'prompt'
                if 'naturalLanguage' in cc and 'judgePrompt' not in cc:
                    cc['judgePrompt'] = cc['naturalLanguage']
                migration_log.append({'type': 'condition_llm_to_prompt', 'nodeId': node['id']})
            if 'modelConfig' not in cc:
                cc['modelConfig'] = {'providerId': '', 'modelId': ''}
            config['conditionConfig'] = cc

        # ── End 节点 outputFormat → endMode + logFormat ──
        if node_type == 'end' and 'outputFormat' in config and 'endMode' not in config:
            old_fmt = config.pop('outputFormat')
            config['endMode'] = 'log'
            fmt_map = {'text': 'txt', 'json': 'json', 'markdown': 'markdown'}
            config['logFormat'] = fmt_map.get(old_fmt, 'txt')
            migration_log.append({
                'type': 'end_outputFormat_migration',
                'nodeId': node['id'],
                'oldOutputFormat': old_fmt,
            })

        # ── LoopConfig 迁移 ──
        lc = config.get('loopConfig')
        if isinstance(lc, dict):
            lc = dict(lc)
            old_mode = lc.get('mode', '')
            # for/while → canvas
            if old_mode in ('for', 'while'):
                lc['mode'] = 'canvas'
                migration_log.append({
                    'type': 'loop_mode_migration',
                    'nodeId': node['id'],
                    'oldMode': old_mode,
                })

            # 删除已废弃字段并记录日志
            for deprecated_field in ('condition', 'circuitBreakerAction'):
                if deprecated_field in lc:
                    migration_log.append({
                        'type': f'loop_{deprecated_field}_removed',
                        'nodeId': node['id'],
                        'oldValue': lc.pop(deprecated_field),
                    })

            if 'iterateOver' in lc:
                migration_log.append({
                    'type': 'loop_iterateOver_removed',
                    'nodeId': node['id'],
                    'oldValue': lc.pop('iterateOver'),
                })

            if 'maxIterations' not in lc:
                lc['maxIterations'] = 10

            config['loopConfig'] = lc

        # ── 边端口迁移：Loop 旧端口 → 新端口 ──
        for edge in raw.get('edges', []):
            edge = dict(edge)
            source_port = edge.get('sourcePort', 'default')
            target_port = edge.get('targetPort', 'default')

            # sourcePort break/continue/output → out_end
            if source_port in ('break', 'continue'):
                migration_log.append({
                    'type': 'loop_source_port_migration',
                    'edgeId': edge['id'],
                    'oldPort': source_port,
                    'newPort': 'out_end',
                })
                edge['sourcePort'] = 'out_end'
            elif source_port == 'output':
                migration_log.append({
                    'type': 'loop_source_port_migration',
                    'edgeId': edge['id'],
                    'oldPort': source_port,
                    'newPort': 'out_end',
                })
                edge['sourcePort'] = 'out_end'

            # targetPort items → in
            if target_port == 'items':
                migration_log.append({
                    'type': 'loop_target_port_migration',
                    'edgeId': edge['id'],
                    'oldPort': target_port,
                    'newPort': 'in',
                })
                edge['targetPort'] = 'in'

        node['config'] = config

    # ── 移除 router 节点和 continue 边 ──
    original_nodes = raw.get('nodes', [])
    router_ids = {n['id'] for n in original_nodes if n.get('type') == 'router'}
    if router_ids:
        raw['nodes'] = [n for n in original_nodes if n.get('type') != 'router']
        raw['edges'] = [e for e in raw.get('edges', []) if e['source'] not in router_ids and e['target'] not in router_ids]
        for rid in router_ids:
            migration_log.append({'type': 'router_node_removed', 'nodeId': rid})

    raw['edges'] = [e for e in raw.get('edges', []) if e.get('edgeType', e.get('edge_type', 'data')) not in ('break', 'continue')]

    if migration_log:
        raw['_migration_log'] = migration_log

    return raw


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
    async with _get_workflow_lock():
        data = await asyncio.to_thread(_read_workflows_unlocked)
    item = next((w for w in data['workflows'] if w['id'] == workflow_id), None)
    if item is None:
        return None
    item = _migrate_definition(item)
    return _dict_to_definition(item)


async def save(definition: WorkflowDefinition) -> WorkflowDefinition:
    async with _get_workflow_lock():
        data = await asyncio.to_thread(_read_workflows_unlocked)
        existing = next((w for w in data['workflows'] if w['id'] == definition.id), None)
        definition.version = (existing.get('version', 0) + 1) if existing else 1
        definition.updated_at = _now_ms()
        if not existing:
            definition.created_at = definition.updated_at
        if existing:
            data['workflows'] = [w for w in data['workflows'] if w['id'] != definition.id]
        # 保存前先做迁移（确保新创建的工作流也经过规范化）
        raw = _definition_to_dict(definition)
        raw = _migrate_definition(raw)
        raw.pop('_migration_log', None)
        data['workflows'].append(raw)
        await asyncio.to_thread(_write_workflows_unlocked, data)
    return definition


async def list_all() -> list[dict]:
    async with _get_workflow_lock():
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
    async with _get_workflow_lock():
        data = await asyncio.to_thread(_read_workflows_unlocked)
        before = len(data['workflows'])
        data['workflows'] = [w for w in data['workflows'] if w['id'] != workflow_id]
        if len(data['workflows']) == before:
            return False
        await asyncio.to_thread(_write_workflows_unlocked, data)
    return True


async def list_runs(workflow_id: str) -> list[dict]:
    return []


async def export_to_file(workflow_id: str, file_path: str) -> None:
    definition = await load(workflow_id)
    if not definition:
        raise ValueError('workflow not found')
    data = _definition_to_dict(definition)
    data = _migrate_definition(data)
    data.pop('_migration_log', None)
    async with _get_workflow_lock():
        await asyncio.to_thread(_write_json_file, file_path, data)


def _write_json_file(file_path: str, data: dict) -> None:
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

from __future__ import annotations

import os
import json
import asyncio
from typing import Any
from zaowu_paths import get_project_root
from workflow_engine.schema import (
    WorkflowDefinition, WorkflowNode, NodeType, WorkflowEdge, EdgeType,
    WorkflowExecutionConfig,
)
from workflow_engine.sse_helpers import _now_ms

_workflow_lock: asyncio.Lock | None = None
_runs_lock: asyncio.Lock | None = None
BASE_DIR = get_project_root()
WORKFLOWS_FILE = os.path.join(BASE_DIR, 'workflows.json')
WORKFLOW_RUNS_FILE = os.path.join(BASE_DIR, 'workflow_runs.json')


def _normalize_edge_dict(edge: dict | WorkflowEdge | Any) -> dict | None:
    """把 dict 或 WorkflowEdge 对象归一化为原始 edge dict。"""
    if isinstance(edge, WorkflowEdge):
        return {
            'id': edge.id,
            'source': edge.source,
            'sourcePort': edge.source_port,
            'target': edge.target,
            'targetPort': edge.target_port,
            'type': edge.type,
            'edgeType': edge.edge_type.value,
            'condition': edge.condition,
            'dataContract': edge.data_contract,
            'label': edge.label,
        }
    if isinstance(edge, dict):
        normalized = dict(edge)
        normalized.setdefault('id', '')
        normalized.setdefault('source', '')
        normalized.setdefault('sourcePort', normalized.get('source_port', 'default'))
        normalized.setdefault('target', '')
        normalized.setdefault('targetPort', normalized.get('target_port', 'default'))
        normalized.setdefault('type', 'smoothstep')
        normalized.setdefault('edgeType', normalized.get('edge_type', 'data'))
        return normalized
    return None


def _get_workflow_lock() -> asyncio.Lock:
    global _workflow_lock
    if _workflow_lock is None:
        _workflow_lock = asyncio.Lock()
    return _workflow_lock


def _get_runs_lock() -> asyncio.Lock:
    global _runs_lock
    if _runs_lock is None:
        _runs_lock = asyncio.Lock()
    return _runs_lock


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

    nodes = list(raw.get('nodes', []))
    for i, node in enumerate(nodes):
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
            # 移除 mode 字段（for/while/canvas 均不再使用）
            if old_mode:
                migration_log.append({
                    'type': 'loop_mode_removed',
                    'nodeId': node['id'],
                    'oldMode': old_mode,
                })
                lc.pop('mode', None)

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

        node['config'] = config
        nodes[i] = node

    raw['nodes'] = nodes

    # ── 边端口迁移：Loop 旧端口 → 新端口 ──
    edges = list(raw.get('edges', []))
    for i, edge in enumerate(edges):
        edge = dict(edge)
        source_port = edge.get('sourcePort', 'default')
        target_port = edge.get('targetPort', 'default')

        # sourcePort break/continue/output → out_end
        if source_port in ('break', 'continue', 'output'):
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

        edges[i] = edge

    raw['edges'] = edges

    # ── 把旧 bodyNodeIds / bodyEdges 提升为真实工作流边 ──
    node_ids = {n['id'] for n in raw.get('nodes', [])}
    used_edge_ids = {e['id'] for e in edges}
    promoted_loop_ids: set[str] = set()

    for node in raw.get('nodes', []):
        if node.get('type') != 'loop':
            continue
        loop_id = node['id']
        lc = (node.get('config') or {}).get('loopConfig') or {}
        body_node_ids = lc.get('bodyNodeIds', []) or []
        body_edges = lc.get('bodyEdges', []) or []

        if not body_node_ids and not body_edges:
            continue

        # 幂等：如果已经存在 loop.body 边，跳过并视为已迁移
        if any(e.get('source') == loop_id and e.get('sourcePort') == 'body' for e in edges):
            promoted_loop_ids.add(loop_id)
            continue

        # 归一化并校验 bodyEdges
        normalized_body_edges: list[dict] = []
        for idx, edge in enumerate(body_edges):
            norm = _normalize_edge_dict(edge)
            if not norm:
                migration_log.append({
                    'type': 'loop_body_edge_invalid',
                    'nodeId': loop_id,
                    'index': idx,
                })
                continue
            if norm['source'] not in node_ids or norm['target'] not in node_ids:
                migration_log.append({
                    'type': 'loop_body_edge_node_missing',
                    'nodeId': loop_id,
                    'edgeId': norm['id'],
                })
                continue
            base_id = norm['id'] or f'edge-loop-{loop_id}-{idx}'
            edge_id = base_id
            suffix = 0
            while edge_id in used_edge_ids:
                suffix += 1
                edge_id = f'{base_id}-{suffix}'
            norm['id'] = edge_id
            used_edge_ids.add(edge_id)
            normalized_body_edges.append(norm)

        # 计算 bodyNodeIds 中节点在 bodyEdges 内的入度
        in_degree = {nid: 0 for nid in body_node_ids}
        for edge in normalized_body_edges:
            if edge['target'] in in_degree:
                in_degree[edge['target']] += 1

        # 筛选入口节点：在 bodyEdges 里出现过且入度为 0
        candidate_entries = [
            nid for nid in body_node_ids
            if in_degree.get(nid, 0) == 0
            and (any(e['source'] == nid for e in normalized_body_edges)
                 or any(e['target'] == nid for e in normalized_body_edges))
        ]

        # 最常见的旧形态：循环体里只有一个节点，bodyEdges 为空
        if not candidate_entries and not normalized_body_edges and body_node_ids:
            candidate_entries = [body_node_ids[0]]
            migration_log.append({
                'type': 'loop_single_node_body_promoted',
                'nodeId': loop_id,
                'entryId': candidate_entries[0],
            })

        if not candidate_entries:
            migration_log.append({
                'type': 'loop_no_entry_node',
                'nodeId': loop_id,
            })
            # 无法安全迁移，保留 bodyNodeIds / bodyEdges 供人工修复
            continue

        entry_id = candidate_entries[0]
        if len(candidate_entries) > 1:
            migration_log.append({
                'type': 'loop_multiple_entries_skipped',
                'nodeId': loop_id,
                'kept': entry_id,
                'skipped': candidate_entries[1:],
            })

        body_edge_id = f'edge-loop-{loop_id}-body-entry'
        suffix = 0
        while body_edge_id in used_edge_ids:
            suffix += 1
            body_edge_id = f'edge-loop-{loop_id}-body-entry-{suffix}'
        used_edge_ids.add(body_edge_id)
        edges.append({
            'id': body_edge_id,
            'source': loop_id,
            'sourcePort': 'body',
            'target': entry_id,
            'targetPort': 'default',
            'type': 'smoothstep',
            'edgeType': 'data',
        })
        edges.extend(normalized_body_edges)
        promoted_loop_ids.add(loop_id)
        migration_log.append({
            'type': 'loop_body_edges_promoted',
            'nodeId': loop_id,
            'edgeCount': len(normalized_body_edges),
        })

    # ── 二次迁移：out_end / output → out ──
    for i, edge in enumerate(edges):
        edge = dict(edge)
        source_port = edge.get('sourcePort', 'default')
        if source_port in ('out_end', 'output'):
            migration_log.append({
                'type': 'loop_source_port_to_out',
                'edgeId': edge['id'],
                'oldPort': source_port,
            })
            edge['sourcePort'] = 'out'
        edges[i] = edge

    raw['edges'] = edges

    # ── 移除 router 节点和 continue 边 ──
    router_ids = {n['id'] for n in raw.get('nodes', []) if n.get('type') == 'router'}
    if router_ids:
        raw['nodes'] = [n for n in raw.get('nodes', []) if n.get('type') != 'router']
        raw['edges'] = [e for e in raw.get('edges', []) if e['source'] not in router_ids and e['target'] not in router_ids]
        for rid in router_ids:
            migration_log.append({'type': 'router_node_removed', 'nodeId': rid})

    raw['edges'] = [e for e in raw.get('edges', []) if e.get('edgeType', e.get('edge_type', 'data')) not in ('break', 'continue')]

    # ── 最终清理：LoopConfig 只保留 maxIterations ──
    # 成功迁移的 Loop 清除旧字段；无法确定入口的 Loop 保留 bodyNodeIds / bodyEdges
    # 供人工修复，避免用户打开旧工作流再保存时丢失循环体数据。
    nodes = list(raw.get('nodes', []))
    for i, node in enumerate(nodes):
        node = dict(node)
        config = dict(node.get('config', {}))
        lc = config.get('loopConfig')
        if isinstance(lc, dict):
            max_iter = lc.get('maxIterations', 10)
            keep_old_body = node['id'] not in promoted_loop_ids
            allowed_fields = {'maxIterations'}
            if keep_old_body:
                allowed_fields.update({'bodyNodeIds', 'bodyEdges'})
            removed_fields = [k for k in lc.keys() if k not in allowed_fields]
            if removed_fields:
                migration_log.append({
                    'type': 'loop_config_simplified',
                    'nodeId': node['id'],
                    'removedFields': removed_fields,
                })
            new_lc: dict[str, Any] = {'maxIterations': max_iter}
            if keep_old_body:
                if lc.get('bodyNodeIds'):
                    new_lc['bodyNodeIds'] = lc['bodyNodeIds']
                if lc.get('bodyEdges'):
                    new_lc['bodyEdges'] = lc['bodyEdges']
            config['loopConfig'] = new_lc
        node['config'] = config
        nodes[i] = node
    raw['nodes'] = nodes

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
        if existing:
            # lastRunAt / runCount 由 touch_run_metadata 维护、createdAt 由系统管理，
            # 保存时一律保留服务端值，避免被客户端陈旧数据覆盖——否则运行后再保存会让
            # lastRunAt 倒退回运行前、runCount 卡在初始值+1，破坏 Launcher 的「最近」排序。
            definition.last_run_at = existing.get('lastRunAt')
            definition.run_count = existing.get('runCount', 0)
            definition.created_at = existing.get('createdAt') or definition.updated_at
            data['workflows'] = [w for w in data['workflows'] if w['id'] != definition.id]
        else:
            definition.created_at = definition.updated_at
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
            'description': w.get('description', ''),
            'createdAt': w.get('createdAt'),
            'updatedAt': w.get('updatedAt'),
            'lastRunAt': w.get('lastRunAt'),
            'version': w.get('version', 1),
            'runCount': w.get('runCount', 0),
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


async def touch_run_metadata(workflow_id: str, run_time: int) -> None:
    """更新工作流最近运行时间和运行次数。"""
    async with _get_workflow_lock():
        data = await asyncio.to_thread(_read_workflows_unlocked)
        for w in data.get('workflows', []):
            if w.get('id') == workflow_id:
                w['lastRunAt'] = run_time
                w['runCount'] = w.get('runCount', 0) + 1
                break
        await asyncio.to_thread(_write_workflows_unlocked, data)


def _read_runs_unlocked() -> dict:
    if not os.path.exists(WORKFLOW_RUNS_FILE):
        return {'runs': []}
    with open(WORKFLOW_RUNS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def _write_runs_unlocked(data: dict) -> None:
    tmp = WORKFLOW_RUNS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, WORKFLOW_RUNS_FILE)


async def persist_run_start(workflow_id: str, run_id: str, start_time: int,
                            initial_input: str = '') -> None:
    """在 wf_started 时插入一条 status='running' 的运行记录。"""
    record = {
        'runId': run_id,
        'workflowId': workflow_id,
        'status': 'running',
        'startTime': start_time,
        'endTime': None,
        'totalTokens': 0,
        'error': None,
        'initialInput': initial_input,
    }
    async with _get_runs_lock():
        data = await asyncio.to_thread(_read_runs_unlocked)
        data['runs'].append(record)
        await asyncio.to_thread(_write_runs_unlocked, data)


async def persist_run_end(workflow_id: str, run_id: str, status: str,
                          end_time: int, total_tokens: int = 0,
                          error: str | None = None) -> None:
    """在 wf_completed/wf_errored 时更新对应运行记录。"""
    async with _get_runs_lock():
        data = await asyncio.to_thread(_read_runs_unlocked)
        for r in data['runs']:
            if r.get('runId') == run_id and r.get('workflowId') == workflow_id:
                r['status'] = status
                r['endTime'] = end_time
                r['totalTokens'] = total_tokens
                r['error'] = error
                break
        await asyncio.to_thread(_write_runs_unlocked, data)


async def list_runs(workflow_id: str, limit: int = 50) -> list[dict]:
    """返回指定工作流的运行记录（按 startTime 倒序）。"""
    async with _get_runs_lock():
        data = await asyncio.to_thread(_read_runs_unlocked)
    runs = [r for r in data.get('runs', []) if r.get('workflowId') == workflow_id]
    runs.sort(key=lambda r: r.get('startTime', 0), reverse=True)
    return runs[:limit]


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

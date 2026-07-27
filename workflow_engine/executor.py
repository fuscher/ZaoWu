from __future__ import annotations

import asyncio
import copy
import json
import os
import time
from collections import deque
from typing import AsyncGenerator, Callable

from workflow_engine.schema import (
    WorkflowDefinition, WorkflowNode, NodeType, WorkflowExecutionConfig,
)
from workflow_engine.context import ExecutionContext, NodeContext, _resolve_inputs
from workflow_engine.node_registry import NodeRegistry
from workflow_engine.sse_helpers import (
    _generate_run_id, _now_ms,
    _sse_wf_started, _sse_wf_errored, _sse_node_errored, _sse_wf_completed,
)


def _get_active_project_paths() -> list[str]:
    paths = []
    try:
        from routes.explorer import read_projects
        projects = read_projects()
        for p in projects:
            p_path = p.get('path', '')
            if not p_path or not os.path.isdir(p_path):
                continue
            zaowu_path = os.path.join(p_path, '.zaowu')
            if os.path.exists(zaowu_path):
                try:
                    with open(zaowu_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                        if meta.get('archived', False):
                            continue
                except (json.JSONDecodeError, IOError):
                    pass
            paths.append(os.path.realpath(p_path))
    except Exception:
        pass

    if not paths:
        home_zaowu = os.path.join(os.path.expanduser('~'), '.ZaoWu')
        os.makedirs(home_zaowu, exist_ok=True)
        paths.append(home_zaowu)
    return paths


class WorkflowExecutor:
    def __init__(self, definition: WorkflowDefinition):
        self.definition = definition
        self._graph: dict[str, list[str]] = {}
        self._in_degree: dict[str, int] = {}
        self._build_graph()

    def _build_graph(self):
        for node in self.definition.nodes:
            self._graph[node.id] = []
            self._in_degree[node.id] = 0
        for edge in self.definition.edges:
            self._graph[edge.source].append(edge.target)
            self._in_degree[edge.target] += 1

    def _get_node(self, node_id: str) -> WorkflowNode:
        for n in self.definition.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f'节点 {node_id} 不存在')

    def _collect_body_node_ids(self) -> set[str]:
        body_ids: set[str] = set()
        for node in self.definition.nodes:
            if node.type == NodeType.LOOP:
                cfg = (node.config.get('loopConfig') or {})
                body_ids.update(cfg.get('bodyNodeIds') or [])
        return body_ids

    def validate(self) -> list[str]:
        errors = []
        starts = [n for n in self.definition.nodes if n.type == NodeType.START]
        if len(starts) != 1:
            errors.append(f"需要恰好 1 个开始节点，当前 {len(starts)} 个")
        ends = [n for n in self.definition.nodes if n.type == NodeType.END]
        if not ends:
            errors.append("需要至少 1 个结束节点")

        body_node_ids = self._collect_body_node_ids()

        all_connected = set()
        for edge in self.definition.edges:
            all_connected.add(edge.source)
            all_connected.add(edge.target)
        for node in self.definition.nodes:
            if node.id in body_node_ids:
                continue
            if node.id not in all_connected:
                errors.append(f"节点 '{node.label}' 未连接到工作流")
        try:
            self._topological_sort()
        except ValueError:
            errors.append("工作流中存在环路")
        return errors

    def _topological_sort(self) -> list[str]:
        in_degree = dict(self._in_degree)
        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        result = []
        while queue:
            node_id = queue.popleft()
            result.append(node_id)
            for successor in self._graph[node_id]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)
        if len(result) != len(self._in_degree):
            raise ValueError("Graph contains a cycle")
        return result


async def execute_workflow(
    definition: WorkflowDefinition,
    stop_event: asyncio.Event,
    confirm_callback: Callable,
    run_id: str | None = None,
    initial_input: str = '',
    register_pending_callback: Callable[[str, str, dict], None] | None = None,
) -> AsyncGenerator[dict, None]:
    run_id = run_id or _generate_run_id()
    executor = WorkflowExecutor(definition)
    errors = executor.validate()
    if errors:
        yield _sse_wf_errored(definition.id, run_id, '; '.join(errors))
        return

    ctx = ExecutionContext(
        definition.id,
        run_id,
        execution_config=definition.execution_config,
        project_paths=_get_active_project_paths(),
        initial_input=initial_input,
        definition=definition,
    )
    yield _sse_wf_started(ctx, _now_ms())

    total_tokens = 0
    start_ms = _now_ms()
    timeout_ms = (ctx.execution_config.timeout_seconds or 0) * 1000
    topology = executor._topological_sort()
    node_handlers = NodeRegistry.get_handlers()

    active_edges: set[str] = {e.id for e in definition.edges}
    body_node_ids: set[str] = executor._collect_body_node_ids()

    # 顺序执行状态：跟踪 Start 节点的 orderedTargets 进度
    completed_node_ids: set[str] = set()
    ordered_targets_list: list[str] | None = None
    ordered_idx: int = 0
    start_node_id: str | None = None

    cursor = 0  # topology 遍历指针

    MAX_PASSES = max(len(topology) * 2, 100)

    try:
        for _pass in range(MAX_PASSES):
            if stop_event.is_set():
                yield _sse_wf_errored(ctx.workflow_id, ctx.run_id, '用户已停止')
                return

            made_progress = False

            while cursor < len(topology):
                node_id = topology[cursor]
                cursor += 1

                if node_id in completed_node_ids:
                    continue
                if timeout_ms and _now_ms() - start_ms > timeout_ms:
                    yield _sse_wf_errored(
                        ctx.workflow_id, ctx.run_id, f'工作流执行超时（{ctx.execution_config.timeout_seconds}s）')
                    return
                if stop_event.is_set():
                    yield _sse_wf_errored(ctx.workflow_id, ctx.run_id, '用户已停止')
                    return

                node_def = executor._get_node(node_id)

                if node_id in body_node_ids:
                    continue

                if node_def.type != NodeType.START:
                    active_incoming = [
                        e for e in definition.edges
                        if e.target == node_id and e.id in active_edges
                    ]
                    if not active_incoming:
                        continue

                handler_cls = node_handlers.get(node_def.type.value)
                if not handler_cls:
                    continue

                handler = handler_cls(node_def)
                ctx_node = NodeContext(node_id)
                ctx.node_contexts[node_id] = ctx_node
                ctx_node.inputs = await _resolve_inputs(node_def, definition.edges, ctx, active_edges)

                retry_config = node_def.retry_config
                max_retries = (retry_config.get('maxRetries') or 0) if retry_config else 0
                retry_delay = (retry_config.get('retryDelay') or 1000) if retry_config else 1000
                backoff = (retry_config.get('backoffMultiplier') or 1.0) if retry_config else 1.0
                on_exhausted = (retry_config.get('onRetryExhausted') or 'error') if retry_config else 'error'
                fallback_model = retry_config.get('fallbackModel') if retry_config else None

                node_done = False
                for attempt in range(max_retries + 1):
                    try:
                        async for event in handler.execute(ctx, ctx_node, confirm_callback, stop_event):
                            if stop_event.is_set():
                                yield _sse_wf_errored(ctx.workflow_id, ctx.run_id, '用户已停止')
                                return
                            if (register_pending_callback
                                    and isinstance(event, dict)
                                    and event.get('type') == 'node_requires_confirmation'):
                                register_pending_callback(ctx.workflow_id, node_id, event.get('toolCall') or {})
                            yield event

                        total_tokens += ctx_node.tokens_in + ctx_node.tokens_out
                        _activate_downstream_edges(node_def, ctx_node, definition, active_edges)
                        completed_node_ids.add(node_id)
                        made_progress = True
                        node_done = True

                        # 捕获 Start 节点的 ordered 信息
                        if node_def.type == NodeType.START:
                            ordered = ctx_node.outputs.get('__ordered__')
                            if ordered and len(ordered) > 1:
                                ordered_targets_list = list(ordered)
                                ordered_idx = 0
                                start_node_id = node_id

                        break
                    except Exception as e:
                        if attempt < max_retries:
                            yield _sse_node_errored(ctx, ctx_node, str(e), attempt + 1)
                            await asyncio.sleep((retry_delay / 1000) * (backoff ** attempt))
                        else:
                            yield _sse_node_errored(ctx, ctx_node, str(e), -1)
                            if on_exhausted == 'fallback' and fallback_model:
                                cfg = copy.deepcopy(handler.node_def.config)
                                handler.node_def.config = cfg
                                if not cfg.get('slots'):
                                    cfg['slots'] = {}
                                cfg['slots']['model'] = fallback_model
                                try:
                                    async for event in handler.execute(ctx, ctx_node, confirm_callback, stop_event):
                                        if (register_pending_callback
                                                and isinstance(event, dict)
                                                and event.get('type') == 'node_requires_confirmation'):
                                            register_pending_callback(ctx.workflow_id, node_id, event.get('toolCall') or {})
                                        yield event
                                    total_tokens += ctx_node.tokens_in + ctx_node.tokens_out
                                    _activate_downstream_edges(node_def, ctx_node, definition, active_edges)
                                    completed_node_ids.add(node_id)
                                    made_progress = True
                                    node_done = True
                                    break
                                except Exception as fe:
                                    yield _sse_wf_errored(
                                        ctx.workflow_id, ctx.run_id, f'节点 {node_id} fallback 执行失败: {fe}')
                                    return
                            yield _sse_wf_errored(ctx.workflow_id, ctx.run_id, f'节点 {node_id} 执行失败: {e}')
                            return

                if not node_done:
                    return

            # 本轮 topology 遍历结束 —— 检查是否有待激活的 ordered 分支
            if not made_progress:
                if (ordered_targets_list and start_node_id
                        and ordered_idx < len(ordered_targets_list) - 1):
                    ordered_idx += 1
                    next_target = ordered_targets_list[ordered_idx]
                    for e in definition.edges:
                        if e.source == start_node_id and e.target == next_target:
                            active_edges.add(e.id)
                            made_progress = True
                    if made_progress:
                        cursor = 0  # 重新遍历 topology
                        continue
                break  # 真正结束

            # 本轮有进展 → 重置指针继续（topology 中可能有新节点因 active_edges 变化而变为可执行）
            cursor = 0

        yield _sse_wf_completed(ctx, total_tokens)
    except Exception as e:
        yield _sse_wf_errored(ctx.workflow_id, ctx.run_id, f'工作流异常终止: {e}')


def _activate_downstream_edges(node_def, ctx_node, definition, active_edges):
    if node_def.type == NodeType.CONDITION:
        selected = ctx_node.outputs.get('branch', 'true')
        for e in definition.edges:
            if e.source == node_def.id and e.source_port != selected:
                active_edges.discard(e.id)
    elif node_def.type == NodeType.LOOP:
        control = ctx_node.outputs.get('control', 'output')
        keep = {'output', control}
        # 新 Loop 的 out_end 端口始终保留
        if 'out_end' in (ctx_node.outputs or {}):
            keep.add('out_end')
        for e in definition.edges:
            if e.source == node_def.id and e.source_port not in keep:
                active_edges.discard(e.id)
    elif node_def.type == NodeType.START:
        # Start 顺序执行模式：执行后按 orderedTargets 顺序，
        # 先只激活第一个出边，其余边暂时丢弃，由主循环逐条激活
        ordered = ctx_node.outputs.get('__ordered__')
        if ordered and len(ordered) > 1:
            first_target = ordered[0]
            for e in definition.edges:
                if e.source == node_def.id and e.target != first_target:
                    active_edges.discard(e.id)

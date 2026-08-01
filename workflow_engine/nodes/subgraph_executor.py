from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from workflow_engine.context import NodeContext, _resolve_inputs
from workflow_engine.schema import NodeType, WorkflowEdge, WorkflowNode
from workflow_engine.sse_helpers import _sse_edge_crossed

logger = logging.getLogger(__name__)


def discover_loop_body(
    loop_id: str,
    edges: list[WorkflowEdge],
    nodes: list[WorkflowNode],
) -> tuple[set[str], list[WorkflowEdge]]:
    """发现 Loop 节点循环体包含的节点与内部边。

    入口：所有 source == loop_id && source_port == 'body' 的边指向的 target 节点。
    从入口沿出边 BFS 扩散；遇到嵌套 Loop 节点时只沿其 'out' 边扩散，不沿 'body' 边扩散。
    遇到 End 节点或 Loop.out 下游可达的节点时停止扩散，避免把共享下游链吞进循环体。
    返回 (body_node_ids, body_edges)。
    """
    node_by_id = {n.id: n for n in nodes}
    body_node_ids: set[str] = set()
    queue: deque[str] = deque()

    # 收集入口节点
    for edge in edges:
        if edge.source == loop_id and edge.source_port == 'body':
            entry_id = edge.target
            if entry_id in node_by_id and entry_id not in body_node_ids:
                body_node_ids.add(entry_id)
                queue.append(entry_id)

    # 计算 Loop.out 下游可达的节点：这些节点属于循环体外部，不应被 body BFS 吞并
    out_reachable: set[str] = set()
    out_queue: deque[str] = deque()
    for edge in edges:
        if edge.source == loop_id and edge.source_port == 'out':
            if edge.target in node_by_id:
                out_queue.append(edge.target)
    while out_queue:
        cur = out_queue.popleft()
        if cur in out_reachable:
            continue
        out_reachable.add(cur)
        for edge in edges:
            if edge.source == cur:
                nxt = edge.target
                if nxt in node_by_id and nxt not in out_reachable:
                    out_queue.append(nxt)

    while queue:
        cur_id = queue.popleft()
        cur_node = node_by_id.get(cur_id)
        if not cur_node:
            continue

        # 嵌套 Loop：只沿 out 边继续；body 边交给内层 Loop 自己处理
        if cur_node.type == NodeType.LOOP:
            out_edges = [e for e in edges if e.source == cur_id and e.source_port == 'out']
            for edge in out_edges:
                nxt = edge.target
                if nxt in node_by_id and nxt not in body_node_ids and nxt != loop_id:
                    body_node_ids.add(nxt)
                    queue.append(nxt)
            continue

        # 普通节点：沿全部出边扩散，但跳过 Loop.out 下游可达节点。
        # 共享下游节点（如 End）应归主执行器驱动，避免被循环体吞并。
        for edge in edges:
            if edge.source != cur_id:
                continue
            nxt = edge.target
            if nxt not in node_by_id:
                logger.warning(
                    'Loop %s 的循环体边 %s 指向不存在的节点 %s，忽略该边',
                    loop_id, edge.id, nxt,
                )
                continue
            if nxt == loop_id:
                # 避免回边把 Loop 自身或其 body 下游吞掉
                continue
            if nxt in out_reachable:
                continue
            if nxt not in body_node_ids:
                body_node_ids.add(nxt)
                queue.append(nxt)

    # 内部边：两端都在循环体内的边
    body_edges = [
        e for e in edges
        if e.source in body_node_ids and e.target in body_node_ids
    ]
    return body_node_ids, body_edges


class SubgraphExecutor:
    """在 Loop 内部执行一段子图，支持内部边、条件分支、多出口聚合。

    用法：
        subgraph = SubgraphExecutor(loop_node_def, parent_ctx)
        feedback, control = await subgraph.run(
            initial_input, iteration, confirm_callback, stop_event, queue,
        )

    返回值：
        feedback: dict | None — 汇总本轮出口节点的 outputs['default']
        control: str | None — 'end' / 'stopped' / None
    """

    def __init__(
        self,
        loop_node_def: WorkflowNode,
        parent_ctx: Any,
    ):
        self.loop_node_def = loop_node_def
        self.parent_ctx = parent_ctx
        self.loop_id = loop_node_def.id
        self.definition = parent_ctx.definition
        self.nodes: list[WorkflowNode] = list(self.definition.nodes) if self.definition else []
        self.edges: list[WorkflowEdge] = list(self.definition.edges) if self.definition else []
        self.body_node_ids, self.body_edges = discover_loop_body(
            self.loop_id, self.edges, self.nodes,
        )
        self._node_by_id = {n.id: n for n in self.nodes}

    async def run(
        self,
        initial_input: Any,
        iteration: int,
        confirm_callback: Any,
        stop_event: Any,
        queue: asyncio.Queue | None = None,
    ) -> tuple[dict | None, str | None]:
        """执行子图一轮，返回 (feedback, control)。"""
        if not self.body_node_ids:
            return ({'default': initial_input}, None)

        # 1. 构建子图拓扑
        graph: dict[str, list[str]] = {}
        in_degree: dict[str, int] = {}
        for node_id in self.body_node_ids:
            graph[node_id] = []
            in_degree[node_id] = 0
        for edge in self.body_edges:
            graph[edge.source].append(edge.target)
            in_degree[edge.target] += 1

        # 2. 入口节点：Loop.body 边指向的节点，或子图内入度为 0 的节点
        entry_ids = {
            e.target for e in self.edges
            if e.source == self.loop_id and e.source_port == 'body'
        } & self.body_node_ids
        if not entry_ids:
            entry_ids = {nid for nid, deg in in_degree.items() if deg == 0}

        # 3. 拓扑排序并检测环
        sorted_ids = self._topological_sort(graph, in_degree)
        if len(sorted_ids) != len(self.body_node_ids):
            raise ValueError(f'Loop {self.loop_id} 的循环体内部存在环路')

        # 4. 每轮重置活跃边，避免 Condition 分支门控跨迭代污染
        active_edges: set[str] = {e.id for e in self.body_edges}

        # 5. 执行（局部导入避免循环依赖）
        from workflow_engine.node_registry import NodeRegistry
        handlers = NodeRegistry.get_handlers()
        executed_this_round: set[str] = set()

        # 清理本轮可能用到的 body 节点上下文，避免上一轮残留污染
        for nid in self.body_node_ids:
            self.parent_ctx.node_contexts.pop(nid, None)

        for nid in sorted_ids:
            if stop_event and stop_event.is_set():
                return (None, 'stopped')

            node_def = self._node_by_id.get(nid)
            if not node_def:
                continue

            handler_cls = handlers.get(node_def.type.value)
            if not handler_cls:
                continue

            # 注入输入：与主执行器保持一致，按端口归桶为 list。
            # 多出口反馈本身已是 list，避免再次包装成 [[...]]。
            if nid in entry_ids:
                inputs: dict[str, Any] = {
                    'default': initial_input if isinstance(initial_input, list) else [initial_input]
                }
            else:
                inputs = await _resolve_inputs(
                    node_def, self.body_edges, self.parent_ctx, active_edges,
                )
                # 任一活跃入边即可触发；无活跃入边则跳过
                if not inputs:
                    continue

            handler = handler_cls(node_def)
            sub_ctx = NodeContext(nid)
            sub_ctx.inputs = inputs
            self.parent_ctx.node_contexts[nid] = sub_ctx
            executed_this_round.add(nid)

            async for event in handler.execute(
                self.parent_ctx, sub_ctx, confirm_callback, stop_event,
            ):
                if event and queue is not None:
                    await queue.put(event)

            # Condition 分支门控
            if node_def.type == NodeType.CONDITION:
                selected = sub_ctx.outputs.get('branch', 'true')
                for edge in self.body_edges:
                    if edge.source == nid and edge.source_port != selected:
                        active_edges.discard(edge.id)

            # End / 嵌套 Loop 透传的终止信号
            outs = sub_ctx.outputs or {}
            if node_def.type == NodeType.END or outs.get('__control__') == 'end':
                return (None, 'end')

            # 对本轮仍活跃的出边发 edge_crossed，驱动前端边流动动画
            if queue is not None:
                for edge in self.body_edges:
                    if edge.source == nid and edge.id in active_edges:
                        await queue.put(_sse_edge_crossed(
                            self.parent_ctx, edge.source, edge.target,
                        ))

        # 6. 汇总出口节点输出：本轮执行过 且 无活跃出边
        feedback_parts: list[Any] = []
        for nid in sorted_ids:
            if nid not in executed_this_round:
                continue
            has_active_out = any(
                edge.source == nid and edge.id in active_edges
                for edge in self.body_edges
            )
            if has_active_out:
                continue
            sub_ctx = self.parent_ctx.node_contexts.get(nid)
            if sub_ctx and sub_ctx.outputs:
                raw = sub_ctx.outputs.get('default')
                if raw is not None:
                    feedback_parts.append(raw)

        if not feedback_parts:
            return ({'default': initial_input}, None)

        merged = feedback_parts[0] if len(feedback_parts) == 1 else feedback_parts
        return ({'default': merged}, None)

    def _topological_sort(
        self,
        graph: dict[str, list[str]],
        in_degree: dict[str, int],
    ) -> list[str]:
        deg = dict(in_degree)
        queue = deque([nid for nid, d in deg.items() if d == 0])
        result: list[str] = []
        while queue:
            nid = queue.popleft()
            result.append(nid)
            for succ in graph.get(nid, []):
                deg[succ] -= 1
                if deg[succ] == 0:
                    queue.append(succ)
        return result

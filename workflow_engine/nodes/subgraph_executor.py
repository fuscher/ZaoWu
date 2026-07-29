from __future__ import annotations

from typing import Any
from collections import deque
from workflow_engine.nodes.base import BaseNode
from workflow_engine.context import NodeContext, _resolve_inputs
from workflow_engine.schema import WorkflowEdge
from workflow_engine.sse_helpers import _sse_node_started, _sse_node_progress, _sse_node_ended


class SubgraphExecutor:
    """在 Loop 内部执行一段子图，支持内部边、多入口、多出口、条件分支。

    用法：
        subgraph = SubgraphExecutor(body_nodes, body_edges, ctx)
        feedback, control = await subgraph.run(
            initial_input, iteration, confirm_callback, stop_event,
        )

    返回值：
        feedback: dict — 汇总所有出口节点的 outputs['default'] 作为下一轮输入
        control: str | None — 'break' / 'continue' / None
    """

    def __init__(
        self,
        body_nodes: list[Any],
        body_edges: list[Any],
        parent_ctx: Any,
    ):
        self.body_nodes = body_nodes
        self.body_edges = body_edges
        self.parent_ctx = parent_ctx

    async def run(
        self,
        initial_input: Any,
        iteration: int,
        confirm_callback: Any,
        stop_event: Any,
    ) -> tuple[dict | None, str | None]:
        """执行子图一轮，返回 (feedback, control)。"""
        if not self.body_nodes:
            return ({'default': initial_input}, None)

        # 1. 构建子图拓扑
        graph: dict[str, list[str]] = {}
        in_degree: dict[str, int] = {}
        for node in self.body_nodes:
            graph[node.id] = []
            in_degree[node.id] = 0
        for edge in self.body_edges:
            src_id = edge.get('source') if isinstance(edge, dict) else edge.source
            tgt_id = edge.get('target') if isinstance(edge, dict) else edge.target
            if src_id in graph and tgt_id in graph:
                graph[src_id].append(tgt_id)
                in_degree[tgt_id] += 1

        # 2. 识别入口节点（子图中入度为 0 的节点）
        entry_ids = [nid for nid, deg in in_degree.items() if deg == 0]

        # 3. 拓扑排序
        sorted_ids = self._topological_sort(graph, in_degree)

        # 4. 执行
        from workflow_engine.node_registry import NodeRegistry
        handlers = NodeRegistry.get_handlers()

        # 归一化 body_edges，子图内所有边默认全部激活
        normalized_edges = self._normalize_edges(self.body_edges)
        all_body_edge_ids = {e.id for e in normalized_edges}

        for nid in sorted_ids:
            if stop_event and stop_event.is_set():
                return (None, 'break')

            node_def = self._find_node(nid)
            if not node_def:
                continue

            handler_cls = handlers.get(node_def.type.value)
            if not handler_cls:
                continue

            handler = handler_cls(node_def)
            sub_ctx = NodeContext(nid)
            self.parent_ctx.node_contexts[nid] = sub_ctx

            # 注入输入：入口节点使用 initial_input，其余节点按 body_edges 解析上游输出
            if nid in entry_ids or in_degree.get(nid, 0) == 0:
                sub_ctx.inputs = {'default': initial_input}
            else:
                sub_ctx.inputs = await _resolve_inputs(
                    node_def, normalized_edges, self.parent_ctx, all_body_edge_ids,
                )

            async for _ in handler.execute(
                self.parent_ctx, sub_ctx, confirm_callback, stop_event,
            ):
                pass

            # 检测 __control__ 信号
            outs = sub_ctx.outputs or {}
            control = outs.get('__control__')
            if control in ('break', 'continue'):
                return ({'default': outs.get('default')}, control)

        # 5. 汇总出口节点（子图中无出边的节点）的输出
        feedback_parts: list[Any] = []
        for nid in sorted_ids:
            if graph.get(nid, []) == []:
                sub_ctx = self.parent_ctx.node_contexts.get(nid)
                if sub_ctx and sub_ctx.outputs:
                    raw = sub_ctx.outputs.get('default')
                    if raw is not None:
                        feedback_parts.append(raw)

        if not feedback_parts:
            return (None, None)

        # 单出口 → 直接返回；多出口 → 合并为列表
        merged = feedback_parts[0] if len(feedback_parts) == 1 else feedback_parts
        return ({'default': merged}, None)

    def _find_node(self, node_id: str) -> Any | None:
        for n in self.body_nodes:
            nid = n.get('id') if isinstance(n, dict) else n.id
            if nid == node_id:
                return n
        return None

    def _normalize_edges(self, body_edges: list[Any]) -> list[WorkflowEdge]:
        """将 body_edges 统一归一化为 WorkflowEdge 对象，兼容 dict/对象两种形态。"""
        result: list[WorkflowEdge] = []
        for edge in body_edges:
            if isinstance(edge, WorkflowEdge):
                result.append(edge)
                continue
            if isinstance(edge, dict):
                result.append(WorkflowEdge(
                    id=edge.get('id', ''),
                    source=edge.get('source', ''),
                    source_port=edge.get('sourcePort', edge.get('source_port', 'default')),
                    target=edge.get('target', ''),
                    target_port=edge.get('targetPort', edge.get('target_port', 'default')),
                ))
        return result

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

from __future__ import annotations

import json
from workflow_engine.nodes.base import BaseNode
from workflow_engine.nodes.subgraph_executor import SubgraphExecutor
from workflow_engine.sse_helpers import _sse_node_started, _sse_node_progress, _sse_node_ended


class LoopNode(BaseNode):
    node_type = 'loop'

    async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
        yield _sse_node_started(ctx, ctx_node)

        cfg = self.config.get('loopConfig') or {}
        max_iter = cfg.get('maxIterations', 10)
        if ctx.execution_config.max_iterations:
            max_iter = min(max_iter, ctx.execution_config.max_iterations)

        body_node_ids = cfg.get('bodyNodeIds', [])
        body_edges = cfg.get('bodyEdges', [])

        # 从 definition 中查找 body 节点对象
        body_nodes = []
        if ctx.definition:
            all_nodes = ctx.definition.nodes if ctx.definition else []
            body_nodes = [n for n in all_nodes if n.id in body_node_ids]

        subgraph = SubgraphExecutor(body_nodes, body_edges, ctx)
        current_input = ctx_node.inputs.get('default')

        for iteration in range(max_iter):
            if stop_event and stop_event.is_set():
                break

            # out_body SSE 事件：广播当前轮输入（纯观察，无下游边）
            yield _sse_node_progress(
                ctx, ctx_node,
                json.dumps({'iteration': iteration, 'input': current_input}, ensure_ascii=False),
            )

            feedback, control = await subgraph.run(
                current_input,
                iteration,
                confirm_callback,
                stop_event,
            )

            if control == 'break':
                break
            elif control == 'continue':
                if iteration + 1 >= max_iter:
                    break
                continue

            current_input = feedback.get('default') if feedback else None
            if current_input is None:
                break

        ctx_node.outputs = {
            'default': current_input if current_input is not None else '',
            'control': 'out_end',
        }
        yield _sse_node_ended(ctx, ctx_node)

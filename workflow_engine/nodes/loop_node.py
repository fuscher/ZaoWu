from __future__ import annotations

import asyncio
import json
from workflow_engine.context import _first
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

        subgraph = SubgraphExecutor(self.node_def, ctx)
        current_input = _first(ctx_node.inputs.get('in', ctx_node.inputs.get('default', '')))

        for iteration in range(max_iter):
            if stop_event and stop_event.is_set():
                break

            yield _sse_node_progress(
                ctx, ctx_node,
                json.dumps({'iteration': iteration, 'input': current_input}, ensure_ascii=False),
            )

            # 无界队列：流式 LLM 单节点可能产生大量事件，固定上限容易失真
            queue = asyncio.Queue()
            task = asyncio.create_task(subgraph.run(
                current_input,
                iteration,
                confirm_callback,
                stop_event,
                queue,
            ))
            try:
                while not task.done() or not queue.empty():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.1)
                        if event:
                            yield event
                    except asyncio.TimeoutError:
                        pass

                feedback, control = task.result()
            finally:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            if control == 'end':
                ctx_node.outputs = {
                    'default': '',
                    'out': '',
                    '__control__': 'end',
                }
                yield _sse_node_ended(ctx, ctx_node)
                return

            if control == 'stopped':
                break

            if feedback:
                current_input = feedback.get('default', current_input)

        ctx_node.outputs = {
            'default': current_input if current_input is not None else '',
            'out': current_input if current_input is not None else '',
            'control': 'out',
        }
        yield _sse_node_ended(ctx, ctx_node)

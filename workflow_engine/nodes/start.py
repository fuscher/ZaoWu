from __future__ import annotations

from workflow_engine.nodes.base import BaseNode
from workflow_engine.sse_helpers import _sse_node_started, _sse_node_ended


class StartNode(BaseNode):
    node_type = 'start'

    async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
        yield _sse_node_started(ctx, ctx_node)
        ctx_node.outputs = {'default': ctx.initial_input}
        yield _sse_node_ended(ctx, ctx_node)

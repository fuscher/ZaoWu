from __future__ import annotations

from workflow_engine.nodes.base import BaseNode
from workflow_engine.sse_helpers import _sse_node_started, _sse_node_ended


class EndNode(BaseNode):
    node_type = 'end'

    async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
        yield _sse_node_started(ctx, ctx_node)
        raw = ctx_node.inputs.get('default', [])
        if not isinstance(raw, list):
            raw = [raw]
        output_format = self.config.get('outputFormat', 'text')
        if output_format == 'json':
            ctx_node.outputs = {'default': raw}
        else:
            ctx_node.outputs = {'default': '\n---\n'.join(str(item) for item in raw)}
        yield _sse_node_ended(ctx, ctx_node)

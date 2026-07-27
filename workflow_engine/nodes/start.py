from __future__ import annotations

from workflow_engine.nodes.base import BaseNode
from workflow_engine.sse_helpers import _sse_node_started, _sse_node_ended


class StartNode(BaseNode):
    node_type = 'start'

    async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
        yield _sse_node_started(ctx, ctx_node)

        # defaultValue 防御性回退：使用 is not None 判断，
        # 避免覆盖用户有意传入的空字符串
        if ctx.initial_input is not None:
            value = ctx.initial_input
        else:
            value = self.config.get('defaultValue', '')

        ctx_node.outputs = {'default': value}

        # executionMode: parallel（默认）或 ordered
        # ordered 模式下由 executor 按 orderedTargets 顺序激活出边
        execution_mode = self.config.get('executionMode', 'parallel')
        if execution_mode == 'ordered':
            ordered_targets = self.config.get('orderedTargets', [])
            ctx_node.outputs['__ordered__'] = ordered_targets

        yield _sse_node_ended(ctx, ctx_node)

from __future__ import annotations

from services.tool_executor import ToolExecutor
from services.tool_registry import ToolRegistry
from workflow_engine.nodes.base import BaseNode
from workflow_engine.sse_helpers import (
    _sse_node_started, _sse_node_ended,
    _sse_node_requires_confirmation, _sse_wf_paused, _sse_wf_resumed,
)


class ToolNode(BaseNode):
    node_type = 'tool'

    async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
        yield _sse_node_started(ctx, ctx_node)

        tool_name = self.config.get('toolName')
        raw_args = self.config.get('toolArgs', {})
        args = ctx.resolve_all(raw_args, ctx_node.inputs)

        registry = ToolRegistry.get_instance()
        tool_def = registry.get(tool_name)
        requires_approval = tool_def.requires_approval if tool_def else False
        auto_approve = ctx.execution_config.auto_approve_writes

        if requires_approval and not (tool_name == 'write_file' and auto_approve):
            tool_call = {
                'requestId': f'{ctx.run_id}-{self.node_def.id}',
                'name': tool_name,
                'arguments': args,
            }
            yield _sse_node_requires_confirmation(ctx, ctx_node, tool_call)
            yield _sse_wf_paused(ctx, 'tool_confirmation')
            approved = await confirm_callback(self.node_def.id, tool_call)
            yield _sse_wf_resumed(ctx)
            if not approved:
                ctx_node.outputs = {'default': {'success': False, 'error': '用户已拒绝'}}
                yield _sse_node_ended(ctx, ctx_node)
                return

        executor = ToolExecutor(registry, ctx.project_paths)
        result = await executor.execute(tool_name, args)
        ctx_node.outputs = {'default': result}

        yield _sse_node_ended(ctx, ctx_node)

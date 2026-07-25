from __future__ import annotations

import asyncio
from workflow_engine.nodes.base import BaseNode
from workflow_engine.context import NodeContext
from workflow_engine.nodes.condition_node import safe_eval
from workflow_engine.sse_helpers import _sse_node_started, _sse_node_ended


class LoopNode(BaseNode):
    node_type = 'loop'

    async def execute(self, ctx, ctx_node, confirm_callback, stop_event):
        yield _sse_node_started(ctx, ctx_node)
        cfg = self.config.get('loopConfig') or {}
        mode = cfg.get('mode', 'for')
        body_node_ids = cfg.get('bodyNodeIds', [])
        body_edges = cfg.get('bodyEdges', [])
        max_iter = cfg.get('maxIterations', 10)
        if ctx.execution_config.max_iterations:
            max_iter = min(max_iter, ctx.execution_config.max_iterations)

        results: list = []
        control = 'output'

        if mode == 'for':
            iterable = ctx.resolve_value(cfg.get('iterateOver', '{{input}}'), ctx_node.inputs)
            if not isinstance(iterable, list):
                iterable = [iterable] if iterable else []
            for i, item in enumerate(iterable):
                if stop_event and stop_event.is_set():
                    control = 'break'
                    break
                if i >= max_iter:
                    control = 'break' if cfg.get('circuitBreakerAction') == 'break' else 'output'
                    break
                iter_out = await self._run_body_once(ctx, body_node_ids, body_edges,
                                                     {'item': item, 'index': i},
                                                     confirm_callback, stop_event)
                if iter_out.get('__control__') == 'break':
                    control = 'break'
                    break
                results.append(iter_out.get('default'))
        else:
            count = 0
            while count < max_iter:
                if stop_event and stop_event.is_set():
                    control = 'break'
                    break
                iter_out = await self._run_body_once(ctx, body_node_ids, body_edges,
                                                     {'index': count},
                                                     confirm_callback, stop_event)
                results.append(iter_out.get('default'))
                count += 1
                cond_expr = cfg.get('condition', 'False')
                try:
                    keep = safe_eval(cond_expr, {'input': iter_out.get('default'),
                                                 'count': count})
                except Exception:
                    keep = False
                if not keep:
                    break
            else:
                control = 'break' if cfg.get('circuitBreakerAction') == 'break' else 'output'

        ctx_node.outputs = {
            'default': results,
            'control': control,
        }
        yield _sse_node_ended(ctx, ctx_node)

    async def _run_body_once(self, ctx, body_node_ids, body_edges, loop_vars,
                             confirm_callback, stop_event):
        from workflow_engine.node_registry import NodeRegistry
        for nid in body_node_ids:
            if stop_event and stop_event.is_set():
                return {'default': None, '__control__': 'break'}
            node_def = self._find_node(ctx, nid)
            handler_cls = NodeRegistry.get_handlers().get(node_def.type.value)
            if not handler_cls:
                continue
            handler = handler_cls(node_def)
            sub_ctx = NodeContext(nid)
            ctx.node_contexts[nid] = sub_ctx
            if loop_vars:
                sub_ctx.inputs = {'default': loop_vars.get('item', ''), **loop_vars}
            async for event in handler.execute(ctx, sub_ctx, confirm_callback, stop_event):
                pass
        if not body_node_ids:
            return {'default': None}
        last_ctx = ctx.node_contexts.get(body_node_ids[-1])
        return last_ctx.outputs if last_ctx else {'default': None}

    def _find_node(self, ctx, node_id):
        for n in (ctx.definition.nodes if ctx.definition else []):
            if n.id == node_id:
                return n
        raise KeyError(f'循环体节点 {node_id} 不存在')

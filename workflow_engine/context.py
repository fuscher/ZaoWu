from __future__ import annotations

import re
from typing import Any


class NodeContext:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.inputs: dict[str, Any] = {}
        self.outputs: dict[str, Any] = {}
        self.tokens_in: int = 0
        self.tokens_out: int = 0
        self.elapsed_ms: float = 0
        self.error: str | None = None


class ExecutionContext:
    def __init__(
        self,
        workflow_id: str,
        run_id: str,
        execution_config: 'WorkflowExecutionConfig | None' = None,
        project_paths: list[str] | None = None,
        initial_input: str = '',
        definition: 'WorkflowDefinition | None' = None,
    ):
        self.workflow_id = workflow_id
        self.run_id = run_id
        from workflow_engine.schema import WorkflowExecutionConfig
        self.execution_config = execution_config or WorkflowExecutionConfig()
        self.project_paths = project_paths or []
        self.initial_input = initial_input
        self.definition = definition
        self.node_contexts: dict[str, NodeContext] = {}
        self._variable_resolver = VariableResolver(self)

    def resolve(self, template: str, local_inputs: dict | None = None) -> str:
        return self._variable_resolver.resolve(template, local_inputs)

    def resolve_value(self, template: str, local_inputs: dict | None = None) -> Any:
        return self._variable_resolver.resolve_value(template, local_inputs)

    def resolve_all(self, mapping: dict, local_inputs: dict | None = None) -> dict:
        return {k: self.resolve(v, local_inputs) if isinstance(v, str) else v
                for k, v in mapping.items()}


class VariableResolver:
    _PATTERN = re.compile(r'\{\{\s*([\w.]+)\s*\}\}')

    def __init__(self, ctx: ExecutionContext):
        self._ctx = ctx

    def resolve(self, template: str, local_inputs: dict | None = None) -> str:
        if not isinstance(template, str):
            return template

        def _sub(match: re.Match) -> str:
            return str(self._lookup(match.group(1), local_inputs))

        return self._PATTERN.sub(_sub, template)

    def resolve_value(self, template: str, local_inputs: dict | None = None) -> Any:
        if not isinstance(template, str):
            return template
        template = template.strip()
        match = self._PATTERN.fullmatch(template)
        if not match:
            return template
        return self._lookup(match.group(1), local_inputs)

    def _lookup(self, path: str, local_inputs: dict | None = None):
        parts = path.split('.')
        head = parts[0]

        if head == 'input' and local_inputs is not None:
            value = local_inputs.get('default', '')
            rest = parts[1:]
            if not rest:
                return _first(value)
            value = _first(value)
            for key in rest:
                if isinstance(value, dict):
                    value = value.get(key, '')
                else:
                    return ''
            return value

        if len(parts) == 1 and local_inputs is not None and head in local_inputs:
            return local_inputs[head]

        if len(parts) < 2:
            return ''
        node_id, *rest = parts
        node_ctx = self._ctx.node_contexts.get(node_id)
        if not node_ctx:
            return ''
        value = node_ctx.outputs
        for key in rest:
            if isinstance(value, dict):
                value = value.get(key, '')
            else:
                return ''
        return value


def _first(value):
    if isinstance(value, list):
        return value[0] if value else ''
    return value


async def _resolve_inputs(
    node_def: 'WorkflowNode',
    edges: list['WorkflowEdge'],
    ctx: ExecutionContext,
    active_edges: set[str],
) -> dict:
    inputs: dict[str, list] = {}

    def _append(port: str, value):
        inputs.setdefault(port, []).append(value)

    for edge in edges:
        if edge.target != node_def.id or edge.id not in active_edges:
            continue
        source_ctx = ctx.node_contexts.get(edge.source)
        if not source_ctx:
            continue
        source_output = source_ctx.outputs.get(edge.source_port, source_ctx.outputs.get('default'))

        # 若该边命中 input_mapping，仅追加到映射指定的 targetKey，
        # 不再重复追加到默认端口，避免数据泄漏到 default
        matched = False
        for mapping in node_def.input_mapping or []:
            if mapping.get('sourceNodeId') == edge.source and mapping.get('sourcePort') == edge.source_port:
                _append(mapping.get('targetKey') or 'default', source_output)
                matched = True

        if not matched:
            _append(edge.target_port or 'default', source_output)

    return inputs

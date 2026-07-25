from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Callable
from workflow_engine.context import NodeContext, ExecutionContext
from workflow_engine.schema import WorkflowNode, WorkflowEdge


class BaseNode(ABC):
    node_type: str

    def __init__(self, node_def: WorkflowNode):
        self.node_def = node_def
        self.config = node_def.config

    @abstractmethod
    async def execute(
        self,
        ctx: ExecutionContext,
        ctx_node: NodeContext,
        confirm_callback: Callable | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> AsyncGenerator[dict, None]:
        ...

    def get_next_nodes(self, edge_list: list[WorkflowEdge],
                       port: str | None = None) -> list[tuple[str, str]]:
        return [
            (e.target, e.target_port)
            for e in edge_list
            if e.source == self.node_def.id and (port is None or e.source_port == port)
        ]

from __future__ import annotations

from typing import Dict, Type
from workflow_engine.nodes.base import BaseNode
from workflow_engine.nodes.start import StartNode
from workflow_engine.nodes.llm_node import LLMNode
from workflow_engine.nodes.condition_node import ConditionNode
from workflow_engine.nodes.tool_node import ToolNode
from workflow_engine.nodes.end_node import EndNode
from workflow_engine.nodes.loop_node import LoopNode
from workflow_engine.schema import NodeType


class NodeRegistry:
    _handlers: Dict[str, Type[BaseNode]] = {
        NodeType.START.value: StartNode,
        NodeType.LLM.value: LLMNode,
        NodeType.CONDITION.value: ConditionNode,
        NodeType.TOOL.value: ToolNode,
        NodeType.END.value: EndNode,
        NodeType.LOOP.value: LoopNode,
    }

    @classmethod
    def get_handlers(cls) -> Dict[str, Type[BaseNode]]:
        return cls._handlers

    @classmethod
    def register(cls, node_type: str, handler_cls: Type[BaseNode]) -> None:
        cls._handlers[node_type] = handler_cls

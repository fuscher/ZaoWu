from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


class NodeType(str, Enum):
    START = "start"
    LLM = "llm"
    CONDITION = "condition"
    TOOL = "tool"
    LOOP = "loop"
    END = "end"


class EdgeType(str, Enum):
    DATA = "data"
    CONDITION = "condition"


@dataclass
class WorkflowNode:
    id: str
    type: NodeType
    position: dict[str, float]
    label: str
    config: dict[str, Any] = field(default_factory=dict)
    retry_config: Optional[dict] = None
    input_mapping: list[dict] = field(default_factory=list)
    output_expose: list[dict] = field(default_factory=list)


@dataclass
class WorkflowEdge:
    id: str
    source: str
    source_port: str
    target: str
    target_port: str
    type: str = 'smoothstep'           # Vue Flow 视觉渲染类型
    edge_type: EdgeType = EdgeType.DATA  # 业务语义类型
    condition: Optional[dict] = None
    data_contract: Optional[dict] = None
    label: Optional[str] = None


@dataclass
class WorkflowExecutionConfig:
    auto_approve_writes: bool = False
    max_iterations: Optional[int] = None   # 全局循环迭代上限
    timeout_seconds: Optional[int] = None  # 执行超时（秒）


@dataclass
class WorkflowDefinition:
    id: str
    name: str
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    execution_config: WorkflowExecutionConfig = field(default_factory=WorkflowExecutionConfig)
    variables: list[dict] = field(default_factory=list)
    version: int = 1
    description: str = ''
    created_at: int = 0
    updated_at: int = 0
    last_run_at: Optional[int] = None
    run_count: int = 0

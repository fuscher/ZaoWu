"""Agent 运行期状态存储抽象 — 为多 worker 部署预留（S13-P1-1）。

现状：Agent 的停止事件与活跃实例存于 ``routes/chat.py`` 模块级 dict，
仅适用于单 worker 部署（SSE 流与停止/确认请求同进程）。本模块提供
接口级抽象与默认内存实现，**单进程行为零变化**；未来多 worker 时
只需替换实现（如 Redis），路由层无感知。

Redis 改造点：
- ``StopStore``：停止事件可用 pub/sub（stop 端点发布，worker 订阅）
  或带 TTL 的共享键轮询。
- ``ActiveAgentStore``：确认端点需按 convId 定位 AgentService 所在
  worker，可用带 TTL 的共享索引（键含 worker id），或将确认事件
  本身下沉为共享队列。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional


class StopStore:
    """停止事件存储接口（convId → ``asyncio.Event``）。"""

    def get(self, conv_id: str) -> Optional[asyncio.Event]:
        """返回 convId 对应的停止事件；不存在返回 None。"""
        raise NotImplementedError

    def set(self, conv_id: str, event: asyncio.Event) -> None:
        """绑定 convId 与停止事件。"""
        raise NotImplementedError

    def pop(self, conv_id: str) -> Optional[asyncio.Event]:
        """移除并返回 convId 对应事件；不存在返回 None。"""
        raise NotImplementedError


class ActiveAgentStore:
    """活跃 Agent 存储接口（convId → ``AgentService`` 实例）。"""

    def get(self, conv_id: str) -> Optional[Any]:
        """返回 convId 对应的 AgentService；不存在返回 None。"""
        raise NotImplementedError

    def set(self, conv_id: str, agent: Any) -> None:
        """绑定 convId 与 AgentService 实例。"""
        raise NotImplementedError

    def pop(self, conv_id: str) -> Optional[Any]:
        """移除并返回 convId 对应实例；不存在返回 None。"""
        raise NotImplementedError

    def contains(self, conv_id: str) -> bool:
        """convId 是否已有活跃 Agent（并发防护用，见 F03）。"""
        raise NotImplementedError


class MemoryStopStore(StopStore):
    """默认内存实现：内部 dict，语义与现状（模块级 dict）完全等价。"""

    def __init__(self) -> None:
        self._events: Dict[str, asyncio.Event] = {}

    def get(self, conv_id: str) -> Optional[asyncio.Event]:
        return self._events.get(conv_id)

    def set(self, conv_id: str, event: asyncio.Event) -> None:
        self._events[conv_id] = event

    def pop(self, conv_id: str) -> Optional[asyncio.Event]:
        return self._events.pop(conv_id, None)


class MemoryActiveAgentStore(ActiveAgentStore):
    """默认内存实现：内部 dict，语义与现状（模块级 dict）完全等价。"""

    def __init__(self) -> None:
        self._agents: Dict[str, Any] = {}

    def get(self, conv_id: str) -> Optional[Any]:
        return self._agents.get(conv_id)

    def set(self, conv_id: str, agent: Any) -> None:
        self._agents[conv_id] = agent

    def pop(self, conv_id: str) -> Optional[Any]:
        return self._agents.pop(conv_id, None)

    def contains(self, conv_id: str) -> bool:
        return conv_id in self._agents

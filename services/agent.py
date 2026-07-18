"""智能体核心服务的兼容性 shim。

原实现已迁移至 agent_modules.agent_core.agent_service。
保留本文件以兼容旧导入路径。
"""

from agent_modules.agent_core.agent_service import (
    AgentService,
    AGENT_SYSTEM_PROMPT,
    _now_ts,
)

__all__ = ['AgentService', 'AGENT_SYSTEM_PROMPT', '_now_ts']

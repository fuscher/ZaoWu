"""Agent 核心模块。

本模块提供 AgentService 以及相关的常量，作为智能体运行时的核心入口。
"""

from agent_modules.agent_core.agent_service import (
    AgentService,
    AGENT_SYSTEM_PROMPT,
)
from agent_modules.agent_core.sandbox import SkillSandbox

__all__ = ['AgentService', 'AGENT_SYSTEM_PROMPT', 'SkillSandbox']

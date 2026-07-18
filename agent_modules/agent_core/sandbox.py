"""Skill Sandbox 封装层。

为 Skill 提供代码级 API 限制：每个 Skill 可以声明允许调用的工具白名单，
Sandbox 在运行时过滤 LLM 可见的工具列表以及实际可执行的工具。

如果白名单为空，则放行全部工具，保持向后兼容。
"""
from typing import Any, Dict, List, Optional, Set

from services.tool_executor import ToolExecutor
from services.tool_registry import ToolRegistry


class SkillSandbox:
    """限制 Skill 可访问工具的轻量级沙箱。

    用法：
        sandbox = SkillSandbox(tool_registry, executor, allowed_tools={'read_file', 'search_code'})
        specs = sandbox.build_openai_tools_spec()          # 仅含白名单工具
        result = await sandbox.execute('read_file', args)  # 白名单外工具被拒绝
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        allowed_tools: Optional[Set[str]] = None,
    ):
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.allowed_tools: Set[str] = set(allowed_tools or [])

    def is_allowed(self, tool_name: str) -> bool:
        """工具是否在白名单中。空白名单表示放行所有工具。"""
        if not self.allowed_tools:
            return True
        return tool_name in self.allowed_tools

    def build_openai_tools_spec(self) -> List[Dict[str, Any]]:
        """构建仅包含白名单工具的 OpenAI tools 描述。"""
        specs = self.tool_registry.build_openai_tools_spec()
        if not self.allowed_tools:
            return specs
        return [s for s in specs if self._tool_name_from_spec(s) in self.allowed_tools]

    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具；白名单外工具返回拒绝结果。"""
        if not self.is_allowed(tool_name):
            return {
                'success': False,
                'content': '',
                'error': (
                    f'工具 `{tool_name}` 不在当前 Skill 的白名单中，'
                    f'允许的工具：{sorted(self.allowed_tools)}'
                ),
                'tool': tool_name,
            }
        return await self.tool_executor.execute(tool_name, arguments)

    @staticmethod
    def _tool_name_from_spec(spec: Dict[str, Any]) -> Optional[str]:
        """从 OpenAI tool 描述中提取 function.name。"""
        try:
            return spec['function']['name']
        except (KeyError, TypeError):
            return None

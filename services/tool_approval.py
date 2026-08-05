"""工具审批规则引擎（阶段三 6.1）。

把 ``agent_service.REQUIRES_APPROVAL_TOOLS`` 布尔硬编码升级为可组合、可持久化、
可被模型感知的规则集。三态：``allow`` / ``deny`` / ``ask``，findLast 匹配
（后声明优先），缺省 ``ask``。

设计要点：
- **N2-M3**：``autoApproveWrites`` 转规则时由调用方强制绑定当前 conv_id，
  仅本会话内存生效，绝不写入全局规则表，避免跨会话越权泄漏。
- **现状修复**：默认规则从 ``ToolDefinition.requires_approval`` 元数据生成——
  requires_approval=True 的工具默认 ``ask``，其余默认 ``allow``。消除
  ``REQUIRES_APPROVAL_TOOLS`` 硬编码与 ``requires_approval`` 死字段的不一致：
  新增需审批工具只需在 ``@tool`` 标注，无需改 agent_service。
- **findLast 语义**：规则列表后声明优先。默认规则最先（最低优先级），
  持久化 always 规则、autoApproveWrites 规则、preset deny 规则依次叠加，
  preset deny 优先级最高（plan 模式覆盖 autoApproveWrites）。
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import List

from services.tool_registry import ToolRegistry


@dataclass
class ApprovalRule:
    """一条审批规则。

    ``resource`` 支持通配：``*`` 任意字符序列、``?`` 单字符，大小写敏感。
    形如 ``command:git status*`` / ``file:*`` / ``run_command:*``。
    """
    action: str        # 工具名，如 'run_command'
    resource: str      # 资源模式，如 'command:git status' / 'file:*'
    effect: str        # 'allow' | 'deny' | 'ask'

    def matches(self, action: str, resource: str) -> bool:
        return self.action == action and _match(self.resource, resource)


def _match(pattern: str, resource: str) -> bool:
    """通配匹配（定义原方案缺失的部分）。

    用 ``fnmatch.fnmatchcase`` 而非 ``fnmatch``，避免平台差异导致大小写归一化
    （Windows 下 fnmatch 会折叠大小写，使命令匹配不可预测）。
    """
    return fnmatch.fnmatchcase(resource, pattern)


def evaluate(action: str, resource: str, rules: List[ApprovalRule]) -> str:
    """findLast 匹配（后声明优先），无匹配返回 ``'ask'``。

    默认规则集已为每个工具生成显式规则（allow/ask），故正常路径下总能在默认层
    命中；此处的 ``'ask'`` 兜底仅针对未注册工具（不应发生），偏保守。
    """
    for r in reversed(rules):
        if r.matches(action, resource):
            return r.effect
    return 'ask'


def derive_resource(action: str, arguments: dict) -> str:
    """从工具名 + 参数派生资源描述字符串。

    - ``run_command`` → ``command:<command>``
    - ``write_file`` / ``edit_file`` → ``file:<path>``
    - 其他 → ``<tool_name>:*``（资源不可派生时用通配，规则按工具名整体匹配）
    """
    if action == 'run_command':
        return f"command:{arguments.get('command', '')}"
    if action in ('write_file', 'edit_file'):
        return f"file:{arguments.get('path', '')}"
    return f"{action}:*"


def build_default_rules(registry: ToolRegistry) -> List[ApprovalRule]:
    """默认规则从工具元数据生成（消除 REQUIRES_APPROVAL_TOOLS 硬编码）。

    requires_approval=True → ``ask``；False → ``allow``。
    每个工具都生成显式规则，使 evaluate 总能在默认层命中，避免非审批工具
    落入 ``'ask'`` 兜底而被误拦截。
    """
    rules: List[ApprovalRule] = []
    for t in registry.list_tools().values():
        effect = 'ask' if t.requires_approval else 'allow'
        rules.append(ApprovalRule(action=t.name, resource=f'{t.name}:*', effect=effect))
    return rules


def build_auto_approve_writes_rules() -> List[ApprovalRule]:
    """``autoApproveWrites=True`` 转为 allow 规则（仅本会话内存，不持久化）。

    N2-M3：由调用方确保仅作用于当前 conv_id——这些规则追加在默认规则之后、
    preset 之前，且绝不写入 ``tool_approval_rules`` 表，故不会跨会话泄漏。
    覆盖 ``write_file`` / ``edit_file`` 的所有文件（``file:*``）。
    """
    return [
        ApprovalRule(action='write_file', resource='file:*', effect='allow'),
        ApprovalRule(action='edit_file', resource='file:*', effect='allow'),
    ]

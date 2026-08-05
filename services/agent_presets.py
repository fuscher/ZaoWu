"""智能体预设（阶段三 6.2）。

N2-I4 解耦：plan 模式单靠 ``SkillSandbox``（工具可见性过滤）+ 审批引擎 deny
规则（兜底）即可实现系统级只读，不依赖审批引擎的持久化能力。

- ``build``：全工具，走默认审批规则。
- ``plan``：只读工具白名单 + 写工具 deny 规则 + 系统提示词后缀。

双重保险：plan 模式下写工具既在 ``SkillSandbox`` 不可见（LLM 看不到），
即使被强行调用也被 deny 规则拒绝（``SkillSandbox.execute`` 与审批引擎各拦一道）。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

from services.tool_approval import ApprovalRule

# plan 模式只读工具白名单（与 tool_registry 中 @tool 注册名一致）
PLAN_READ_ONLY_TOOLS: Set[str] = {
    'read_file', 'list_files', 'search_code',
    'git_status', 'git_diff', 'git_log', 'web_search',
}

AGENT_PRESETS: Dict[str, dict] = {
    'build': {
        # None=全部工具（由 skill allowed_tools 决定可见性）
        'tools': None,
        # 走默认规则 + 持久化 always 规则 + autoApproveWrites
        'approval_rules': [],
        'system_suffix': '',
    },
    'plan': {
        # 只读工具集，与 skill 白名单取交集（skill 只能收窄不能放开写工具）
        'tools': PLAN_READ_ONLY_TOOLS,
        # deny 规则优先级最高（在 _build_approval_rules 末尾追加），
        # 覆盖 autoApproveWrites 的 allow，确保 plan 模式绝不可写。
        'approval_rules': [
            ApprovalRule(action='write_file', resource='file:*', effect='deny'),
            ApprovalRule(action='edit_file', resource='file:*', effect='deny'),
            ApprovalRule(action='run_command', resource='command:*', effect='deny'),
        ],
        'system_suffix': (
            '\n\n## 当前模式：计划模式\n'
            '你只能读取和探索，不能修改文件或执行命令。'
            '产出方案后由用户切回执行模式落地。'
        ),
    },
}


def get_preset(name: str) -> dict:
    """返回预设配置，未知预设回退 build（保守放行）。"""
    return AGENT_PRESETS.get(name, AGENT_PRESETS['build'])


def preset_tools(name: str) -> Optional[Set[str]]:
    """返回 preset 的工具白名单；``None`` 表示不限制（build 模式）。"""
    return get_preset(name).get('tools')


def preset_approval_rules(name: str) -> List[ApprovalRule]:
    """返回 preset 的审批规则（plan 模式为 deny 写工具）。"""
    return list(get_preset(name).get('approval_rules', []))


def preset_system_suffix(name: str) -> str:
    """返回 preset 的系统提示词后缀。"""
    return get_preset(name).get('system_suffix', '')

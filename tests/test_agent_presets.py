"""智能体预设单元测试（阶段三 6.2）。"""
from services.agent_presets import (
    AGENT_PRESETS, get_preset,
    preset_tools, preset_approval_rules, preset_system_suffix,
    PLAN_READ_ONLY_TOOLS,
)
from services.tool_approval import ApprovalRule, evaluate


def test_get_preset_build():
    p = get_preset('build')
    assert p['tools'] is None
    assert p['approval_rules'] == []
    assert p['system_suffix'] == ''


def test_get_preset_plan():
    p = get_preset('plan')
    assert p['tools'] == PLAN_READ_ONLY_TOOLS
    assert len(p['approval_rules']) == 3
    assert p['system_suffix'].startswith('\n\n## 当前模式：计划模式')


def test_get_preset_unknown_falls_back_to_build():
    """未知 preset 保守回退 build（全放行），不误判为 plan。"""
    p = get_preset('nonexistent')
    assert p is AGENT_PRESETS['build']


def test_preset_tools_build_is_none():
    assert preset_tools('build') is None


def test_preset_tools_plan_is_readonly_set():
    tools = preset_tools('plan')
    assert 'read_file' in tools
    assert 'search_code' in tools
    assert 'git_status' in tools
    # 写工具不在只读集
    assert 'write_file' not in tools
    assert 'edit_file' not in tools
    assert 'run_command' not in tools


def test_preset_tools_unknown_is_none():
    """未知 preset 回退 build → tools=None（不限制）。"""
    assert preset_tools('nonexistent') is None


def test_preset_approval_rules_plan_denies_writes():
    rules = preset_approval_rules('plan')
    by_action = {r.action: r.effect for r in rules}
    assert by_action['write_file'] == 'deny'
    assert by_action['edit_file'] == 'deny'
    assert by_action['run_command'] == 'deny'


def test_preset_approval_rules_build_is_empty():
    assert preset_approval_rules('build') == []


def test_preset_approval_rules_returns_copy():
    """返回副本，修改不影响 AGENT_PRESETS 原数据。"""
    rules = preset_approval_rules('plan')
    rules.append(ApprovalRule('read_file', 'file:*', 'deny'))
    assert len(AGENT_PRESETS['plan']['approval_rules']) == 3  # 原数据未被污染


def test_preset_system_suffix_plan_has_text():
    suffix = preset_system_suffix('plan')
    assert '计划模式' in suffix
    assert '不能修改文件或执行命令' in suffix


def test_preset_system_suffix_build_is_empty():
    assert preset_system_suffix('build') == ''


def test_plan_deny_rules_evaluate_against_derived_resources():
    """plan 的 deny 规则能正确匹配 derive_resource 产生的资源字符串。"""
    from services.tool_approval import derive_resource
    rules = preset_approval_rules('plan')
    # write_file 任意路径 → deny
    assert evaluate('write_file', derive_resource('write_file', {'path': '/a/b.py'}), rules) == 'deny'
    # run_command 任意命令 → deny
    assert evaluate('run_command', derive_resource('run_command', {'command': 'ls'}), rules) == 'deny'

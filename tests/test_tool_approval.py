"""工具审批规则引擎单元测试（阶段三 6.1）。

覆盖：通配匹配、findLast 求值、资源派生、默认规则生成、autoApproveWrites 转规则。
"""
from services.tool_approval import (
    ApprovalRule, _match, evaluate, derive_resource,
    build_default_rules, build_auto_approve_writes_rules,
)
from services.tool_registry import ToolRegistry


# ── _match 通配匹配 ────────────────────────────────────────────


def test_match_exact_string():
    assert _match('command:git status', 'command:git status') is True


def test_match_wildcard_star():
    assert _match('file:*', 'file:/a/b.py') is True
    assert _match('command:git *', 'command:git status') is True


def test_match_wildcard_question_single_char():
    assert _match('file:a?c', 'file:abc') is True
    assert _match('file:a?c', 'file:abbc') is False  # ? 只匹配单字符


def test_match_case_sensitive():
    """fnmatchcase 不做平台归一化，大小写敏感。"""
    assert _match('command:Git Status', 'command:git status') is False
    assert _match('command:GIT*', 'command:git status') is False


def test_match_no_match_returns_false():
    assert _match('file:*', 'command:git status') is False


# ── evaluate findLast 求值 ─────────────────────────────────────


def test_evaluate_returns_ask_when_no_rules():
    assert evaluate('write_file', 'file:/a', []) == 'ask'


def test_evaluate_returns_ask_when_no_match():
    rules = [ApprovalRule('read_file', 'file:*', 'allow')]
    assert evaluate('write_file', 'file:/a', rules) == 'ask'


def test_evaluate_findlast_later_declaration_wins():
    """后声明优先：同 action+resource 匹配多条时取最后一条。"""
    rules = [
        ApprovalRule('write_file', 'file:*', 'ask'),     # 默认
        ApprovalRule('write_file', 'file:*', 'allow'),   # autoApproveWrites
        ApprovalRule('write_file', 'file:*', 'deny'),    # preset deny
    ]
    assert evaluate('write_file', 'file:/a', rules) == 'deny'


def test_evaluate_specific_resource_overrides_wildcard():
    """更具体的 resource 规则（后声明）覆盖通配默认。"""
    rules = [
        ApprovalRule('run_command', 'command:*', 'ask'),       # 默认通配
        ApprovalRule('run_command', 'command:git status', 'allow'),  # 用户 always
    ]
    assert evaluate('run_command', 'command:git status', rules) == 'allow'
    # 其他命令仍走默认 ask
    assert evaluate('run_command', 'command:rm -rf /', rules) == 'ask'


def test_evaluate_action_must_match():
    rules = [ApprovalRule('write_file', 'file:*', 'allow')]
    # action 不同 → 不匹配，落默认 ask
    assert evaluate('edit_file', 'file:/a', rules) == 'ask'


# ── derive_resource 资源派生 ───────────────────────────────────


def test_derive_resource_run_command():
    assert derive_resource('run_command', {'command': 'git status'}) == 'command:git status'


def test_derive_resource_run_command_missing_command():
    assert derive_resource('run_command', {}) == 'command:'


def test_derive_resource_write_file():
    assert derive_resource('write_file', {'path': '/a/b.py'}) == 'file:/a/b.py'


def test_derive_resource_edit_file():
    assert derive_resource('edit_file', {'path': '/a/b.py'}) == 'file:/a/b.py'


def test_derive_resource_other_tools_use_wildcard():
    """非 command/file 工具用 <tool>:* 通配，规则按工具名整体匹配。"""
    assert derive_resource('read_file', {'path': '/a'}) == 'read_file:*'
    assert derive_resource('web_search', {'query': 'x'}) == 'web_search:*'


# ── build_default_rules 默认规则 ──────────────────────────────


def test_build_default_rules_ask_for_approval_tools():
    """requires_approval=True 的工具默认 ask。"""
    rules = {r.action: r.effect for r in build_default_rules(ToolRegistry.get_instance())}
    assert rules['write_file'] == 'ask'
    assert rules['edit_file'] == 'ask'
    assert rules['run_command'] == 'ask'


def test_build_default_rules_allow_for_readonly_tools():
    """requires_approval=False 的工具默认 allow（不被误拦入确认流程）。"""
    rules = {r.action: r.effect for r in build_default_rules(ToolRegistry.get_instance())}
    assert rules['read_file'] == 'allow'
    assert rules['list_files'] == 'allow'
    assert rules['git_status'] == 'allow'


def test_build_default_rules_covers_all_registered_tools():
    """每个注册工具都有显式规则，evaluate 总能在默认层命中。"""
    registry = ToolRegistry.get_instance()
    rules = build_default_rules(registry)
    rule_actions = {r.action for r in rules}
    assert rule_actions == set(registry.list_tools().keys())


def test_build_default_rules_resource_is_tool_wildcard():
    """默认规则的 resource 为 <tool>:*，匹配该工具的所有资源。"""
    rules = {r.action: r.resource for r in build_default_rules(ToolRegistry.get_instance())}
    assert rules['write_file'] == 'write_file:*'
    assert rules['run_command'] == 'run_command:*'


# ── build_auto_approve_writes_rules ───────────────────────────


def test_auto_approve_writes_rules_covers_write_and_edit():
    """autoApproveWrites 转 allow 规则，覆盖 write_file/edit_file 所有文件。"""
    rules = build_auto_approve_writes_rules()
    by_action = {r.action: (r.resource, r.effect) for r in rules}
    assert by_action['write_file'] == ('file:*', 'allow')
    assert by_action['edit_file'] == ('file:*', 'allow')


def test_auto_approve_writes_rules_does_not_cover_run_command():
    """autoApproveWrites 仅影响写文件，run_command 仍需确认。"""
    rules = build_auto_approve_writes_rules()
    assert all(r.action != 'run_command' for r in rules)


# ── 组合：默认 + autoApproveWrites + preset deny 优先级 ────────


def test_priority_preset_deny_overrides_auto_approve():
    """findLast：preset deny（后追加）覆盖 autoApproveWrites allow。"""
    from services.agent_presets import preset_approval_rules
    rules = build_default_rules(ToolRegistry.get_instance())
    rules.extend(build_auto_approve_writes_rules())  # allow
    rules.extend(preset_approval_rules('plan'))       # deny
    # plan 模式下 write_file 被 deny，即使 autoApproveWrites 开了
    assert evaluate('write_file', 'file:/a', rules) == 'deny'
    assert evaluate('edit_file', 'file:/a', rules) == 'deny'
    assert evaluate('run_command', 'command:ls', rules) == 'deny'


def test_priority_auto_approve_overrides_default_ask():
    """autoApproveWrites allow 覆盖默认 ask。"""
    rules = build_default_rules(ToolRegistry.get_instance())
    rules.extend(build_auto_approve_writes_rules())
    assert evaluate('write_file', 'file:/a', rules) == 'allow'
    assert evaluate('edit_file', 'file:/a', rules) == 'allow'
    # run_command 不受 autoApproveWrites 影响，仍 ask
    assert evaluate('run_command', 'command:ls', rules) == 'ask'


def test_priority_user_always_overrides_default_ask():
    """用户 'always' 持久化规则覆盖默认 ask（针对特定资源）。"""
    rules = build_default_rules(ToolRegistry.get_instance())
    rules.append(ApprovalRule('run_command', 'command:git status', 'allow'))
    assert evaluate('run_command', 'command:git status', rules) == 'allow'
    # 其他命令仍 ask
    assert evaluate('run_command', 'command:rm -rf /', rules) == 'ask'

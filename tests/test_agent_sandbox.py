"""SkillSandbox 单元测试。"""
import asyncio

import pytest

from agent_modules.agent_core import SkillSandbox
from services.tool_executor import ToolExecutor
from services.tool_registry import ToolRegistry


@pytest.fixture
def sandbox():
    """提供未加限制的 Sandbox 实例。"""
    return SkillSandbox(
        ToolRegistry.get_instance(),
        ToolExecutor(ToolRegistry.get_instance(), []),
    )


@pytest.fixture
def restricted_sandbox():
    """提供只允许 read_file 的 Sandbox 实例。"""
    return SkillSandbox(
        ToolRegistry.get_instance(),
        ToolExecutor(ToolRegistry.get_instance(), []),
        {'read_file'},
    )


def test_sandbox_allows_all_when_no_whitelist(sandbox):
    assert sandbox.is_allowed('read_file') is True
    assert sandbox.is_allowed('write_file') is True
    assert sandbox.is_allowed('any_tool') is True


def test_sandbox_respects_whitelist(restricted_sandbox):
    assert restricted_sandbox.is_allowed('read_file') is True
    assert restricted_sandbox.is_allowed('write_file') is False
    assert restricted_sandbox.is_allowed('run_command') is False


def test_sandbox_build_tools_spec_filters_by_name(restricted_sandbox):
    specs = restricted_sandbox.build_openai_tools_spec()
    names = {
        s['function']['name']
        for s in specs
        if 'function' in s and 'name' in s['function']
    }
    assert names == {'read_file'}


def _run(coro):
    """在新事件循环中运行协程，避免复用已关闭的默认循环。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_sandbox_execute_allows_whitelisted_tool(restricted_sandbox):
    # read_file 白名单内，但路径不存在会返回失败结果；这里只验证没有被沙箱拒绝。
    result = _run(restricted_sandbox.execute('read_file', {'path': '/nonexistent/path'}))
    assert '不在当前 Skill 的白名单中' not in result.get('error', '')


def test_sandbox_execute_rejects_non_whitelisted_tool(restricted_sandbox):
    result = _run(restricted_sandbox.execute('write_file', {'path': '/a', 'content': 'x'}))
    assert result['success'] is False
    assert '不在当前 Skill 的白名单中' in result['error']
    assert 'read_file' in result['error']

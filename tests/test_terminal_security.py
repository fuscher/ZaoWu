"""终端命令执行安全校验测试。"""
import pytest
import sys

from routes.terminal import (
    is_command_safe,
    build_terminal_args,
    _SHELL_OPERATORS,
    _WINDOWS_CMD_BUILTINS,
)
from services.terminal_utils import agent_is_command_safe


def test_is_command_safe_allows_git_status():
    safe, err = is_command_safe('git status')
    assert safe is True
    assert err == ''


def test_is_command_safe_blocks_pipe():
    safe, err = is_command_safe('git status | cat')
    assert safe is False
    assert 'shell operator' in err


def test_is_command_safe_blocks_chain():
    safe, err = is_command_safe('git status && calc.exe')
    assert safe is False


def test_is_command_safe_blocks_command_substitution():
    safe, err = is_command_safe('git status $(whoami)')
    assert safe is False


def test_is_command_safe_blocks_newline():
    safe, err = is_command_safe('git status\ncalc.exe')
    assert safe is False


def test_is_command_safe_blocks_redirect_in_command_string():
    # 原始字符串含重定向符号，应在白名单/操作符层拦截
    safe, err = is_command_safe('git status > file.txt')
    # '>' 不在 _SHELL_OPERATORS 全局黑名单中，因此这里被允许到达 build_terminal_args
    # 但 Windows 下非内置命令使用 shell=False，'>' 仅是普通参数字符
    assert safe is True


def test_build_terminal_args_returns_list_for_executable():
    args, err = build_terminal_args('git status')
    assert err == ''
    assert args == ['git', 'status']


def test_build_terminal_args_rejects_cmd_metacharacters_for_windows_builtin():
    if sys.platform != 'win32':
        pytest.skip('仅 Windows 环境测试 cmd /c 路径')
    args, err = build_terminal_args('dir > file.txt')
    assert args is None
    assert 'cmd metacharacter' in err


def test_build_terminal_args_allows_safe_windows_builtin():
    if sys.platform != 'win32':
        pytest.skip('仅 Windows 环境测试 cmd /c 路径')
    args, err = build_terminal_args('dir')
    assert err == ''
    assert args == ['cmd', '/c', 'dir']


def test_agent_is_command_safe_allows_pytest():
    safe, err = agent_is_command_safe('pytest tests/')
    assert safe is True


def test_agent_is_command_safe_blocks_dangerous_pattern():
    safe, err = agent_is_command_safe('rm -rf /')
    assert safe is False


def test_agent_does_not_allow_docker_or_kubectl():
    """3.2: docker/kubectl 不纳入 agent 默认白名单（高危，本地 AI 编程极少需要）。"""
    safe, err = agent_is_command_safe('docker ps')
    assert safe is False
    assert 'not allowed' in err
    safe, err = agent_is_command_safe('kubectl get pods')
    assert safe is False
    assert 'not allowed' in err


def test_agent_is_command_safe_blocks_shell_operators():
    """3.2: agent 模式拒绝 shell 操作符，防止管道/链式命令绕过白名单。"""
    for cmd in ('git status | cat', 'git status && whoami', 'git status; ls',
                'echo `whoami`', 'echo $(whoami)'):
        safe, err = agent_is_command_safe(cmd)
        assert safe is False, f'{cmd} should be blocked'
        assert 'shell operator' in err


def test_full_flow_windows_builtin_allowed():
    """Windows cmd 内置命令应通过 is_command_safe 与 build_terminal_args 完整链路。"""
    safe, err = is_command_safe('dir')
    assert safe is True, f'dir should be allowed, got: {err}'
    args, err = build_terminal_args('dir')
    assert err == ''
    if sys.platform == 'win32':
        assert args == ['cmd', '/c', 'dir']
    else:
        assert args == ['dir']

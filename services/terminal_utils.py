"""终端命令执行纯函数 — 供智能体工具调用使用，不依赖 Quart request 上下文。"""
import os
import shlex
import asyncio

from routes.terminal import validate_terminal_path, BLOCKED_PATTERNS, ALLOWED_COMMANDS, _SHELL_OPERATORS

# 智能体模式扩展白名单——在终端面板白名单基础上增加 AI 编程常用工具
AGENT_ALLOWED_COMMANDS = set(ALLOWED_COMMANDS) | {
    'pytest', 'mypy', 'flake8', 'black', 'ruff', 'isort',
    'go', 'cargo', 'make', 'cmake',
    'curl', 'wget', 'grep', 'find', 'diff', 'sed', 'awk',
    'tsc', 'eslint', 'prettier', 'vite', 'webpack', 'rollup',
    'docker', 'kubectl',
}


def agent_is_command_safe(command: str) -> tuple:
    """智能体模式命令安全校验（扩展白名单 + 管道检测）

    与 routes/terminal.py 的 is_command_safe 的区别：
    1. 使用 AGENT_ALLOWED_COMMANDS（包含 pytest/mypy/ruff 等开发工具）
    2. 检测 shell 操作符（|, &&, ||, ;, `, $()），防止管道命令绕过白名单
       （_SHELL_OPERATORS 现从 routes/terminal.py 导入，单一来源）
    """
    cmd = command.strip()
    if not cmd:
        return False, 'command cannot be empty'

    cmd_lower = cmd.lower()

    # 1. 黑名单子串检查（复用 terminal.py 的 BLOCKED_PATTERNS）
    for pattern in BLOCKED_PATTERNS:
        if pattern.lower() in cmd_lower:
            return False, 'blocked pattern: ' + pattern

    # 2. Shell 操作符检测（防止管道/链式命令绕过白名单）
    for op in _SHELL_OPERATORS:
        if op in cmd:
            return False, f'shell operator not allowed in agent mode: {op}'

    # 3. 白名单检查（使用扩展白名单）
    cmd_parts = shlex.split(cmd)
    if not cmd_parts:
        return False, 'command cannot be empty'
    if cmd_parts[0] not in AGENT_ALLOWED_COMMANDS:
        return False, 'command not allowed: ' + cmd_parts[0]

    return True, ''


async def execute_command(command: str, cwd: str) -> dict:
    """执行终端命令（异步，纯函数）

    复用 routes/terminal.py 的 validate_terminal_path 进行路径验证，
    使用 agent_is_command_safe（扩展白名单 + 管道检测）。
    """
    path_error = validate_terminal_path(cwd)
    if path_error:
        return {'ok': False, 'error': path_error}

    safe, err_msg = agent_is_command_safe(command)
    if not safe:
        return {'ok': False, 'error': err_msg}

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=os.path.realpath(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = stdout.decode('utf-8', errors='replace')
        if stderr:
            output += '\n' + stderr.decode('utf-8', errors='replace')

        if len(output) > 8_000:
            output = output[:8_000] + '\n... (output truncated)'

        return {
            'ok': True,
            'output': output.strip() or '(no output)',
            'exitCode': proc.returncode,
        }
    except asyncio.TimeoutError:
        return {'ok': False, 'error': 'command timed out (30s)'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

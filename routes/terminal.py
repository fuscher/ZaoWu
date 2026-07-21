import os
import shlex
import subprocess
from quart import Blueprint, request, jsonify
from routes.log import append_log
from routes.explorer import is_path_in_projects
from services.input_validation import require_command, require_str, validate_json_body

terminal_bp = Blueprint('terminal', __name__)

ALLOWED_COMMANDS = ['git', 'npm', 'npx', 'node', 'python', 'pip',
                    'dir', 'ls', 'cat', 'type', 'echo', 'pwd', 'cd',
                    'mkdir', 'rmdir', 'copy', 'move', 'ren', 'del']

BLOCKED_PATTERNS = [
    'rm -rf', 'rmdir /s', 'del /s', 'del /f /s', 'del /q',
    'format', 'shutdown', 'taskkill', 'diskpart', 'reg',
]

# Shell 操作符检测——防止管道/链式命令绕过白名单
# 这些字符在 shell=True 模式下会触发命令链接/替换，必须拒绝
_SHELL_OPERATORS = ('|', '&&', '||', ';', '`', '$(')


def validate_terminal_path(cwd):
    if not cwd:
        return 'missing working directory'
    try:
        real = os.path.realpath(cwd)
        if not os.path.exists(real) or not os.path.isdir(real):
            return 'working directory does not exist'
        if not is_path_in_projects(real):
            return 'working directory is not within registered projects'
        return None
    except Exception as e:
        return str(e)


def is_command_safe(command):
    """校验命令是否安全执行。

    三层防护：
    1. 黑名单子串检查（BLOCKED_PATTERNS）— 拦截危险命令模式
    2. Shell 操作符检测（_SHELL_OPERATORS）— 防止 |, &&, ;, `, $() 绕过白名单
    3. 白名单检查 — 使用 shlex.split 正确解析命令，校验首词

    注意：即使有 shell=True，操作符检测也能阻止命令链接攻击，
    因为攻击者无法用 `git status && calc.exe` 等模式绕过。
    """
    cmd = command.strip()
    if not cmd:
        return False, 'command cannot be empty'
    cmd_lower = cmd.lower()

    # 1. 黑名单子串检查
    for pattern in BLOCKED_PATTERNS:
        if pattern.lower() in cmd_lower:
            return False, 'blocked pattern: ' + pattern

    # 2. Shell 操作符检测（防止管道/链式命令绕过白名单）
    for op in _SHELL_OPERATORS:
        if op in cmd:
            return False, f'shell operator not allowed: {op}'

    # 3. 白名单检查（使用 shlex 正确分割，处理带引号的参数）
    try:
        cmd_parts = shlex.split(cmd)
    except ValueError as e:
        return False, f'invalid command syntax: {e}'
    if not cmd_parts:
        return False, 'command cannot be empty'
    if cmd_parts[0] not in ALLOWED_COMMANDS:
        return False, 'command not allowed: ' + cmd_parts[0]
    return True, ''


@terminal_bp.route('/exec', methods=['POST'])
async def exec_command():
    data = await request.get_json(silent=True)

    # 输入校验：请求体必须是有效 JSON 对象
    ok, err = validate_json_body(data)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400

    # 输入校验：cwd 必须是非空字符串
    ok, err = require_str(data, 'cwd', max_len=4096)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400
    cwd = data['cwd'].strip()

    # 输入校验：command 必须是非空字符串，无控制字符
    ok, err = require_command(data, 'command', max_len=2000)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400
    command = data['command'].strip()

    v_error = validate_terminal_path(cwd)
    if v_error:
        return jsonify({'ok': False, 'error': v_error}), 403

    safe, err_msg = is_command_safe(command)
    if not safe:
        return jsonify({'ok': False, 'error': err_msg}), 400

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=os.path.realpath(cwd),
            capture_output=True,
            text=True,
            timeout=30,
            encoding='utf-8',
            errors='replace',
        )
        output = result.stdout
        if result.stderr:
            output += '\n' + result.stderr
        return jsonify({'ok': True, 'output': output.strip(), 'exitCode': result.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': 'command timed out'})
    except Exception as e:
        append_log({
            'level': 'error',
            'type': 'TerminalExecError',
            'message': str(e),
            'details': {'cwd': cwd, 'command': command},
        })
        return jsonify({'ok': False, 'error': str(e)})

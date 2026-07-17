import os
import subprocess
from quart import Blueprint, request, jsonify
from routes.log import append_log
from routes.explorer import is_path_in_projects

terminal_bp = Blueprint('terminal', __name__)

ALLOWED_COMMANDS = ['git', 'npm', 'npx', 'node', 'python', 'pip',
                    'dir', 'ls', 'cat', 'type', 'echo', 'pwd', 'cd',
                    'mkdir', 'rmdir', 'copy', 'move', 'ren', 'del']

BLOCKED_PATTERNS = [
    'rm -rf', 'rmdir /s', 'del /s', 'del /f /s', 'del /q',
    'format', 'shutdown', 'taskkill', 'diskpart', 'reg',
]


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
    cmd = command.strip()
    if not cmd:
        return False, 'command cannot be empty'
    cmd_lower = cmd.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern.lower() in cmd_lower:
            return False, 'blocked pattern: ' + pattern
    cmd_parts = cmd.split()
    if cmd_parts[0] not in ALLOWED_COMMANDS:
        return False, 'command not allowed: ' + cmd_parts[0]
    return True, ''


@terminal_bp.route('/exec', methods=['POST'])
async def exec_command():
    data = await request.get_json(silent=True) or {}
    cwd = data.get('cwd', '')
    command = data.get('command', '')

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

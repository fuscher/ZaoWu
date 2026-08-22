from __future__ import annotations

import re
from quart import Blueprint, request, jsonify
from routes.log import append_log
from services.input_validation import require_command, require_str, validate_json_body
from services.command_policy import (
    ALLOWED_COMMANDS, BLOCKED_PATTERNS, _SHELL_OPERATORS, _WINDOWS_CMD_BUILTINS,
    validate_terminal_path, is_command_safe, _validate_cmd_metacharacters,
    build_terminal_args,
)
from services.terminal_utils import execute_command

terminal_bp = Blueprint('terminal', __name__)


def strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)


@terminal_bp.route('/exec', methods=['POST'])
async def exec_command():
    data = await request.get_json(silent=True)

    ok, err = validate_json_body(data)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400

    ok, err = require_str(data, 'cwd', max_len=4096)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400
    cwd = data['cwd'].strip()

    ok, err = require_command(data, 'command', max_len=2000)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400
    command = data['command'].strip()

    result = await execute_command(command, cwd, safe_checker=is_command_safe)

    if result.get('output'):
        result['output'] = strip_ansi(result['output'])

    status = 200 if result.get('ok') else 400
    return jsonify(result), status

"""轻量级 HTTP 请求输入校验工具。

不引入 pydantic 等重依赖，提供针对安全敏感参数（path、command、字符串字段）
的类型和内容校验。所有校验函数返回 (ok, error_message) 元组。

使用示例::

    from services.input_validation import require_str, require_path

    data = await request.get_json(silent=True) or {}
    ok, err = require_str(data, 'command', max_len=2000)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400
"""
from __future__ import annotations

import os
from typing import Any, Optional


def require_str(data: dict, key: str, max_len: Optional[int] = None) -> tuple[bool, str]:
    """校验 data[key] 是非空字符串。

    Args:
        data: 请求体字典。
        key: 字段名。
        max_len: 最大长度限制（字符数），None 表示不限制。

    Returns:
        (True, '') 校验通过； (False, 'error message') 校验失败。
    """
    if key not in data:
        return False, f'missing field: {key}'
    value = data[key]
    if not isinstance(value, str):
        return False, f'field {key} must be a string, got {type(value).__name__}'
    value = value.strip()
    if not value:
        return False, f'field {key} cannot be empty'
    if max_len is not None and len(value) > max_len:
        return False, f'field {key} exceeds max length {max_len}'
    return True, ''


def get_str(data: dict, key: str, default: str = '', max_len: Optional[int] = None) -> tuple[bool, str, str]:
    """获取可选字符串字段，返回 (ok, error, value)。

    与 require_str 的区别：字段缺失时返回 default 值而非报错。
    """
    if key not in data or data[key] is None:
        return True, '', default
    value = data[key]
    if not isinstance(value, str):
        return False, f'field {key} must be a string, got {type(value).__name__}', default
    value = value.strip() if value else default
    if max_len is not None and len(value) > max_len:
        return False, f'field {key} exceeds max length {max_len}', default
    return True, '', value


def require_path(data: dict, key: str = 'path', max_len: int = 4096) -> tuple[bool, str]:
    """校验 data[key] 是合法的文件路径字符串。

    安全检查：
    1. 必须是字符串类型（防止 int/list 注入）
    2. 长度限制（防止超长路径攻击）
    3. 不包含 null 字节（防止 null 字节注入）

    注意：路径遍历（../）的防护由调用方的 is_path_in_projects 负责，
    此函数只做基础类型和格式校验。
    """
    ok, err = require_str(data, key, max_len=max_len)
    if not ok:
        return False, err
    value = data[key]
    if '\x00' in value:
        return False, f'field {key} contains null byte'
    return True, ''


def require_command(data: dict, key: str = 'command', max_len: int = 2000) -> tuple[bool, str]:
    """校验 data[key] 是合法的命令字符串。

    安全检查：
    1. 必须是字符串类型
    2. 长度限制（防止缓冲区攻击）
    3. 不包含 null 字节
    4. 不包含回车换行（防止命令注入 CRLF）

    注意：shell 操作符检测由 routes/terminal.py 的 is_command_safe 负责。
    """
    ok, err = require_str(data, key, max_len=max_len)
    if not ok:
        return False, err
    value = data[key]
    if '\x00' in value or '\r' in value or '\n' in value:
        return False, f'field {key} contains invalid control characters'
    return True, ''


def require_int(data: dict, key: str, min_val: Optional[int] = None,
                max_val: Optional[int] = None) -> tuple[bool, str, int]:
    """校验 data[key] 是整数，返回 (ok, error, value)。"""
    if key not in data or data[key] is None:
        return False, f'missing field: {key}', 0
    value = data[key]
    # 接受 int 或可转换为 int 的字符串
    if isinstance(value, bool):
        return False, f'field {key} must be an integer, not boolean', 0
    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError:
            return False, f'field {key} must be an integer', 0
    elif not isinstance(value, int):
        return False, f'field {key} must be an integer, got {type(value).__name__}', 0
    if min_val is not None and value < min_val:
        return False, f'field {key} must be >= {min_val}', value
    if max_val is not None and value > max_val:
        return False, f'field {key} must be <= {max_val}', value
    return True, '', value


def validate_json_body(data: Any) -> tuple[bool, str]:
    """校验请求体是有效的非空字典。

    替代 `await request.get_json(silent=True)` 后的 `if not body` 检查，
    提供更明确的错误信息。
    """
    if data is None:
        return False, 'request body is required or invalid JSON'
    if not isinstance(data, dict):
        return False, f'request body must be a JSON object, got {type(data).__name__}'
    if not data:
        return False, 'request body cannot be empty'
    return True, ''

"""工具执行器 — 安全执行工具调用，格式化结果。

执行策略：
- 按 execution_mode 分组：parallel 工具可并发执行，sequential 工具串行执行
- 错误不终止：无论成功失败都注入消息历史，由 LLM 自行判断下一步
- 不自动重试：失败结果中携带 `success: false`，LLM 可选择重试或换用其他工具
"""
import os
import json
import asyncio
from typing import Dict, Any, Optional, List
from services.tool_registry import ToolRegistry, ToolDefinition


# Python 类型 → JSON Schema 类型名反向映射，用于错误信息与 expected 对称
_PY_TO_JSON_TYPE = {
    str: 'string', int: 'integer', float: 'number',
    bool: 'boolean', list: 'array', dict: 'object',
}


class ToolExecutor:
    """工具执行器，负责参数验证、安全校验、结果格式化。

    多项目白名单——接受 project_bases 列表，验证目标路径是否在任一已注册项目中。
    当用户通过 agentConfig.projectPath 限缩时，白名单仅包含该项目。
    """

    MAX_RESULT_LENGTH = 8_000  # 结果内容最大字符数

    def __init__(self, registry: ToolRegistry, project_bases: list = None):
        self.registry = registry
        self.project_bases = project_bases or [os.getcwd()]

    def validate_path(self, path: str) -> bool:
        """验证路径是否在任一已注册项目内（多项目白名单）"""
        try:
            real = os.path.realpath(path)
            for base in self.project_bases:
                base_real = os.path.realpath(base)
                if os.path.commonpath([real, base_real]) == base_real:
                    return True
            return False
        except (ValueError, OSError):
            return False

    def validate_arguments(self, tool: ToolDefinition, arguments: dict) -> Optional[str]:
        """验证参数，返回错误信息或 None（通过）

        校验顺序：必填 → 路径白名单 → 写路径确认 → 类型/枚举。
        类型/枚举校验在 handler 前拦截，返回结构化错误帮模型自我修正，
        而非让 handler 抛异常浪费往返。
        """
        required = tool.parameters.get('required', [])
        for key in required:
            if key not in arguments:
                return f'missing required parameter: {key}'

        # 路径参数必须通过白名单验证
        for path_key in ('path', 'project_path', 'cwd'):
            if path_key in arguments:
                if not self.validate_path(arguments[path_key]):
                    return f'path not in project: {arguments[path_key]}'

        # 写文件需要确认
        if tool.name in ('write_file', 'edit_file') and 'path' in arguments:
            if not self.validate_path(arguments['path']):
                return f'write path not in project: {arguments["path"]}'

        # 类型与枚举校验：按 tool.parameters['properties'] 的 JSON Schema 校验
        properties = tool.parameters.get('properties', {})
        for pname, spec in properties.items():
            if pname not in arguments:
                continue
            err = self._check_type(pname, arguments[pname], spec)
            if err:
                return err

        return None

    @staticmethod
    def _check_type(name: str, val, spec: dict) -> Optional[str]:
        """按 JSON Schema 片段校验单个参数的类型与枚举。

        - bool 是 int 子类：isinstance(True, (int, float)) 为 True，
          故 integer 与 number 都必须先排除 bool，否则 True 会通过 number 校验。
        - enum 校验对所有类型生效（不只 integer），否则 string enum 永不触发。
        - 实际类型名映射为 JSON Schema 名（str→string 等），与 expected 对称，便于模型理解。
        """
        expected = spec.get('type')
        # None 视为"未提供"，交由 handler 的默认值处理，保持与既有行为兼容
        # （如 search_code 的 project_path: str = None，模型传 null 不应被类型校验拦截）。
        if val is None:
            return None
        type_map = {
            'string': str, 'integer': int, 'number': (int, float),
            'boolean': bool, 'array': list, 'object': dict,
        }
        if expected in ('integer', 'number') and isinstance(val, bool):
            return f'parameter {name}: expected {expected}, got boolean'
        py_type = type_map.get(expected)
        if py_type and not isinstance(val, py_type):
            # 反向映射 Python 类型 → JSON Schema 名，与 expected 对称
            actual = _PY_TO_JSON_TYPE.get(type(val), type(val).__name__)
            return f'parameter {name}: expected {expected}, got {actual}'
        if 'enum' in spec and val not in spec['enum']:
            return f'parameter {name}: {val!r} not in {spec["enum"]}'
        return None

    async def execute(self, tool_name: str, arguments: dict) -> dict:
        """执行工具，返回统一格式的结果"""
        tool = self.registry.get(tool_name)
        if not tool:
            return {'success': False, 'error': f'Tool "{tool_name}" not found'}

        # 参数验证
        validation_error = self.validate_arguments(tool, arguments)
        if validation_error:
            return {'success': False, 'error': validation_error}

        # 执行（错误不终止，所有异常捕获为失败结果）
        try:
            handler = tool.handler
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                result = await asyncio.to_thread(handler, **arguments)

            return self._format_result(result, tool_name)
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _format_result(self, raw: dict, tool_name: str) -> dict:
        """格式化工具执行结果，确保统一结构

        run_command 的 output 字段需打包 output + exitCode 为 JSON 对象后序列化。
        search_code 需打包 results + totalFiles + totalMatches 为 JSON 对象后序列化。
        截断统一在末尾按序列化后的实际内容长度执行，truncated 标志与真实截断一致。
        """
        formatted = {
            'success': raw.get('ok', False),
            'content': '',
        }

        if raw.get('ok'):
            if tool_name == 'run_command':
                payload = {
                    'output': raw.get('output', ''),
                    'exitCode': raw.get('exitCode', 0),
                }
                formatted['content'] = json.dumps(payload, ensure_ascii=False)
            elif tool_name == 'search_code':
                payload = {
                    'results': raw.get('results', []),
                    'totalFiles': raw.get('totalFiles', 0),
                    'totalMatches': raw.get('totalMatches', 0),
                }
                formatted['content'] = json.dumps(payload, ensure_ascii=False)
            elif tool_name in ('write_file', 'edit_file'):
                payload = {
                    'path': raw.get('path', ''),
                    'diff': raw.get('diff', ''),
                }
                if 'replacements' in raw:
                    payload['replacements'] = raw['replacements']
                if 'created' in raw:
                    payload['created'] = raw['created']
                formatted['content'] = json.dumps(payload, ensure_ascii=False)
            else:
                content_fields = {
                    'read_file': 'content',
                    'list_files': 'tree',
                    'search_code': 'results',
                    'git_status': 'files',
                    'git_diff': 'diff',
                    'git_log': 'commits',
                    'run_command': 'output',
                }

                key = content_fields.get(tool_name)
                if key and key in raw:
                    content = raw[key]
                    if isinstance(content, (list, dict)):
                        content = json.dumps(content, ensure_ascii=False, indent=2)
                    else:
                        content = str(content)
                    formatted['content'] = content
                else:
                    formatted['content'] = json.dumps(raw, ensure_ascii=False, indent=2)

            # 统一截断：以序列化后的实际内容长度为准，避免 truncated 标志失真
            if len(formatted['content']) > self.MAX_RESULT_LENGTH:
                formatted['content'] = formatted['content'][:self.MAX_RESULT_LENGTH]
                formatted['truncated'] = True
        else:
            formatted['error'] = raw.get('error', 'unknown error')

        formatted['tool'] = tool_name
        return formatted

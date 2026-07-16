"""工具执行器 — 安全执行工具调用，格式化结果。

执行策略：
- 串行执行：按 LLM 返回的顺序依次执行，避免依赖冲突
- 错误不终止：无论成功失败都注入消息历史，由 LLM 自行判断下一步
- 不自动重试：失败结果中携带 `success: false`，LLM 可选择重试或换用其他工具
"""
import os
import json
import asyncio
from typing import Dict, Any, Optional, List
from services.tool_registry import ToolRegistry, ToolDefinition


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
        """验证参数，返回错误信息或 None（通过）"""
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
        if tool.name == 'write_file' and 'path' in arguments:
            if not self.validate_path(arguments['path']):
                return f'write path not in project: {arguments["path"]}'

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
                formatted['content'] = json.dumps(payload, ensure_ascii=False)[:self.MAX_RESULT_LENGTH]
            elif tool_name == 'search_code':
                payload = {
                    'results': raw.get('results', []),
                    'totalFiles': raw.get('totalFiles', 0),
                    'totalMatches': raw.get('totalMatches', 0),
                }
                formatted['content'] = json.dumps(payload, ensure_ascii=False)[:self.MAX_RESULT_LENGTH]
            else:
                content_fields = {
                    'read_file': 'content',
                    'write_file': 'path',
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
                    formatted['content'] = content[:self.MAX_RESULT_LENGTH]
                else:
                    formatted['content'] = json.dumps(raw, ensure_ascii=False, indent=2)[:self.MAX_RESULT_LENGTH]

            if len(str(raw)) > self.MAX_RESULT_LENGTH:
                formatted['truncated'] = True
        else:
            formatted['error'] = raw.get('error', 'unknown error')

        formatted['tool'] = tool_name
        return formatted

"""工具注册表 — 管理所有可用工具的注册、Schema 提供和执行匹配。"""
import inspect
import typing
from typing import get_type_hints, get_origin, get_args, Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field

from services.file_utils import read_file_content, write_file_content, list_directory
from services.search_utils import search_project
from services.web_search_utils import search_web
from services.git_utils import get_git_status, get_git_diff, get_recent_commits
from services.terminal_utils import execute_command


# ── 数据模型 ──────────────────────────────────────────────────

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable
    requires_approval: bool = False
    tags: List[str] = field(default_factory=list)


# ── Python → JSON Schema 类型映射 ─────────────────────────────

_TYPE_MAP = {
    str:   {'type': 'string'},
    int:   {'type': 'integer'},
    float: {'type': 'number'},
    bool:  {'type': 'boolean'},
    list:  {'type': 'array'},
    dict:  {'type': 'object'},
}


def _resolve_jsonschema(annotation):
    """将 Python 类型注解转为 JSON Schema 片段

    Optional[X] 的 get_origin() 返回 typing.Union，需检查 origin is typing.Union。
    """
    origin = get_origin(annotation)

    # List[X] → {"type": "array", "items": ...}
    if origin is list:
        args = get_args(annotation)
        item_type = args[0] if args else str
        return {'type': 'array', 'items': _resolve_jsonschema(item_type)}

    # Dict[K, V] → {"type": "object"}
    if origin is dict:
        return {'type': 'object'}

    # Optional[X] / Union[X, None] → 解包为 X
    if origin is typing.Union:
        args = get_args(annotation)
        non_none_args = [a for a in args if a is not type(None)]
        if non_none_args:
            return _resolve_jsonschema(non_none_args[0])
        return {'type': 'string'}

    return _TYPE_MAP.get(annotation, {'type': 'string'})


def _parse_docstring_params(doc: str) -> dict[str, str]:
    """从 docstring 的 Args: 块提取参数名 → 描述"""
    if not doc:
        return {}
    params = {}
    in_args = False
    for line in doc.split('\n'):
        stripped = line.strip()
        if stripped.startswith('Args:'):
            in_args = True
            continue
        if in_args:
            if stripped.startswith('Returns:') or stripped.startswith('Raises:'):
                in_args = False
            elif stripped:
                parts = stripped.split(':', 1)
                if len(parts) == 2:
                    pname = parts[0].strip().split()[0]
                    params[pname] = parts[1].strip()
    return params


# ── @tool 装饰器 ──────────────────────────────────────────────

def tool(name=None, description=None, requires_approval=False, tags=None):
    """装饰器：将函数注册为智能体工具，自动推导参数 Schema。

    用法:
        @tool(tags=['filesystem', 'read'])
        def read_file(path: str) -> dict:
            \"\"\"读取指定文件的内容。

            Args:
                path: 文件的绝对路径
            \"\"\"
            ...

    装饰器自动完成:
        - 工具名 = 函数名（或 name 参数）
        - 描述 = docstring 首行（或 description 参数）
        - 参数 Schema = 从类型注解 + docstring Args 块推导
        - 自动注册到全局 ToolRegistry
    """
    def decorator(func):
        tool_name = name or func.__name__
        doc = inspect.getdoc(func) or ''
        tool_desc = description or (doc.split('\n')[0] if doc else tool_name)
        sig = inspect.signature(func)
        type_hints = get_type_hints(func) if func.__annotations__ else {}
        param_descs = _parse_docstring_params(doc)

        properties = {}
        required = []
        for pname, param in sig.parameters.items():
            if pname in ('self', 'cls'):
                continue
            annotation = type_hints.get(pname, str)
            prop = _resolve_jsonschema(annotation)
            prop['description'] = param_descs.get(pname, f'Parameter: {pname}')
            properties[pname] = prop
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        parameters = {'type': 'object', 'properties': properties}
        if required:
            parameters['required'] = required

        td = ToolDefinition(
            name=tool_name,
            description=tool_desc,
            parameters=parameters,
            handler=func,
            requires_approval=requires_approval,
            tags=tags or [],
        )
        ToolRegistry.get_instance().register(td)
        return func
    return decorator


# ── 注册表 ────────────────────────────────────────────────────

class ToolRegistry:
    """工具注册表 — 单例，全局唯一。"""

    _instance: Optional['ToolRegistry'] = None

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        # 核心工具通过模块底部的 @tool 装饰器自动注册，不在此处调用

    @classmethod
    def get_instance(cls) -> 'ToolRegistry':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> Dict[str, ToolDefinition]:
        return dict(self._tools)

    def build_openai_tools_spec(self) -> List[Dict[str, Any]]:
        """构建 OpenAI API `tools` 参数"""
        return [
            {
                'type': 'function',
                'function': {
                    'name': t.name,
                    'description': t.description,
                    'parameters': t.parameters,
                }
            }
            for t in self._tools.values()
        ]


# ── 核心工具定义（使用 @tool 装饰器） ──────────────────────────

@tool(name='read_file', tags=['filesystem', 'read'])
def _read_file_tool(path: str) -> dict:
    """读取指定文件的内容。适用于查看代码文件、配置文件、文档等。

    Args:
        path: 文件的绝对路径
    """
    return read_file_content(path)


@tool(name='write_file', requires_approval=True, tags=['filesystem', 'write'])
def _write_file_tool(path: str, content: str) -> dict:
    """向指定文件写入内容。注意：这会覆盖原文件内容。需要用户确认。

    Args:
        path: 文件的绝对路径
        content: 要写入的文件内容
    """
    return write_file_content(path, content)


@tool(name='list_files', tags=['filesystem', 'read'])
def _list_files_tool(path: str, depth: int = 1) -> dict:
    """列出指定目录下的文件和子目录。适用于探索项目结构。

    Args:
        path: 目录的绝对路径
        depth: 递归深度（1-3），默认 1
    """
    return list_directory(path, depth=depth)


@tool(name='search_code', tags=['search', 'read'])
def _search_code_tool(query: str, project_path: str = None) -> dict:
    """在项目中搜索代码，支持文件名和文件内容匹配。

    Args:
        query: 搜索关键词
        project_path: 限定搜索的项目路径（可选）
    """
    return search_project(query, project_path)


@tool(name='web_search', tags=['search', 'web', 'read'])
def _web_search_tool(query: str, max_results: int = 5) -> dict:
    """搜索公开网页，支持多引擎自动降级。无需 API key。

    搜索引擎降级链（可通过 settings.json 的 searchEngine 配置覆盖）：
    1. DuckDuckGo（国际通用）
    2. Bing China（国内稳定）
    主引擎失败后自动切换备用引擎，支持代理配置（settings.json 的 searchProxy）。

    如需限定站点，可在 query 中加入 ``site:github.com``。

    Args:
        query: 搜索关键词
        max_results: 返回结果数量上限（1-20），默认 5
    """
    return search_web(query, max_results=max_results)


@tool(name='git_status', tags=['git', 'read'])
def _git_status_tool(project_path: str) -> dict:
    """查看 Git 仓库状态，显示修改、新增、删除、未跟踪的文件。

    Args:
        project_path: 项目目录的绝对路径
    """
    return get_git_status(project_path)


@tool(name='git_diff', tags=['git', 'read'])
def _git_diff_tool(project_path: str, staged: bool = False) -> dict:
    """查看 Git 差异，显示文件变更的具体内容。

    Args:
        project_path: 项目目录的绝对路径
        staged: 是否查看暂存区的差异
    """
    return get_git_diff(project_path, staged)


@tool(name='git_log', tags=['git', 'read'])
def _git_log_tool(project_path: str, count: int = 5) -> dict:
    """查看最近的 Git 提交记录，了解项目变更历史。

    Args:
        project_path: 项目目录的绝对路径
        count: 返回的提交数量，默认 5
    """
    return get_recent_commits(project_path, count)


@tool(name='run_command', requires_approval=True, tags=['terminal', 'write'])
async def _run_command_tool(command: str, cwd: str) -> dict:
    """在项目目录执行终端命令。仅允许安全的命令列表。需要用户确认。

    Args:
        command: 要执行的命令（仅限白名单命令）
        cwd: 命令执行的工作目录
    """
    return await execute_command(command, cwd)

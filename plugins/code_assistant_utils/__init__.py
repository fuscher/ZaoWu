"""code_assistant_utils — 智能体代码助手实用工具插件。

该插件通过 ``zaowu_register_agent_tools`` 钩子向 ZaoWu 智能体模块注册一组
安全、只读的辅助工具，增强智能体在代码分析、项目统计和日常开发任务中的能力。

同时通过 ``zaowu_plugin_detail_sections`` 在插件详情页展示 README 文档，
所有渲染逻辑均保留在插件内部，不侵入主程序业务。

所有工具函数均为纯函数或轻量级 IO 操作，不依赖 Quart request 上下文，
不修改主程序状态，符合 agent_module_design.md 中定义的插件扩展规范。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from quart import Blueprint, jsonify, request, send_file
from plugin_system.api import plugin_api
from services.tool_registry import ToolDefinition


# ── 插件常量 ─────────────────────────────────────────────────────────

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_MAX_README_SIZE = 1024 * 1024  # 1MB

_DEFAULT_CONFIG: Dict[str, Any] = {
    'default_timezone': 'local',
    'default_exclude_patterns': [
        'node_modules', '.git', '__pycache__',
        '.venv', 'venv', 'dist', 'build',
    ],
    'readme_enabled': True,
    'readme_path': 'README.md',
    'readme_theme': 'auto',
    'readme_refresh_seconds': 10,
}

_readme_cache: Dict[str, Any] = {}


# ── 配置读取辅助 ────────────────────────────────────────────────────

def _get_config() -> Dict[str, Any]:
    """读取插件合并配置；在钩子函数外部调用时返回安全默认值。"""
    try:
        return {**_DEFAULT_CONFIG, **dict(plugin_api.config)}
    except RuntimeError:
        return dict(_DEFAULT_CONFIG)


# ── README 读取辅助 ──────────────────────────────────────────────────

def _resolve_readme_path(cfg: Dict[str, Any]) -> str:
    """将配置中的 readme_path 解析为绝对路径。"""
    path = cfg.get('readme_path', 'README.md') or 'README.md'
    if os.path.isabs(path):
        return os.path.realpath(path)
    return os.path.realpath(os.path.join(_PLUGIN_DIR, path))


def _read_readme(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """读取 README 文件内容，使用 mtime 做简单缓存。"""
    path = _resolve_readme_path(cfg)
    if not os.path.isfile(path):
        return {'ok': False, 'error': f'not a file: {path}'}

    try:
        size = os.path.getsize(path)
        if size > _MAX_README_SIZE:
            return {'ok': False, 'error': f'file too large ({size} bytes)'}

        mtime = os.path.getmtime(path)
        cached = _readme_cache.get(path)
        if cached and cached['mtime'] == mtime:
            content = cached['content']
        else:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            _readme_cache[path] = {'mtime': mtime, 'content': content}

        return {
            'ok': True,
            'content': content,
            'mtime': mtime,
            'path': path,
            'size': size,
        }
    except UnicodeDecodeError:
        return {'ok': False, 'error': 'binary file cannot be read as text'}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


# ── 工具函数 ────────────────────────────────────────────────────────

def get_current_time(tz_name: str = 'local') -> Dict[str, Any]:
    """获取当前时间，支持本地时间或 UTC。

    Args:
        tz_name: 时区，'local' 或 'utc'，默认 'local'

    Returns:
        包含 ISO 格式时间戳、日期、时间、时区的字典
    """
    tz = tz_name.lower().strip()
    if tz == 'utc':
        now = datetime.now(timezone.utc)
        zone = 'UTC'
    else:
        now = datetime.now()
        zone = datetime.now().astimezone().tzname() or 'Local'

    return {
        'ok': True,
        'iso': now.isoformat(),
        'date': now.strftime('%Y-%m-%d'),
        'time': now.strftime('%H:%M:%S'),
        'timezone': zone,
        'timestamp': int(now.timestamp()),
    }


def count_code_lines(path: str, exclude_patterns: Optional[List[str]] = None) -> Dict[str, Any]:
    """统计指定文件或目录的代码行数。

    递归遍历目录时自动排除二进制文件和常见依赖/构建目录。

    Args:
        path: 文件或目录的绝对路径
        exclude_patterns: 要排除的目录名列表（可选，默认使用插件配置）

    Returns:
        包含总文件数、总行数、空行数、代码行数、注释行数的字典
    """
    if not path or not isinstance(path, str):
        return {'ok': False, 'error': 'path must be a non-empty string'}

    real_path = os.path.realpath(path)
    if not os.path.exists(real_path):
        return {'ok': False, 'error': f'path does not exist: {path}'}

    cfg = _get_config()
    excludes = exclude_patterns if exclude_patterns is not None else cfg.get(
        'default_exclude_patterns',
        ['node_modules', '.git', '__pycache__', '.venv', 'venv', 'dist', 'build'],
    )

    def _should_exclude(dir_name: str) -> bool:
        return any(pattern in dir_name for pattern in excludes)

    def _is_binary(filepath: str) -> bool:
        try:
            with open(filepath, 'rb') as f:
                chunk = f.read(8192)
            return b'\x00' in chunk
        except OSError:
            return True

    def _count_file(filepath: str) -> Dict[str, int]:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except OSError:
            return {'total': 0, 'blank': 0, 'code': 0, 'comment': 0}

        total = len(lines)
        blank = sum(1 for line in lines if line.strip() == '')
        comment = sum(1 for line in lines if line.strip().startswith(('#', '//', '*', '/*', '--', '<!--')))
        code = total - blank - comment
        return {
            'total': total,
            'blank': blank,
            'code': max(code, 0),
            'comment': max(comment, 0),
        }

    stats = {
        'files': 0,
        'total_lines': 0,
        'blank_lines': 0,
        'code_lines': 0,
        'comment_lines': 0,
    }

    if os.path.isfile(real_path):
        if _is_binary(real_path):
            return {'ok': False, 'error': 'binary file is not supported'}
        file_stats = _count_file(real_path)
        stats.update({
            'files': 1,
            'total_lines': file_stats['total'],
            'blank_lines': file_stats['blank'],
            'code_lines': file_stats['code'],
            'comment_lines': file_stats['comment'],
        })
    else:
        for root, dirs, files in os.walk(real_path):
            dirs[:] = [d for d in dirs if not _should_exclude(d)]
            for filename in files:
                filepath = os.path.join(root, filename)
                if _is_binary(filepath):
                    continue
                file_stats = _count_file(filepath)
                stats['files'] += 1
                stats['total_lines'] += file_stats['total']
                stats['blank_lines'] += file_stats['blank']
                stats['code_lines'] += file_stats['code']
                stats['comment_lines'] += file_stats['comment']

    return {
        'ok': True,
        'path': real_path,
        'files': stats['files'],
        'total_lines': stats['total_lines'],
        'blank_lines': stats['blank_lines'],
        'code_lines': stats['code_lines'],
        'comment_lines': stats['comment_lines'],
    }


def generate_uuid(count: int = 1) -> Dict[str, Any]:
    """生成一个或多个 UUID v4。

    Args:
        count: 生成的 UUID 数量，默认 1，最大 10

    Returns:
        包含 UUID 列表的字典
    """
    try:
        count = int(count)
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'count must be an integer'}

    if count < 1:
        count = 1
    if count > 10:
        count = 10

    uuids = [str(uuid.uuid4()) for _ in range(count)]
    return {
        'ok': True,
        'count': len(uuids),
        'uuids': uuids,
    }


def format_json(content: str, indent: int = 2) -> Dict[str, Any]:
    """格式化或校验 JSON 字符串。

    Args:
        content: 待格式化的 JSON 字符串
        indent: 缩进空格数，默认 2

    Returns:
        格式化后的 JSON 字符串或错误信息
    """
    if not isinstance(content, str):
        return {'ok': False, 'error': 'content must be a string'}

    try:
        indent = int(indent)
    except (TypeError, ValueError):
        indent = 2

    try:
        data = json.loads(content)
        formatted = json.dumps(data, ensure_ascii=False, indent=indent)
        return {
            'ok': True,
            'formatted': formatted,
            'is_valid': True,
        }
    except json.JSONDecodeError as exc:
        return {
            'ok': False,
            'error': f'invalid JSON: {exc}',
            'is_valid': False,
        }


# ── 生命周期钩子 ────────────────────────────────────────────────────

def zaowu_plugin_loaded():
    """插件模块被导入时调用。"""
    plugin_api.logger.info('code_assistant_utils loaded (v1.0.0)')


def zaowu_app_startup():
    """宿主应用启动完成后调用。"""
    cfg = _get_config()
    plugin_api.logger.info(
        'code_assistant_utils ready: timezone=%s, excludes=%d patterns',
        cfg.get('default_timezone', 'local'),
        len(cfg.get('default_exclude_patterns', [])),
    )


# ── 前端扩展钩子 ────────────────────────────────────────────────────

def zaowu_settings_sections():
    """注册插件设置页面分区。"""
    return [
        {
            'id': 'code_assistant_utils_settings',
            'label': {
                'zh-CN': '代码助手工具',
                'en': 'Code Assistant Utils',
            },
            'component': 'Settings',
            'icon': 'Puzzle',
            'order': 100,
        },
        {
            'id': 'code_assistant_utils_readme_settings',
            'label': {
                'zh-CN': 'README 查看器',
                'en': 'README Viewer',
            },
            'component': 'ReadmeSettings',
            'icon': 'BookOpen',
            'order': 110,
        },
    ]


def zaowu_plugin_detail_sections():
    """注册插件详情页分区。"""
    return [{
        'id': 'code_assistant_utils_readme',
        'label': {
            'zh-CN': 'README',
            'en': 'README',
        },
        'component': 'ReadmePanel',
        'order': 50,
    }]


def zaowu_register_routes():
    """注册 README 读取与资源服务路由。"""
    bp = Blueprint('code_assistant_utils', __name__, url_prefix='/api/plugins/code_assistant_utils')

    @bp.route('/readme', methods=['GET'])
    async def get_readme():
        cfg = _get_config()
        if not cfg.get('readme_enabled', True):
            return jsonify({'ok': False, 'error': 'readme viewer disabled'}), 403
        return jsonify(_read_readme(cfg))

    @bp.route('/readme-asset', methods=['GET'])
    async def get_readme_asset():
        src = request.args.get('src', '')
        if not src:
            return jsonify({'ok': False, 'error': 'missing src'}), 400

        cfg = _get_config()
        base_dir = os.path.dirname(_resolve_readme_path(cfg))
        target = os.path.realpath(os.path.join(base_dir, os.path.normpath(src)))

        # 防止路径穿越
        if os.path.commonpath([target, base_dir]) != base_dir:
            return jsonify({'ok': False, 'error': 'invalid path'}), 403
        if not os.path.isfile(target):
            return jsonify({'ok': False, 'error': 'not found'}), 404

        return await send_file(target)

    return [bp]


# ── 智能体工具注册钩子 ──────────────────────────────────────────────

def _build_parameters(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    """构造 OpenAI 函数调用风格的 parameters Schema。"""
    params = {'type': 'object', 'properties': properties}
    if required:
        params['required'] = required
    return params


def zaowu_register_agent_tools() -> List[ToolDefinition]:
    """向智能体模块注册本插件提供的工具。

    返回的 ToolDefinition 列表会被 PluginManager.collect_agent_tools()
    收集并注册到全局 ToolRegistry。
    """
    return [
        ToolDefinition(
            name='get_current_time',
            description='获取当前时间戳和日期时间信息，支持本地时间或 UTC。',
            parameters=_build_parameters({
                'tz_name': {
                    'type': 'string',
                    'description': "时区，'local' 或 'utc'，默认 'local'",
                    'enum': ['local', 'utc'],
                    'default': 'local',
                }
            }, []),
            handler=get_current_time,
            requires_approval=False,
            tags=['utility', 'read'],
        ),
        ToolDefinition(
            name='count_code_lines',
            description='统计指定文件或目录的代码行数、空行数和注释行数，自动排除依赖目录和二进制文件。',
            parameters=_build_parameters({
                'path': {
                    'type': 'string',
                    'description': '文件或目录的绝对路径',
                },
                'exclude_patterns': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': '要排除的目录名列表（可选）',
                }
            }, ['path']),
            handler=count_code_lines,
            requires_approval=False,
            tags=['filesystem', 'read', 'analysis'],
        ),
        ToolDefinition(
            name='generate_uuid',
            description='生成一个或多个 UUID v4，用于创建唯一标识符。',
            parameters=_build_parameters({
                'count': {
                    'type': 'integer',
                    'description': '生成的 UUID 数量，默认 1，最大 10',
                    'default': 1,
                    'minimum': 1,
                    'maximum': 10,
                }
            }, []),
            handler=generate_uuid,
            requires_approval=False,
            tags=['utility', 'read'],
        ),
        ToolDefinition(
            name='format_json',
            description='格式化或校验 JSON 字符串，返回美化后的 JSON 或错误信息。',
            parameters=_build_parameters({
                'content': {
                    'type': 'string',
                    'description': '待格式化的 JSON 字符串',
                },
                'indent': {
                    'type': 'integer',
                    'description': '缩进空格数，默认 2',
                    'default': 2,
                    'minimum': 1,
                    'maximum': 8,
                }
            }, ['content']),
            handler=format_json,
            requires_approval=False,
            tags=['utility', 'read'],
        ),
    ]

"""ToolExecutor 安全与格式化单元测试。"""
import asyncio
import json
import os

import pytest

from services.tool_registry import ToolRegistry
from services.tool_executor import ToolExecutor


@pytest.fixture
def executor(tmp_path):
    registry = ToolRegistry()
    return ToolExecutor(registry, project_bases=[str(tmp_path)])


@pytest.fixture
def real_executor():
    """使用真实项目目录的 executor，用于测试路径边界。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ToolExecutor(ToolRegistry.get_instance(), project_bases=[base])


def test_validate_path_inside_project(executor, tmp_path):
    inside = tmp_path / 'src' / 'main.py'
    inside.parent.mkdir()
    inside.write_text('print(1)', encoding='utf-8')
    assert executor.validate_path(str(inside)) is True


def test_validate_path_outside_project(executor, tmp_path):
    assert executor.validate_path('C:/Windows') is False
    assert executor.validate_path('/etc/passwd') is False
    assert executor.validate_path(str(tmp_path.parent)) is False


def test_validate_path_traversal(executor, tmp_path):
    inside = tmp_path / 'a.txt'
    inside.write_text('x', encoding='utf-8')
    traversal = str(tmp_path / '..' / 'a.txt')
    # realpath should resolve to tmp_path parent, outside base
    assert executor.validate_path(traversal) is False


def test_validate_arguments_missing_required(real_executor, tmp_path):
    read_tool = real_executor.registry.get('read_file')
    error = real_executor.validate_arguments(read_tool, {})
    assert error is not None
    assert 'missing required parameter' in error


def test_validate_arguments_path_not_in_project(real_executor):
    read_tool = real_executor.registry.get('read_file')
    error = real_executor.validate_arguments(read_tool, {'path': 'C:/Windows/system.ini'})
    assert error is not None
    assert 'path not in project' in error


def test_validate_arguments_write_path_ok(tmp_path):
    target = tmp_path / 'new_file.py'
    executor = ToolExecutor(ToolRegistry.get_instance(), project_bases=[str(tmp_path)])
    write_tool = executor.registry.get('write_file')
    error = executor.validate_arguments(
        write_tool,
        {'path': str(target), 'content': 'x = 1'},
    )
    assert error is None


def test_execute_unknown_tool(real_executor):
    result = asyncio.run(real_executor.execute('unknown_tool', {}))
    assert result['success'] is False
    assert 'not found' in result['error']


def test_execute_validation_failure(real_executor):
    result = asyncio.run(real_executor.execute('read_file', {'path': 'C:/Windows'}))
    assert result['success'] is False
    assert 'path not in project' in result['error']


def test_format_result_run_command(real_executor):
    raw = {'ok': True, 'output': 'hello', 'exitCode': 0}
    formatted = real_executor._format_result(raw, 'run_command')
    assert formatted['success'] is True
    payload = json.loads(formatted['content'])
    assert payload['output'] == 'hello'
    assert payload['exitCode'] == 0


def test_format_result_search_code(real_executor):
    raw = {
        'ok': True,
        'results': [{'path': '/p/a.py', 'matches': []}],
        'totalFiles': 1,
        'totalMatches': 0,
    }
    formatted = real_executor._format_result(raw, 'search_code')
    assert formatted['success'] is True
    payload = json.loads(formatted['content'])
    assert payload['totalFiles'] == 1
    assert payload['totalMatches'] == 0


def test_format_result_error(real_executor):
    raw = {'ok': False, 'error': 'something bad'}
    formatted = real_executor._format_result(raw, 'read_file')
    assert formatted['success'] is False
    assert formatted['error'] == 'something bad'


def test_result_truncation(real_executor):
    long_content = 'x' * 20_000
    raw = {'ok': True, 'content': long_content}
    formatted = real_executor._format_result(raw, 'read_file')
    assert len(formatted['content']) <= ToolExecutor.MAX_RESULT_LENGTH
    assert formatted.get('truncated') is True


def test_truncated_flag_not_set_when_content_under_limit(monkeypatch):
    """N2 回归：truncated 标志应基于序列化后实际内容长度，而非 str(raw)。

    旧实现用 len(str(raw)) 比较，dict repr 的开销会让「未实际截断」的内容
    误报 truncated=True。此处 content 长度 45 < 50（未截断），但
    str({'ok': True, 'content': 'x'*45}) 的 repr 长度 > 50。
    """
    monkeypatch.setattr(ToolExecutor, 'MAX_RESULT_LENGTH', 50)
    executor = ToolExecutor(ToolRegistry(), project_bases=['/tmp'])
    raw = {'ok': True, 'content': 'x' * 45}
    formatted = executor._format_result(raw, 'read_file')
    assert 'truncated' not in formatted, '内容未超限不应标记 truncated'
    assert len(formatted['content']) == 45


def test_truncated_flag_set_and_content_capped_when_over_limit(monkeypatch):
    """N2：内容超限时 truncated=True 且 content 截断到上限长度。"""
    monkeypatch.setattr(ToolExecutor, 'MAX_RESULT_LENGTH', 50)
    executor = ToolExecutor(ToolRegistry(), project_bases=['/tmp'])
    raw = {'ok': True, 'content': 'x' * 200}
    formatted = executor._format_result(raw, 'read_file')
    assert formatted.get('truncated') is True
    assert len(formatted['content']) == 50


def test_format_result_write_file_packs_json(real_executor):
    raw = {'ok': True, 'path': '/p/a.py', 'diff': '--- a/a.py\n+++ b/a.py\n',
           'created': True, 'bytes_written': 10}
    formatted = real_executor._format_result(raw, 'write_file')
    assert formatted['success'] is True
    payload = json.loads(formatted['content'])
    assert payload['path'] == '/p/a.py'
    assert 'diff' in payload
    assert payload['created'] is True


def test_format_result_edit_file_packs_json(real_executor):
    raw = {'ok': True, 'path': '/p/a.py', 'diff': '--- a/a.py\n+++ b/a.py\n',
           'replacements': 2, 'bytes_written': 10}
    formatted = real_executor._format_result(raw, 'edit_file')
    assert formatted['success'] is True
    payload = json.loads(formatted['content'])
    assert payload['replacements'] == 2
    assert 'diff' in payload


def test_format_result_write_file_truncation(real_executor):
    long_diff = 'x' * 20_000
    raw = {'ok': True, 'path': '/p/a.py', 'diff': long_diff, 'created': False}
    formatted = real_executor._format_result(raw, 'write_file')
    assert len(formatted['content']) <= ToolExecutor.MAX_RESULT_LENGTH
    assert formatted.get('truncated') is True


def test_validate_arguments_edit_file_path_not_in_project(real_executor):
    edit_tool = real_executor.registry.get('edit_file')
    error = real_executor.validate_arguments(
        edit_tool,
        {'path': 'C:/Windows/system.ini', 'old_string': 'a', 'new_string': 'b'},
    )
    assert error is not None
    assert 'path not in project' in error


def test_validate_arguments_edit_file_path_ok(tmp_path):
    target = tmp_path / 'edit_target.py'
    target.write_text('old code', encoding='utf-8')
    executor = ToolExecutor(ToolRegistry.get_instance(), project_bases=[str(tmp_path)])
    edit_tool = executor.registry.get('edit_file')
    error = executor.validate_arguments(
        edit_tool,
        {'path': str(target), 'old_string': 'old', 'new_string': 'new'},
    )
    assert error is None


def test_execute_edit_file_missing_required(real_executor):
    result = asyncio.run(real_executor.execute('edit_file', {'path': '/tmp/x.py'}))
    assert result['success'] is False
    assert 'missing required parameter' in result['error']


# ── 4.2 类型/枚举校验 ──────────────────────────────────────────


def test_check_type_integer_rejects_string(real_executor, tmp_path):
    """read_file(limit='abc') 应在 handler 前拦截，而非让 handler 抛异常。"""
    read_tool = real_executor.registry.get('read_file')
    target = tmp_path / 'a.py'  # tmp_path 不在 real_executor 的 base 内，故用 base 内文件
    # 用 base 内的真实文件避免路径校验先失败
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    inside = os.path.join(base, 'README.md')
    if not os.path.exists(inside):
        inside = os.path.join(base, 'pyproject.toml')
    error = real_executor.validate_arguments(
        read_tool, {'path': inside, 'limit': 'abc'}
    )
    assert error is not None
    assert 'expected integer' in error and 'got string' in error


def test_check_type_integer_rejects_bool(real_executor):
    """bool 是 int 子类，必须显式排除，否则 True 冒充 integer 通过。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    inside = os.path.join(base, 'pyproject.toml')
    read_tool = real_executor.registry.get('read_file')
    error = real_executor.validate_arguments(
        read_tool, {'path': inside, 'limit': True}
    )
    assert error is not None
    assert 'expected integer' in error and 'got boolean' in error


def test_check_type_number_rejects_bool():
    """number 类型同样要排除 bool（True 通过 isinstance(_,(int,float))）。"""
    err = ToolExecutor._check_type('x', True, {'type': 'number'})
    assert err is not None
    assert 'expected number' in err and 'got boolean' in err


def test_check_type_number_accepts_int_and_float():
    assert ToolExecutor._check_type('x', 3, {'type': 'number'}) is None
    assert ToolExecutor._check_type('x', 3.14, {'type': 'number'}) is None


def test_check_type_string_enum_violation():
    """enum 校验对所有类型生效，string enum 也要触发（原方案锁死 integer 分支）。"""
    spec = {'type': 'string', 'enum': ['asc', 'desc']}
    assert ToolExecutor._check_type('order', 'sideways', spec) is not None
    assert "not in" in ToolExecutor._check_type('order', 'sideways', spec)
    assert ToolExecutor._check_type('order', 'asc', spec) is None


def test_check_type_none_skipped():
    """None 视为未提供，交由 handler 默认值处理（兼容 project_path=None 等）。"""
    assert ToolExecutor._check_type('x', None, {'type': 'string'}) is None
    assert ToolExecutor._check_type('x', None, {'type': 'integer'}) is None


def test_check_type_valid_types_pass(real_executor):
    """合法类型组合不应被新校验拦截。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    inside = os.path.join(base, 'pyproject.toml')
    read_tool = real_executor.registry.get('read_file')
    error = real_executor.validate_arguments(
        read_tool, {'path': inside, 'offset': 1, 'limit': 2000}
    )
    assert error is None


def test_execute_type_mismatch_returns_structured_error(real_executor):
    """类型错误经 execute 返回结构化失败结果，注入消息历史供模型自我修正。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    inside = os.path.join(base, 'pyproject.toml')
    result = asyncio.run(real_executor.execute('read_file', {'path': inside, 'limit': 'abc'}))
    assert result['success'] is False
    assert 'expected integer' in result['error']

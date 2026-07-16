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

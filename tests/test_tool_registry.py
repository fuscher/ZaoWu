"""ToolRegistry / @tool decorator 单元测试。"""
import pytest

from services.tool_registry import ToolRegistry, ToolDefinition, tool


def test_core_tools_auto_registered():
    registry = ToolRegistry.get_instance()
    names = set(registry.list_tools().keys())
    expected = {
        'read_file', 'write_file', 'list_files', 'search_code', 'web_search',
        'git_status', 'git_diff', 'git_log', 'run_command',
    }
    assert names == expected


def test_build_openai_tools_spec_count():
    registry = ToolRegistry.get_instance()
    spec = registry.build_openai_tools_spec()
    assert len(spec) == 9
    assert all(item['type'] == 'function' for item in spec)


def test_tool_metadata():
    registry = ToolRegistry.get_instance()
    read_tool = registry.get('read_file')
    assert read_tool is not None
    assert read_tool.name == 'read_file'
    assert '读取' in read_tool.description or 'read' in read_tool.description.lower()
    assert 'path' in read_tool.parameters['properties']
    assert 'path' in read_tool.parameters.get('required', [])
    assert read_tool.tags == ['filesystem', 'read']
    assert read_tool.requires_approval is False


def test_write_file_requires_approval():
    registry = ToolRegistry.get_instance()
    tool_def = registry.get('write_file')
    assert tool_def is not None
    assert tool_def.requires_approval is True


def test_optional_parameter_schema():
    registry = ToolRegistry.get_instance()
    search_tool = registry.get('search_code')
    props = search_tool.parameters['properties']
    assert 'query' in props
    assert 'project_path' in props
    assert 'query' in search_tool.parameters.get('required', [])
    assert 'project_path' not in search_tool.parameters.get('required', [])


def test_default_value_not_required():
    registry = ToolRegistry.get_instance()
    git_log = registry.get('git_log')
    assert 'count' in git_log.parameters['properties']
    assert 'count' not in git_log.parameters.get('required', [])


def test_custom_tool_registration():
    """直接注册自定义工具到独立注册表，避免污染全局单例。"""
    registry = ToolRegistry()

    def hello(name: str) -> dict:
        return {'ok': True, 'message': f'Hello, {name}'}

    td = ToolDefinition(
        name='hello_tool',
        description='Say hello.',
        parameters={
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'user name'},
            },
            'required': ['name'],
        },
        handler=hello,
        tags=['demo'],
    )
    registry.register(td)

    assert registry.get('hello_tool') is td
    assert registry.build_openai_tools_spec()[0]['function']['name'] == 'hello_tool'
    assert td.handler(name='World') == {'ok': True, 'message': 'Hello, World'}


def test_register_tool_definition_directly():
    registry = ToolRegistry()
    td = ToolDefinition(
        name='direct_tool',
        description='A direct tool.',
        parameters={'type': 'object', 'properties': {}},
        handler=lambda: None,
    )
    registry.register(td)
    assert registry.get('direct_tool') is td


def test_unknown_tool_returns_none():
    registry = ToolRegistry.get_instance()
    assert registry.get('nonexistent_tool') is None
